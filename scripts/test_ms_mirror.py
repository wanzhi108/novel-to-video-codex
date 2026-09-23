"""用 httpx stream 测 Modelscope 镜像速度。"""
import time
import httpx

tests = {
    "ms_lightricks_ltx2": "https://modelscope.cn/models/Lightricks/LTX-2/resolve/master/ltx-2-19b-distilled-fp8.safetensors",
    "ms_unsloth_gemma": "https://modelscope.cn/models/unsloth/gemma-3-12b-it/resolve/master/model-00001-of-00005.safetensors",
}

for name, url in tests.items():
    try:
        t0 = time.time()
        total = 0
        with httpx.Client(timeout=25, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                code = r.status_code
                if code == 200:
                    for chunk in r.iter_bytes(1024*256):
                        total += len(chunk)
                        if time.time() - t0 > 15:
                            break
                el = time.time() - t0
                if code == 200:
                    print(f"{name:24s} HTTP {code}  速度 {total/1e6/el:.1f} MB/s")
                else:
                    print(f"{name:24s} HTTP {code}")
    except Exception as e:
        print(f"{name:24s} FAIL {type(e).__name__} {str(e)[:70]}")
