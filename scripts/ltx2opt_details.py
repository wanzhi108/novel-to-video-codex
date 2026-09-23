"""看 LTX-2-OPTIMIZED 用的文本编码器 + 具体模型/配置。"""
import httpx

PROXY = "http://127.0.0.1:7897"
url = "https://raw.githubusercontent.com/nalexand/LTX-2-OPTIMIZED/main/README.md"

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    r = client.get(url)
    t = r.text
    # 找模型/编码器/checkpoint/显存/内存相关
    for kw in ["Text Encoder", "text encoder", "gemma", "Gemma", "checkpoint", "checkpoints",
               "fp8", "offload", "memory", "VRAM", "distilled", "safetensors", "12B", "4B",
               "RAM", "requirements", "--quantization"]:
        start = 0
        shown = 0
        while shown < 3 and start < len(t):
            i = t.find(kw, start)
            if i == -1:
                break
            seg = t[max(0, i - 60):i + 130].replace("\n", " ")
            print(f"[{kw}] ...{seg}...")
            start = i + len(kw)
            shown += 1
