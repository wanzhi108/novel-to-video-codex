"""确认 unsloth gemma-3-12b-it 5 分片的实际下载总量。"""
import httpx

PROXY = "http://127.0.0.1:7897"
BASE = "https://huggingface.co/unsloth/gemma-3-12b-it/resolve/main"
SHARDS = [
    "model-00001-of-00005.safetensors",
    "model-00002-of-00005.safetensors",
    "model-00003-of-00005.safetensors",
    "model-00004-of-00005.safetensors",
    "model-00005-of-00005.safetensors",
]

total = 0
with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for s in SHARDS:
        try:
            r = client.head(BASE + "/" + s, headers={"Accept-Encoding": "identity"})
            sz = r.headers.get("content-length", "0")
            gb = int(sz) / 1e9 if sz.isdigit() else 0
            total += gb
            print(f"{s}  HTTP {r.status_code}  {gb:.2f} GB")
        except Exception as e:
            print(f"{s}  ERR {str(e)[:50]}")
print(f"\nGemma 3 12B 总计: {total:.2f} GB")
