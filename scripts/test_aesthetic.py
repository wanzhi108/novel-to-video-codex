"""测试 aesthetic-predictor-v2-5：对生成的漫剧关键帧打审美分。"""
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from PIL import Image
import torch
from aesthetic_predictor_v2_5 import convert_v2_5_from_siglip

print("loading siglip v2.5 aesthetic predictor (via hf-mirror)...", flush=True)
model, processor = convert_v2_5_from_siglip(low_cpu_mem_usage=True)
model = model.to(torch.bfloat16).cuda().eval()
print("model loaded", flush=True)

imgs = [
    r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\lkL_s1_kf.png",   # A+C 药铺+叶玄机
    r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\lkL_s5_kf.png",   # A+C 掌柜
    r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\lk_s2_kf.png",    # A 版卧房
    r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\t2i_s6_kf.png",   # 划痕木纹
]
for p in imgs:
    if not os.path.exists(p):
        print("missing", p); continue
    im = Image.open(p).convert("RGB")
    px = processor(images=im, return_tensors="pt").pixel_values.to(torch.bfloat16).cuda()
    with torch.inference_mode():
        score = model(px).logits.squeeze().item()
    print(f"{os.path.basename(p)}: aesthetic={score:.3f}", flush=True)
