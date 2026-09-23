"""搜可匿名下载的 Gemma 3 12B 编码器替代（LTX-2 兼容）。"""
import httpx

PROXY = "http://127.0.0.1:7897"
# 社区/GGUF 的 Gemma 3 12B，通常非 gated
CANDS = [
    ("bartowski_gemma3_12b_gguf", "https://huggingface.co/bartowski/gemma-3-12b-it-GGUF"),
    ("unsloth_gemma3_12b", "https://huggingface.co/unsloth/gemma-3-12b-it"),
    ("lmgemma_12b", "https://huggingface.co/lmstudio-community/gemma-3-12b-it-GGUF"),
    ("Qwen_gemma3_mirror", "https://huggingface.co/Qwen/gemma-3-12b-it"),
]

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in CANDS:
        try:
            r = client.get(url + "/resolve/main/config.json")
            print(f"{name:24s} HTTP {r.status_code}  {r.text[:60] if r.status_code==200 else r.text[:100]}")
        except Exception as e:
            print(f"{name:24s} ERR {str(e)[:60]}")
