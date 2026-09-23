"""抓 ComfyUI-LTXVideo 官方 README + LTX-2 model list，确定确切模型文件。"""
import httpx
import re

PROXY = "http://127.0.0.1:7897"
URLS = [
    ("comfyui_ltxvideo_readme", "https://raw.githubusercontent.com/Lightricks/ComfyUI-LTXVideo/master/README.md"),
    ("ltx2_hf", "https://huggingface.co/Lightricks/LTX-2/raw/main/README.md"),
]

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS:
        try:
            r = client.get(url)
            print(f"\n{'='*20} {name} ({r.status_code}) {'='*20}")
            if r.status_code == 200:
                t = r.text
                # 抓模型相关行
                for kw in ["text_encoder", "VAE", "transformer", "checkpoint", "GGUF", "gemma", "fp8",
                           "Download", "CivitAI", "models/", "Installation", "Install", "vae", "fp4"]:
                    start = 0; shown = 0
                    while shown < 2:
                        i = t.find(kw, start)
                        if i == -1: break
                        seg = t[max(0, i - 60):i + 130].replace("\n", " ")
                        print(f"  [{kw}] ...{seg}...")
                        start = i + len(kw); shown += 1
            else:
                print("  body:", r.text[:200])
        except Exception as e:
            print(f"\n{name}: ERR {type(e).__name__} {str(e)[:100]}")
