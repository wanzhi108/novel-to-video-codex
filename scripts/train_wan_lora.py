"""Wan 2.2 I2V-A14B 角色 LoRA 训练脚本（diffusers + PEFT）。

⚠ 硬件要求：Wan 2.2 A14B 是 ~27B(MoE)/14B 模型，LoRA 训练需 **≥24GB 显存**（建议 40GB/A100）。
  8GB 显存机器无法本地训练本模型 LoRA —— 这是硬件硬约束，不是脚本问题。
  请在云上（A100/L40S）或高显存机器运行；训练好的 LoRA 放 ComfyUI/models/loras，
  通过 engines/wan.py 的 WanEngine(lora=[...]) 加载（部分 1 已实现）。

用法示例：
  python train_wan_lora.py \
    --base_model W-AI/Wan2.2-I2V-A14B \
    --dataset ./dataset/my_char \        # 每个子目录=一个概念；每目录放该角色 15~30 张图
    --output_dir ./out/wan_char_lora \
    --instance_prompt "a photo of sks person" \
    --resolution 480 --num_epochs 5
"""
import argparse
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_model", default="Wan-AI/Wan2.2-I2V-A14B")
    ap.add_argument("--dataset", required=True, help="角色图片目录（含 instance images）")
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--instance_prompt", required=True)
    ap.add_argument("--resolution", type=int, default=480)
    ap.add_argument("--num_epochs", type=int, default=5)
    ap.add_argument("--lora_rank", type=int, default=64)
    ap.add_argument("--learning_rate", type=float, default=1e-4)
    ap.add_argument("--batch_size", type=int, default=1)
    args = ap.parse_args()

    # 依赖：需在目标机器安装
    #   pip install "diffusers[training]" peft accelerate safetensors transformers
    try:
        import torch
        from diffusers import AutoencoderKLWan, WanTransformer2DModel, WanPipeline
        from diffusers.optimization import get_scheduler
        from peft import LoraConfig, get_peft_model
        from torch.utils.data import DataLoader, Dataset
        from torchvision import transforms
        from PIL import Image
        import torch.nn.functional as F
    except ImportError as exc:
        raise SystemExit(
            f"缺少训练依赖: {exc}\n请安装: pip install \"diffusers[training]\" peft accelerate safetensors transformers"
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[train] 使用 device={device}; 显存 {torch.cuda.get_device_properties(0).total_memory/1e9:.0f}GB")

    # ─── 数据 ──────────────────────────────────────────────
    class ImgDataset(Dataset):
        def __init__(self, folder, size=args.resolution):
            self.files = [p for p in Path(folder).glob("*.png")] + \
                         [p for p in Path(folder).glob("*.jpg")] + \
                         [p for p in Path(folder).glob("*.jpeg")] + \
                         [p for p in Path(folder).glob("*.webp")]
            self.tf = transforms.Compose([
                transforms.Resize((size, size), interpolation=transforms.InterpolationMode.LANCZOS),
                transforms.ToTensor(),
            ])

        def __len__(self):
            return len(self.files)

        def __getitem__(self, i):
            img = Image.open(self.files[i]).convert("RGB")
            return self.tf(img)

    ds = ImgDataset(args.dataset)
    if len(ds) < 10:
        print(f"[train] 警告: 只有 {len(ds)} 张图，建议 ≥15~30 张以保证一致性。")
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True, num_workers=0)

    # ─── 模型 ──────────────────────────────────────────────
    print("[train] 载入 Wan2.2 A14B …（需大显存）")
    pipe = WanPipeline.from_pretrained(args.base_model, torch_dtype=torch.bfloat16)
    unet = pipe.transformer  # WanTransformer2DModel
    vae = pipe.vae
    tokenizer = pipe.tokenizer
    text_encoder = pipe.text_encoder
    scheduler = pipe.scheduler
    unet.requires_grad_(False)
    vae.requires_grad_(False)
    text_encoder.requires_grad_(False)

    lora = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_rank,
        target_modules=["to_q", "to_k", "to_v", "to_out.0", "ff.net.0.proj",
                        "ff.net.2", "norm1", "norm2"],
        init_lora_weights="gaussian",
    )
    unet = get_peft_model(unet, lora)
    unet.to(device)
    unet.train()

    opt = torch.optim.AdamW(unet.parameters(), lr=args.learning_rate)
    lr_sched = get_scheduler("constant", optimizer=opt, num_warmup_steps=0, num_training_steps=args.num_epochs * len(dl))
    vae.eval()

    # ─── 训练循环（简化版）───────────────────────────────
    print(f"[train] 开始训练 {args.num_epochs} 轮，每轮 {len(dl)} 步 …")
    for epoch in range(args.num_epochs):
        for step, imgs in enumerate(dl):
            imgs = imgs.to(device, dtype=torch.bfloat16)
            latents = vae.encode(imgs).latent_dist.sample() * vae.config.scaling_factor
            latents = latents.to(dtype=torch.bfloat16)
            noise = torch.randn_like(latents)
            t = torch.randint(0, scheduler.config.num_train_timesteps, (latents.shape[0],), device=device)
            noisy = scheduler.add_noise(latents, noise, t)
            prompt_ids = tokenizer([args.instance_prompt], padding="max_length", max_length=512,
                                   truncation=True, return_tensors="pt").input_ids.to(device)
            encoder_hidden = text_encoder(prompt_ids)[0].to(dtype=torch.bfloat16)
            pred = unet(noisy, t, encoder_hidden_states=encoder_hidden).sample
            loss = F.mse_loss(pred.float(), noise.float())
            loss.backward()
            opt.step(); lr_sched.step(); opt.zero_grad()
            if step % 5 == 0:
                print(f"  epoch {epoch} step {step}: loss {loss.item():.4f}", flush=True)

    # ─── 保存 ──────────────────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)
    out = Path(args.output_dir) / "wan_char_lora.safetensors"
    unet.save_pretrained(args.output_dir, safe_serialization=True)
    print(f"[train] 完成，LoRA 已保存到 {args.output_dir}")
    print(f"[train] 使用时: WanEngine(lora=[{{'name': '{out.name}', 'strength': 0.8}}])")


if __name__ == "__main__":
    main()
