"""查 LTX-2 支持的更小文本编码器（issue #303）+ low-vram 方案。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = [
    ("issue303", "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/issues/303"),
    ("optimization_doc", "https://raw.githubusercontent.com/Lightricks/LTX-2/main/packages/ltx-pipelines/docs/optimization.md"),
]

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS:
        try:
            r = client.get(url)
            if name == "issue303":
                d = r.json()
                print(f"=== Issue #303 ===")
                print("title:", d.get("title"))
                print("body:", d.get("body", "")[:1500])
            else:
                print(f"\n=== optimization.md ({r.status_code}) ===")
                if r.status_code == 200:
                    t = r.text
                    for kw in ["offload", "quantization", "fp8", "fp4", "memory", "VRAM", "text encoder", "gemma", "small"]:
                        idx = t.find(kw)
                        if idx != -1:
                            print(f"  [{kw}] {t[max(0,idx-60):idx+140]}")
        except Exception as e:
            print(f"{name}: ERR {str(e)[:80]}")
