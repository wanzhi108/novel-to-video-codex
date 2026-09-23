"""查 WanVideoModelLoader 的模型列表 + GGUF 支持 + Animate 相关节点。"""
import re
from pathlib import Path

d = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper")
# 找 WanVideoModelLoader 定义
for f in d.rglob("*.py"):
    src = f.read_text(encoding="utf-8", errors="replace")
    if "class WanVideoModelLoader" in src:
        print(f"=== WanVideoModelLoader 在 {f.name} ===")
        m = re.search(r"class WanVideoModelLoader.*?INPUT_TYPES.*?\}(.*?)RETURN", src, re.DOTALL)
        if m:
            seg = m.group(1)
            print(seg[:600])
        break

# 查 GGUF 是否在支持的加载器/模型列表
print("\n=== GGUF / unet_name / get_filename_list ===")
for f in d.rglob("*.py"):
    src = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'get_filename_list\("(unet|diffusion_models|checkpoints)"\)', src):
        print(f"  {f.name}: {m.group(0)}")
    if "WanVideoModelLoader" in src:
        for m in re.finditer(r'get_filename_list\([^)]*\)', src):
            print(f"  {f.name} loader: {m.group(0)}")
