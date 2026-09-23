"""创建 LTX 高质量工作流模板 img2vid_hq.json（12+6 步采样，替代默认 8+3 步）。"""
import json
from pathlib import Path

src = Path("comfyui/img2vid.json")
dst = Path("comfyui/img2vid_hq.json")

wf = json.loads(src.read_text(encoding="utf-8"))

# 阶段1（节点 4984）：8 步 → 12 步（13 个 sigma）
wf["4984"]["inputs"]["sigmas"] = (
    "1.0, 0.9960, 0.9920, 0.9880, 0.9840, 0.9800, 0.9750, "
    "0.9500, 0.9000, 0.7750, 0.5750, 0.3000, 0.0"
)
# 阶段2（节点 4985）：3 步 → 6 步（7 个 sigma）
wf["4985"]["inputs"]["sigmas"] = "0.85, 0.80, 0.70, 0.55, 0.35, 0.15, 0.0"

dst.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ 已创建 {dst}")
print("  阶段1 sigmas:", wf["4984"]["inputs"]["sigmas"])
print("  阶段2 sigmas:", wf["4985"]["inputs"]["sigmas"])
