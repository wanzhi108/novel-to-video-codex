"""稳健下载 umt5-xxl-enc-fp8_e4m3fn.safetensors（raw requests + Range 断点 + 大小校验 + 重试）。"""
import os, time, requests

URL = "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/umt5-xxl-enc-fp8_e4m3fn.safetensors"
DEST = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\text_encoders\umt5-xxl-enc-fp8_e4m3fn.safetensors"
PROX = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

def head_size(url):
    for _ in range(5):
        try:
            r = requests.head(url, proxies=PROX, timeout=30, allow_redirects=True)
            r.raise_for_status()
            return int(r.headers["Content-Length"])
        except Exception:
            time.sleep(3)
    raise RuntimeError("head_size failed after 5 retries")

expected = head_size(URL)
print("expected", round(expected/1e9, 2), "GB", flush=True)
os.makedirs(os.path.dirname(DEST), exist_ok=True)
t0 = time.time()
while True:
    try:
        existing = os.path.getsize(DEST) if os.path.exists(DEST) else 0
        if existing >= expected:
            print("OK", os.path.basename(DEST), round(existing/1e9,2), "GB", flush=True)
            break
        headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
        r = requests.get(URL, stream=True, proxies=PROX, headers=headers, timeout=(20, 300))
        r.raise_for_status()
        with open(DEST, "ab" if existing > 0 else "wb") as f:
            for c in r.iter_content(1024 * 1024):
                if c:
                    f.write(c)
        cur = os.path.getsize(DEST)
        if cur >= expected:
            print("OK", os.path.basename(DEST), round(cur/1e9,2), "GB in", round((time.time()-t0)/60,1), "min", flush=True)
            break
        print("  size", round(cur/1e9,2), "<", round(expected/1e9,2), "retrying", flush=True)
        time.sleep(3)
    except Exception as e:
        print("  ", type(e).__name__, str(e)[:80], flush=True)
        time.sleep(5)
