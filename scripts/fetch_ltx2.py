"""用 httpx 走代理抓 LTX-2 官方 README + awesome-ltx2。"""
import httpx

PROXY = "http://127.0.0.1:7897"
URLS = {
    "ltx2_readme": "https://raw.githubusercontent.com/Lightricks/LTX-2/main/README.md",
    "awesome_ltx2": "https://raw.githubusercontent.com/suryatmodulus/awesome-ltx2/main/README.md",
}


def grab(client, name, url):
    try:
        r = client.get(url)
        if r.status_code != 200:
            print(f"\n{name}: HTTP {r.status_code}")
            return
        t = r.text
        print(f"\n{'='*20} {name} ({len(t)} chars) {'='*20}")
        # 找关键信息
        for kw in ["Checkpoint", "checkpoint", "fp8", "VRAM", "vram", "ComfyUI", "LTXVideo", "text encoder",
                   "Download", "huggingface", "22B", "GGUF", "gguf", "Day-0", "day-0"]:
            start = 0
            shown = 0
            while shown < 2:
                i = t.find(kw, start)
                if i == -1:
                    break
                seg = t[max(0, i - 70):i + 110].replace("\n", " ")
                print(f"  [{kw}] ...{seg}...")
                start = i + len(kw)
                shown += 1
    except Exception as e:
        print(f"\n{name}: ERR {type(e).__name__} {str(e)[:120]}")


with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS.items():
        grab(client, name, url)
