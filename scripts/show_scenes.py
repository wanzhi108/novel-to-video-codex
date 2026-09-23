"""列出 cfb52fe4 前 6 个场景的分镜内容与产物文件。"""
import os
import json
import urllib.request
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
scenes = s["scenes"]

for x in scenes[:6]:
    sid = x["id"]
    print("=" * 70)
    print(f"【场景 {sid}】{x.get('title')}  |  状态: {x.get('status')}")
    print(f"  台词/旁白: {x.get('subtitle_text')}")
    print(f"  角色: {x.get('characters')} | 情绪: {x.get('mood')} | 时长: {x.get('duration')}s")
    print(f"  镜头: {x.get('camera')}")
    print(f"  画面描述: {(x.get('description') or '')[:220]}")
    # 产物文件
    d = OUT / f"scene_{sid:03d}"
    if d.exists():
        files = sorted(d.glob("*.mp4")) + sorted(d.glob("*.png"))
        if files:
            print(f"  产物文件 ({len(files)}):")
            for f in files[:8]:
                kb = f.stat().st_size // 1024
                print(f"    {f.name}  ({kb}KB)")
        else:
            print("  产物文件: (无)")
    else:
        print(f"  产物目录: {d} 不存在")
