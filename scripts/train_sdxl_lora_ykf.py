"""C: 用 diffusers+PEFT 从单文件 RealVisXL 训练"药铺场景" SDXL LoRA。
思路：from_single_file 加载 SDXL → 冻结 VAE/文本编码器 → 给 UNet 挂 LoRA → DreamBooth 式去噪训练
→ 保存为 ComfyUI 可加载的 LoRA (.safetensors)。
8GB：fp16 + 梯度检查点 + batch1 + 低分辨率(512x768) + 少步数。
"""
import argparse, os, sys, glob, random
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

CKPT = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\checkpoints\RealVisXL_V4.0.safetensors"
DATA = r"D:\novel-to-video-codex\dataset\yhkf"
OUT = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\loras\ykf_scene.safetensors"
INSTANCE = "a photo of sks chinese herbal medicine shop"


class SceneDataset(Dataset):
    def __init__(self, folder, size=512):
        self.files = sorted(glob.glob(os.path.join(folder, "*.png")))
        self.size = size
        # 中心裁方（保比例不压扁）再缩到 size
        self.tf = transforms.Compose([
            transforms.CenterCrop(size),   # size=512*? 先裁成 512 的正方形区域
            transforms.Resize((size, size), interpolation=Image.LANCZOS),
            transforms.ToTensor(),
            transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
        ])

    def __len__(self):
        return len(self.files)

    def __getitem__(self, i):
        img = Image.open(self.files[i]).convert("RGB")
        return self.tf(img)


def collate_fn(items):
    return torch.stack(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolution", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max_steps", type=int, default=200)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    print("loading SDXL from_single_file...", flush=True)
    from diffusers import StableDiffusionXLPipeline, AutoencoderKL, DDPMScheduler
    pipe = StableDiffusionXLPipeline.from_single_file(
        CKPT, torch_dtype=torch.float16, use_safetensors=True, local_files_only=True)
    pipe.safety_checker = None
    print("loaded", flush=True)

    unet = pipe.unet
    vae = pipe.vae
    te1 = pipe.text_encoder
    te2 = pipe.text_encoder_2
    sched = pipe.scheduler  # PNDM default; use DDPMScheduler for noise

    # 强制 fp16 + 冻结
    for m in (vae, te1, te2):
        m.requires_grad_(False)
        m.eval()
    unet.requires_grad_(False)
    unet.enable_gradient_checkpointing()

    # 给 UNet 挂 LoRA
    from peft import LoraConfig, get_peft_model
    lora_cfg = LoraConfig(
        r=args.rank, lora_alpha=args.rank, target_modules=["to_q", "to_k", "to_v"],
        lora_dropout=0.0, bias="none")
    unet = get_peft_model(unet, lora_cfg)
    unet.train()
    # 只有 LoRA 参数可训练
    trainable = [p for n, p in unet.named_parameters() if "lora" in n]
    for p in unet.parameters():
        p.requires_grad = False
    for p in trainable:
        p.requires_grad = True
        p.data = p.data.float()   # LoRA 主权重保持 fp32（AMP 稳定）
    print("trainable loRA params:", sum(p.numel() for p in trainable), flush=True)

    # 文本编码：文本编码器放 CPU 一次性编码（SDXL 需 2048-d prompt_embeds + 1280-d pooled text_embeds）
    with torch.no_grad():
        te1 = te1.to("cpu"); te2 = te2.to("cpu")
        ids1 = pipe.tokenizer(INSTANCE, padding="max_length", max_length=77, truncation=True,
                              return_tensors="pt").input_ids
        ids2 = pipe.tokenizer_2(INSTANCE, padding="max_length", max_length=77, truncation=True,
                                return_tensors="pt").input_ids
        e1 = te1(ids1).last_hidden_state                 # (1,77,768)
        o2 = te2(ids2)
        e2 = o2.last_hidden_state                        # (1,77,1280) openCLIP-G
        if hasattr(o2, "text_embeds"):
            pooled = o2.text_embeds
        elif hasattr(o2, "pooler_output"):
            pooled = o2.pooler_output
        else:
            pooled = e2.mean(dim=1)
        prompt_embeds = torch.cat([e1, e2], dim=-1).squeeze(0).to("cuda")  # (77,2048)
        pooled = pooled.squeeze(0).to("cuda")             # (1280,) -> added_cond text_embeds

    # 噪声调度
    ddpm = DDPMScheduler(num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear")
    ddpm.set_timesteps(1000)

    ds = SceneDataset(DATA, args.resolution)
    dl = DataLoader(ds, batch_size=1, shuffle=True, collate_fn=collate_fn, num_workers=0)

    # 把 VAE/text encoder 都放到 CPU 或 fp16？SDXL 训练一般 VAE 在 fp16。这里 unet 在 GPU。
    vae = vae.to("cuda", dtype=torch.float16)
    unet = unet.to("cuda")   # base 保持 fp16；LoRA 已 cast 为 fp32，避免被一并转回 fp16

    opt = torch.optim.AdamW(trainable, lr=args.lr)
    from torch.amp import autocast, GradScaler
    scaler = GradScaler("cuda")
    step = 0
    print("start training...", flush=True)
    for ep in range(args.epochs):
        for batch in dl:
            if step >= args.max_steps:
                break
            pixel = batch.to("cuda", dtype=torch.float16)
            with torch.no_grad():
                latents = vae.encode(pixel).latent_dist.sample() * 0.18215
            noise = torch.randn_like(latents)
            t = torch.randint(0, 1000, (latents.shape[0],), device="cuda")
            noisy = ddpm.add_noise(latents, noise, t)
            time_ids = torch.tensor([[args.resolution, args.resolution, 0, 0, args.resolution, args.resolution]],
                                    dtype=torch.float16, device="cuda")
            add_cond = {"text_embeds": pooled.unsqueeze(0).to("cuda", dtype=torch.float16),
                        "time_ids": time_ids}
            with autocast(device_type="cuda", dtype=torch.float16):
                pred = unet(noisy, t, encoder_hidden_states=prompt_embeds.unsqueeze(0).to("cuda", dtype=torch.float16),
                            added_cond_kwargs=add_cond).sample
                loss = torch.nn.functional.mse_loss(pred.float(), noise.float())
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(unet.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            if step % 10 == 0 or step == 0:
                print(f"ep{ep} step{step} loss={loss.item():.4f}", flush=True)
            step += 1
    print("training done step=", step, flush=True)

    # 保存为 ComfyUI 可加载的 diffusers 格式 LoRA
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    from peft import get_peft_model_state_dict
    unet_lora_state = get_peft_model_state_dict(unet)
    try:
        pipe.save_lora_weights(
            os.path.dirname(args.out), unet_lora_layers=unet_lora_state,
            weight_name=os.path.basename(args.out))
        print("SAVED LoRA:", args.out, round(os.path.getsize(args.out)/1e6,1), "MB", flush=True)
    except Exception as e:
        print("save_lora_weights FAIL:", str(e)[:300], flush=True)
        # 手动写 diffusers PEFT 格式（ComfyUI LoraLoader 也能读）
        import safetensors.torch
        # peft state dict keys: base_model.model.<unet>.<module>.<lora>
        cleaned = {}
        for k, v in unet_lora_state.items():
            nk = k.replace("base_model.model.", "")
            cleaned[nk] = v
        safetensors.torch.save_file(cleaned, args.out, {"ss_sd_model_name": "RealVisXL"})
        print("SAVED manual LoRA:", args.out, round(os.path.getsize(args.out)/1e6,1), "MB", flush=True)


if __name__ == "__main__":
    main()
