"""确认场景1-5的字幕成片。"""
import os
from pathlib import Path

out = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
for i in range(1, 6):
    f = out / f"scene_00{i}" / f"scene_00{i}_subbed.mp4"
    if f.exists():
        print(f"场景{i}: 有 {round(f.stat().st_size/1024)}KB")
    else:
        print(f"场景{i}: 无")
