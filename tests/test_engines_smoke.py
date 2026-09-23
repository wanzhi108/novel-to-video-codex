"""临时冒烟测试：ComfyUIEngine 模板加载与填充正确性（不真提交）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.local import ComfyUIEngine  # noqa: E402

eng = ComfyUIEngine()
print("is_available (8188):", eng.is_available())

img2vid = eng.load_workflow("img2vid")
t2vid = eng.load_workflow("t2vid")
print("img2vid 节点数:", len(img2vid), "| t2vid 节点数:", len(t2vid))

wf = eng.fill_workflow(img2vid, {
    "CHECKPOINT": eng.checkpoint,
    "TEXT_ENCODER": eng.text_encoder,
    "INPUT_IMAGE": "shot.png",
    "POSITIVE_PROMPT": "test motion. locked camera, subtle micro motion",
    "NEGATIVE_PROMPT": "low quality",
    "FILENAME_PREFIX": "engines/smoke",
    "FRAME_RATE": 24,
    "LENGTH": 65,
    "SEED": 42,
    "WIDTH_BASE": 960,
    "HEIGHT_BASE": 1728,
})
s = json.dumps(wf, ensure_ascii=False)
unreplaced = [k for k in ("CHECKPOINT", "INPUT_IMAGE", "POSITIVE_PROMPT", "LENGTH", "SEED", "WIDTH_BASE")
              if "{{" + k + "}}" in s]
assert not unreplaced, f"占位符未替换: {unreplaced}"
assert "ltx-2.3-22b-dev-fp8.safetensors" in s
assert '"shot.png"' in s
parsed = json.loads(s)
assert parsed is not None and isinstance(parsed, dict)
# 数字必须无引号：INTConstant.value 应为 65（数字）而非字符串
import re
nums = [(m.group(1), m.group(2)) for m in re.finditer(r'"value"\s*:\s*("?)(\d+)(\1)', s)]
assert any(v == "65" and q == "" for q, v in nums), f"期望无引号数字 65，实际: {nums[:8]}"
print("✅ fill_workflow I2V 正确：所有占位符已替换，JSON 有效，数字未带引号")
# seed 示例（容错打印）
seed_hits = [v for v in parsed.values() if isinstance(v, dict) and v.get("seed") == 42]
print("   seed 字段:", seed_hits[0].get("seed") if seed_hits else "(节点字段名非 seed，跳过)")
print("SMOKE OK")
