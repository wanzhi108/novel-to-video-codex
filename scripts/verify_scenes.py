"""验证场景6-11成片质量。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")
from quality.visual import assess_video  # noqa: E402

out = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
for i in [6, 7, 8, 9, 10, 11]:
    f = out / f"scene_00{i}" / f"scene_00{i}_final.mp4"
    if f.exists():
        v = assess_video(str(f))
        sharp = v["sharpness_min"]
        motion = v["motion"]
        passed = "PASS" if v["passed"] else "FAIL " + str(v["issues"])
        print(f"场景{i}: {f.stat().st_size//1024}KB sharp={sharp} motion={motion} {passed}")
    else:
        print(f"场景{i}: 无final")
