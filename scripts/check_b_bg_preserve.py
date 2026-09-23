"""量化验证 B：遮罩外背景是否像素级保留（对比主背景与 inpaint 结果）。"""
from PIL import Image
import numpy as np

master = Image.open(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\asset_scene_qiantang.png").convert("RGB")
res = Image.open(r"D:\novel-to-video-codex\output\b_inpaint\b2_obj.png").convert("RGB")
print("master size", master.size, "res size", res.size)
a = np.asarray(master.resize(res.size)).astype(np.int16)
b = np.asarray(res).astype(np.int16)
diff = np.abs(a - b).mean(axis=2)  # per-pixel mean abs diff
W, H = res.size
mask = np.zeros((H, W), dtype=bool)
mask[640:980, 430:780] = True   # b2 的遮罩区域(含 grow)
outside = diff[~mask]
inside = diff[mask]
print(f"OUTSIDE mask: mean|diff|={outside.mean():.2f}  max={outside.max():.0f}  %pixels>8={100*(outside>8).mean():.1f}%")
print(f"INSIDE  mask: mean|diff|={inside.mean():.2f}  max={inside.max():.0f}")
