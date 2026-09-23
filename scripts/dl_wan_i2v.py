"""稳健并行下载：raw requests + Range 断点 + 最终大小校验 + 失败重试。"""
import os, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

PROX = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
FILES = [
    ("https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf",
     r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\diffusion_models\Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf"),
    ("https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf",
     r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\diffusion_models\Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf"),
    ("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
     r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
]

def head_size(url):
    r = requests.head(url, proxies=PROX, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return int(r.headers["Content-Length"])

def dl(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    expected = head_size(url)
    t0 = time.time()
    attempts = 0
    while True:
        try:
            existing = os.path.getsize(dest) if os.path.exists(dest) else 0
            if existing >= expected:
                print(f"OK {os.path.basename(dest)} {existing/1e9:.2f}GB (resume complete)", flush=True)
                return True
            headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
            r = requests.get(url, stream=True, proxies=PROX, headers=headers, timeout=(20, 300))
            r.raise_for_status()
            with open(dest, "ab" if existing > 0 else "wb") as f:
                for c in r.iter_content(1024 * 1024):
                    if c:
                        f.write(c)
            cur = os.path.getsize(dest)
            if cur >= expected:
                print(f"OK {os.path.basename(dest)} {cur/1e9:.2f}GB in {(time.time()-t0)/60:.0f}min", flush=True)
                return True
            print(f"  {os.path.basename(dest)} size {cur/1e9:.2f}GB < {expected/1e9:.2f}GB, retrying", flush=True)
            attempts += 1
            time.sleep(3)
        except Exception as e:
            attempts += 1
            print(f"  {os.path.basename(dest)} {type(e).__name__}: {str(e)[:80]}", flush=True)
            time.sleep(5)

def main():
    print("ROBUST PARALLEL start", flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(dl, u, d) for u, d in FILES]
        for fu in as_completed(futs):
            fu.result()
    print("ALL DONE", flush=True)

if __name__ == "__main__":
    main()
