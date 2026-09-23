"""下载 SDXL 非人脸 IP-Adapter（场景/风格参考），供资产锁定管线 A/B 用。"""
import os, sys
try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("need huggingface_hub"); sys.exit(1)

dest_dir = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\ipadapter"
os.makedirs(dest_dir, exist_ok=True)

# h94/IP-Adapter:  sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors  (~808MB)
files = [
    ("h94/IP-Adapter", "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"),
]
for repo, fn in files:
    out = os.path.join(dest_dir, os.path.basename(fn))
    if os.path.exists(out) and os.path.getsize(out) > 1e8:
        print("SKIP (exists):", out, round(os.path.getsize(out)/1e6,1), "MB"); continue
    print("downloading", fn, "...", flush=True)
    p = hf_hub_download(repo_id=repo, filename=fn, force_download=False)
    import shutil
    shutil.copyfile(p, out)
    print("SAVED:", out, round(os.path.getsize(out)/1e6,1), "MB", flush=True)
print("done")
