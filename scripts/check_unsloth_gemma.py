"""确认 unsloth/gemma-3-12b-it 是否含 LTX-2 所需文件（model*.safetensors, tokenizer.model, preprocessor_config.json）。"""
import httpx

PROXY = "http://127.0.0.1:7897"
BASE = "https://huggingface.co/unsloth/gemma-3-12b-it/resolve/main"

FILES = [
    "model-00001-of-00003.safetensors",
    "model-00002-of-00003.safetensors",
    "model-00003-of-00003.safetensors",
    "tokenizer.model",
    "preprocessor_config.json",
    "config.json",
]

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for f in FILES:
        try:
            r = client.head(BASE + "/" + f, headers={"Accept-Encoding": "identity"})
            size = r.headers.get("content-length", "?")
            ok = r.status_code == 200
            print(f"{'✅' if ok else '❌'} {f:36s} HTTP {r.status_code}  size={size}" + (f"  ({int(size)/1e9:.2f} GB)" if size.isdigit() else ""))
        except Exception as e:
            print(f"❌ {f:36s} ERR {str(e)[:60]}")
