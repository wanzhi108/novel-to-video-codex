"""从 Modelscope 下载 Gemma 3 12B 全部分片（requests 流式 + 断点元）。"""
import os
import time
import requests

BASE = "https://modelscope.cn/models/unsloth/gemma-3-12b-it/resolve/master/"
FILES = [
    "model-00001-of-00005.safetensors",
    "model-00002-of-00005.safetensors",
    "model-00003-of-00005.safetensors",
    "model-00004-of-00005.safetensors",
    "model-00005-of-00005.safetensors",
    "model.safetensors.index.json",
]
DEST = r"D:\novel-to-video-codex\LTX-2-OPTIMIZED\models\gemma3"
os.makedirs(DEST, exist_ok=True)

# 小文件先补（config/tokenizer/preprocessor 已在）
for f in ["config.json", "tokenizer.model", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json"]:
    dest = os.path.join(DEST, f)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        try:
            r = requests.get(BASE + f, timeout=60)
            if r.status_code == 200:
                with open(dest, "wb") as fh:
                    fh.write(r.content)
                print("OK small", f)
        except Exception as e:
            print("FAIL small", f, str(e)[:60])

for f in FILES:
    dest = os.path.join(DEST, f)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000000:
        print("skip", f, f"{os.path.getsize(dest)/1e9:.2f}GB")
        continue
    t0 = time.time()
    total = 0
    try:
        with requests.get(BASE + f, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for c in r.iter_content(1024 * 1024):
                    fh.write(c)
                    total += len(c)
        print(f"OK {f} {total/1e9:.2f}GB in {time.time()-t0:.0f}s")
    except Exception as e:
        print(f"FAIL {f} {type(e).__name__} {str(e)[:60]}")
print("GEMMA ALL DONE")
