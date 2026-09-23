"""从 Modelscope 下载 LTX-2 fp8 (27GB)，带 chunk 超时 + 断点续传。"""
import os
import time
import requests

url = "https://modelscope.cn/models/Lightricks/LTX-2/resolve/master/ltx-2-19b-distilled-fp8.safetensors"
dest = r"D:\novel-to-video-codex\LTX-2-OPTIMIZED\models\ltx-2-19b-distilled-fp8.safetensors"

# 断点续传：若已下载部分，用 Range 继续
mode = "ab" if os.path.exists(dest) and os.path.getsize(dest) > 0 else "wb"
existing = os.path.getsize(dest) if os.path.exists(dest) else 0
t0 = time.time()
try:
    headers = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    with requests.get(url, stream=True, headers=headers, timeout=(10, 60)) as r:
        if r.status_code not in (200, 206):
            print("FAIL HTTP", r.status_code, r.text[:100])
            raise SystemExit(1)
        total = existing
        with open(dest, mode) as f:
            for c in r.iter_content(1024 * 1024):
                f.write(c)
                total += len(c)
                if total % (1024 * 1024 * 1024) < 1024 * 1024:
                    el = time.time() - t0
                    print(f"  {total/1e9:.1f} GB ({total/1e9/el*60:.1f} min/GB)")
    print(f"FP8 DONE {os.path.getsize(dest)/1e9:.2f}GB in {(time.time()-t0)/60:.0f}min")
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:100])
