"""确认 LTX-2 关键模型下载 URL 可用性 + 大小（head 请求）。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = {
    "gemma3_12b_qat": "https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized/resolve/main/model.safetensors",
    "ltx2_gguf_q4km": "https://huggingface.co/unsloth/LTX-2-GGUF/resolve/main/ltx-2-19b-dev-Q4_K_M.gguf",
    "ltx2_gguf_q4km2": "https://huggingface.co/QuantStack/LTX-2-GGUF/resolve/main/LTX-2-dev/LTX-2-dev-Q4_K_M.gguf",
}

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS.items():
        try:
            r = client.head(url, headers={"Accept-Encoding": "identity"})
            size = r.headers.get("content-length", "?")
            print(f"{name:22s} HTTP {r.status_code}  size={size}  ({int(size)/1e9:.2f} GB)" if size.isdigit() else f"{name:22s} HTTP {r.status_code}  size={size}")
        except Exception as e:
            print(f"{name:22s} ERR {type(e).__name__} {str(e)[:80]}")
