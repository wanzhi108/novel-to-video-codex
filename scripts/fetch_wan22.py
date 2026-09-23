"""抓 ComfyUI-Wan2.2-workflow (low VRAM) 和 8GB 教程的部署细节。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = {
    "wan22_lowvram_workflow": "https://raw.githubusercontent.com/Cordux/ComfyUI-Wan2.2-workflow/main/README.md",
    "runflow_8gb": "https://www.runflow.io/blog/comfyui-wan-2-2-image-to-video",
}

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS.items():
        try:
            r = client.get(url)
            print(f"\n{'='*15} {name} ({r.status_code}) {'='*15}")
            if r.status_code == 200:
                t = r.text
                print(t[:2500])
            else:
                print("HTTP", r.status_code, r.text[:100])
        except Exception as e:
            print(f"\n{name}: ERR {str(e)[:80]}")
