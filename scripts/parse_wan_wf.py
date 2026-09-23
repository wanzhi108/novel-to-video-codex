"""解析 Wan 2.2 I2V 官方模板：提取节点类型 + 关键模型参数。"""
import json
from pathlib import Path

p = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json")
w = json.loads(p.read_text(encoding="utf-8"))

# 节点类型统计
from collections import Counter
types = Counter(n["type"] for n in w["nodes"])
print("=== 节点类型 ===")
for t, c in types.most_common():
    print(f"  {t}: {c}")

# 找模型名相关的节点（UnetLoader/VAELoader/CLIPLoader/CheckpointLoader）
print("\n=== 模型加载节点及其参数 ===")
for n in w["nodes"]:
    if "Loader" in n["type"] or "Unet" in n["type"] or "VAE" in n["type"]:
        wv = n.get("widgets_values")
        print(f"  {n['type']}: widgets={wv}")
