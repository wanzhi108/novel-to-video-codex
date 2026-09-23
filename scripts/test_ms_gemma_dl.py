"""测 modelscope gemma 分片能否流式下载（20s 采样）。"""
import time
import requests

url = "https://modelscope.cn/models/unsloth/gemma-3-12b-it/resolve/master/model-00001-of-00005.safetensors"
t0 = time.time()
try:
    with requests.get(url, stream=True, timeout=30) as r:
        print("HTTP", r.status_code)
        total = 0
        if r.status_code == 200:
            for c in r.iter_content(1024*256):
                total += len(c)
                if time.time() - t0 > 20:
                    break
            el = time.time() - t0
            print(f"20s下载 {total/1e6:.0f} MB, 速度 {total/1e6/el:.1f} MB/s")
        else:
            print("非200", r.text[:100])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:100])
