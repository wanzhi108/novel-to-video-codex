"""确认15个场景final（修正路径：scene_001..scene_015）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

out = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
missing = []
clips = []
for i in range(1, 16):
    f = out / f"scene_{i:03d}" / f"scene_{i:03d}_final.mp4"
    if not f.exists():
        missing.append(i)
    else:
        clips.append(f)
        print(f"场景{i}: {f.stat().st_size//1024}KB ✓")

print(f"\n缺失: {missing if missing else '无（15个全齐）'}")
print(f"可用成片: {len(clips)}")
