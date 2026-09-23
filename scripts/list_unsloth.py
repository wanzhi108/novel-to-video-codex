"""列出 unsloth/gemma-3-12b-it 仓库实际文件（HF API）。"""
import httpx

PROXY = "http://127.0.0.1:7897"
url = "https://huggingface.co/api/models/unsloth/gemma-3-12b-it"

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    r = client.get(url)
    if r.status_code == 200:
        d = r.json()
        files = d.get("siblings", [])
        print(f"文件数: {len(files)}")
        for f in files:
            name = f.get("rfilename", "")
            print(f"  {name}")
    else:
        print("HTTP", r.status_code, r.text[:200])
