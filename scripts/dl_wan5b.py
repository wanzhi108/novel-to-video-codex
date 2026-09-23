"""下载 Wan2.2 TI2V-5B Q5_K_M GGUF + Wan2.2 VAE（稳健 raw requests + 断点续传）。"""
import os, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

PROX = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
FILES = [
    ("https://huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/Wan2.2-TI2V-5B-Q5_K_M.gguf",
     r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\diffusion_models\Wan2.2-TI2V-5B-Q5_K_M.gguf"),
    ("https://huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/VAE/Wan2.2_VAE.safetensors",
     r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\vae\Wan2.2_VAE.safetensors"),
]

def head_size(url):
    for _ in range(5):
        try:
            r = requests.head(url, proxies=PROX, timeout=30, allow_redirects=True)
            r.raise_for_status()
            return int(r.headers["Content-Length"])
        except Exception:
            time.sleep(3)
    raise RuntimeError("head_size failed")

def dl(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    expected = head_size(url)
    t0 = time.time()
    while True:
        try:
            existing = os.path.getsize(dest) if os.path.exists(dest) else 0
            if existing >= expected:
                print(f"OK {os.path.basename(dest)} {existing/1e9:.2f}GB (resume)", flush=True); return
            headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
            r = requests.get(url, stream=True, proxies=PROX, headers=headers, timeout=(20, 300))
            r.raise_for_status()
            with open(dest, "ab" if existing > 0 else "wb") as f:
                for c in r.iter_content(1024*1024):
                    if c:
                        f.write(c)
            cur = os.path.getsize(dest)
            if cur >= expected:
                print(f"OK {os.path.basename(dest)} {cur/1e9:.2f}GB in {(time.time()-t0)/60:.0f}min", flush=True); return
            print(f"  {os.path.basename(dest)} {cur/1e9:.2f}GB < {expected/1e9:.2f}GB retry", flush=True); time.sleep(3)
        except Exception as e:
            print(f"  {os.path.basename(dest)} {type(e).__name__} {str(e)[:80]}", flush=True); time.sleep(5)

if __name__ == "__main__":
    print("PARALLEL 5B download start", flush=True)
    with ThreadPoolExecutor(max_workers=2) as ex:
        for fu in as_completed([ex.submit(dl, u, d) for u, d in FILES]):
            fu.result()
    print("ALL DONE", flush=True)
