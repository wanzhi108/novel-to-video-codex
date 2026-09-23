"""下载 Wan 2.2 Animate 14B GGUF Q4_K_M (11.5GB) 到 diffusion_models。"""
import os
import time
import requests

url = "https://huggingface.co/QuantStack/Wan2.2-Animate-14B-GGUF/resolve/main/Wan2.2-Animate-14B-Q4_K_M.gguf"
dest_dir = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\diffusion_models"
dest = os.path.join(dest_dir, "Wan2.2-Animate-14B-Q4_K_M.gguf")
os.makedirs(dest_dir, exist_ok=True)

proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

existing = os.path.getsize(dest) if os.path.exists(dest) else 0
mode = "ab" if existing > 0 else "wb"
headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
t0 = time.time()
try:
    with requests.get(url, stream=True, proxies=proxies, headers=headers, timeout=(15, 120)) as r:
        r.raise_for_status()
        total = existing
        with open(dest, mode) as f:
            for c in r.iter_content(1024 * 1024):
                f.write(c)
                total += len(c)
                if total % (1024 * 1024 * 1024) < 1024 * 1024:
                    el = time.time() - t0
                    print(f"  {total/1e9:.1f} GB ({total/1e9/el*60:.1f} min/GB)")
    print(f"WAN22 DONE {os.path.getsize(dest)/1e9:.2f}GB in {(time.time()-t0)/60:.0f}min")
except Exception as e:
    print(f"FAIL {type(e).__name__} {str(e)[:100]}")
