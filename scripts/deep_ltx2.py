"""深挖 LTX-2-OPTIMIZED (8GB优化) 和 Gemma 4B 替代方案的可行性。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = [
    ("ltx2_optimized", "https://raw.githubusercontent.com/nalexand/LTX-2-OPTIMIZED/main/README.md"),
    ("issue303_full", "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/issues/303/comments"),
]

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    # 1. LTX-2-OPTIMIZED README
    try:
        r = client.get(URLS[0][1])
        print(f"=== LTX-2-OPTIMIZED ({r.status_code}) ===")
        if r.status_code == 200:
            t = r.text
            print(t[:2500])
    except Exception as e:
        print("OPTIMIZED ERR:", str(e)[:80])

    # 2. issue #303 评论（看有没有人成功 8GB/16GB）
    try:
        r = client.get(URLS[1][1])
        print(f"\n=== Issue #303 评论 ({r.status_code}) ===")
        if r.status_code == 200:
            for c in r.json()[:5]:
                body = c.get("body", "")
                print("  -", body[:500].replace("\n", " "))
    except Exception as e:
        print("comments ERR:", str(e)[:80])
