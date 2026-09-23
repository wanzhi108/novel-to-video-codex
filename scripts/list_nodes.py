"""查 WanVideoWrapper 的节点类清单。"""
import re
from pathlib import Path

p = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\nodes.py")
src = p.read_text(encoding="utf-8")
# 抓 class 定义 + NODE_CLASS_MAPPINGS
classes = re.findall(r"class (\w+)", src)
print("=== nodes.py 类数:", len(classes), "===")
for c in classes[:50]:
    print(" ", c)

# 抓 GGUF loader（可能在别的文件）
for f in Path(p.parent).rglob("*.py"):
    t = f.read_text(encoding="utf-8", errors="replace")
    for m in re.findall(r"class (\w*GGUF\w*|\w*Unet\w*)", t):
        print(f"[GGUF/Unet] {f.name}: {m}")
