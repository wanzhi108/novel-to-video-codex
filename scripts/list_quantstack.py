"""列 QuantStack Wan 2.2 GGUF 仓库文件。"""
import httpx

proxy = "http://127.0.0.1:7897"
for repo in ["QuantStack/Wan2.2-Animate-14B-GGUF", "QuantStack/Wan2.2-14B-GGUF"]:
    try:
        r = httpx.get(f"https://huggingface.co/api/models/{repo}", proxy=proxy, timeout=25)
        if r.status_code == 200:
            d = r.json()
            gated = d.get("gated")
            print(f"=== {repo} (gated={gated}) ===")
            for f in d.get("siblings", []):
                name = f["rfilename"]
                if name.endswith((".gguf", ".safetensors")) and "14B" in name:
                    print("  ", name)
        else:
            print(f"{repo}: HTTP {r.status_code}")
    except Exception as e:
        print(f"{repo}: ERR {type(e).__name__} {str(e)[:60]}")
