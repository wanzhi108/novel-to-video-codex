"""从 Modelscope 下载 LTX-2 spatial upscaler (1GB)。"""
import os
import time
import requests

url = "https://modelscope.cn/models/Lightricks/LTX-2/resolve/master/ltx-2-spatial-upscaler-x2-1.0.safetensors"
dest = r"D:\novel-to-video-codex\LTX-2-OPTIMIZED\models\ltx-2-spatial-upscaler-x2-1.0.safetensors"
if os.path.exists(dest) and os.path.getsize(dest) > 1e8:
    print("已存在", os.path.getsize(dest)/1e9, "GB")
else:
    t0 = time.time()
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for c in r.iter_content(1024*1024):
                f.write(c)
    print(f"UPSCALER DONE {os.path.getsize(dest)/1e9:.2f}GB in {time.time()-t0:.0f}s")
