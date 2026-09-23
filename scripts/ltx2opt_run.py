"""确认 LTX-2-OPTIMIZED 是否兼容 ComfyUI + Gemma 替代。"""
import httpx

PROXY = "http://127.0.0.1:7897"

# optimized README 里的 requirements/运行方式
url = "https://raw.githubusercontent.com/nalexand/LTX-2-OPTIMIZED/main/README.md"
with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    r = client.get(url)
    t = r.text
    print("=== 运行/安装方式 ===")
    for kw in ["python ", "pip install", "gradio", "ui.py", "comfyui", "ComfyUI", "--help", "requirements"]:
        start = 0
        shown = 0
        while shown < 2 and start < len(t):
            i = t.find(kw, start)
            if i == -1:
                break
            seg = t[max(0, i - 40):i + 120].replace("\n", " ")
            print(f"[{kw}] ...{seg}...")
            start = i + len(kw)
            shown += 1

# 检查 Gemma qat 是否可匿名（用 huggingface api 看 gated）
print("\n=== Gemma QAT gated 状态 ===")
try:
    u = "https://huggingface.co/api/models/google/gemma-3-12b-it-qat-q4_0-unquantized"
    r = client.get(u, timeout=15)
    d = r.json()
    print("gated:", d.get("gated"), "| id:", d.get("id"), "| downloads:", d.get("downloads"))
except Exception as e:
    print("ERR", str(e)[:80])
