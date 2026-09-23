"""查 WanVideoWrapper 的 unet_gguf 加载器节点类名。"""
import re
from pathlib import Path

d = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper")
for f in d.rglob("*.py"):
    src = f.read_text(encoding="utf-8", errors="replace")
    if "unet_gguf" in src:
        # 找类定义（含 GGUF 或 UnetLoader）
        for m in re.finditer(r"class (\w*GGUF\w*|\w*Unet\w*)", src):
            print(f"{f.name}: class {m.group(1)}")
        # 找对应 NODE_CLASS_MAPPINGS 注册名
        for m in re.finditer(r'"(\w*)":\s*(\w*GGUF\w*|\w*Unet\w*)', src):
            print(f"{f.name}: mapping {m.group(1)} -> {m.group(2)}")
