"""收集前 6 个场景的关键帧图 + 视频，准备展示。"""
import os
import json
import urllib.request
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
scenes = s["scenes"]

for x in scenes[:6]:
    sid = x["id"]
    d = OUT / f"scene_{sid:03d}"
    print(f"=== 场景 {sid} ===")
    if not d.exists():
        print("  目录不存在")
        continue
    # 关键帧：优先 ipadapter 最新 png / novel2vid 关键帧
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    mp4s = sorted(d.glob("*.mp4"))
    # 展示关键帧（取最新的 1-2 张）
    shown = 0
    for p in pngs:
        if "shot" in p.name or "kf" in p.name or "ipadapter" in p.name or "scene_" in p.name:
            print(f"  关键帧: {p.name} ({p.stat().st_size//1024}KB)")
            shown += 1
            if shown >= 2:
                break
    # 视频
    for p in mp4s:
        if "final" in p.name or "industrial" in p.name:
            print(f"  视频: {p.name} ({p.stat().st_size//1024}KB)")
