"""确认 LTX-2 模型下载源可匿名性。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = {
    "ltx2_fp8_distilled": "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-distilled-fp8.safetensors",
    "ltx2_spatial_upscaler": "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-spatial-upscaler-x2-1.0.safetensors",
    "gemma_qat": "https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized/resolve/main/model.safetensors",
    "gemma_unsloth_shard1": "https://huggingface.co/unsloth/gemma-3-12b-it/resolve/main/model-00001-of-00005.safetensors",
}

with httpx.Client(proxy=PROXY, timeout=25, follow_redirects=True) as client:
    for name, url in URLS.items():
        try:
            r = client.head(url, headers={"Accept-Encoding": "identity"})
            sz = r.headers.get("content-length", "?")
            gb = int(sz) / 1e9 if sz.isdigit() else 0
            print(f"{name:24s} HTTP {r.status_code}  size={sz}  ({gb:.2f} GB)" if sz.isdigit() else f"{name:24s} HTTP {r.status_code}  size={sz}")
        except Exception as e:
            print(f"{name:24s} ERR {str(e)[:60]}")
