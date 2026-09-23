"""对比新引擎(industrial_1.mp4)与旧引擎(scene_001_concat.mp4)的视觉质量。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

from quality.visual import assess_video, sharpness  # noqa: E402

base = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\c0e98869"))
new = base / "industrial_1.mp4"
old = base / "scene_001" / "scene_001_concat.mp4"

for label, p in [("NEW 工业引擎", new), ("OLD 旧引擎", old)]:
    if not p.exists():
        print(f"{label}: 文件不存在 {p}")
        continue
    vq = assess_video(str(p))
    print(f"\n{label} ({p.name}):")
    print(f"  passed={vq['passed']} sharp_min={vq['sharpness_min']} "
          f"sharp_mean={vq['sharpness_mean']} motion={vq['motion']} "
          f"black={vq['black_frames']} issues={vq['issues']}")
