"""查 IPAdapter 定妆照保存位置 + 生成关键帧是否接入 IPAdapter。"""
import os
import json
import subprocess
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))

# 1. 找所有定妆照（portrait 相关）：全盘搜 output
print("=== 全 output 下的定妆照/角色图 ===")
for f in sorted(OUT.rglob("*.png")):
    name = f.name
    if "0071" in name or "portrait" in name.lower() or "700" in name or "王砚" in str(f):
        print(f"  {f.name} ({f.stat().st_size//1024}KB) mtime={f.stat().st_mtime}")

# 2. 看场景关键帧是否用 IPAdapter：检查关键帧命名规律 + 是否有角色定妆照被引用
print("\n=== 场景关键帧里哪些可能带角色（ipadapter 命名）===")
for sid in range(1, 6):
    d = OUT / f"scene_{sid:03d}"
    if d.exists():
        ipads = [p.name for p in d.glob("*ipadapter*")]
        print(f"  场景{sid}: ipadapter关键帧 {len(ipads)} 张")

# 3. 查 main.py IPAdapter 定妆照保存逻辑
print("\n=== main.py IPAdapter 定妆照相关代码 ===")
import sys
sys.path.insert(0, r"D:\novel-to-video-codex")
sys.path.insert(0, r"D:\novel-to-video-codex\scripts")
try:
    import main as m
    src = open(r"D:\novel-to-video-codex\scripts\main.py", encoding="utf-8").read()
    for kw in ["portrait", "定妆照", "cast_", "character_material", "_build_character_material"]:
        idxs = [i for i in range(len(src)) if src.startswith(kw, i)][:3]
        for i in idxs:
            print(f"  [{kw}] ...{src[max(0,i-40):i+80]}...")
except Exception as e:
    print("err:", str(e)[:100])
