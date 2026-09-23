"""诊断人物/场景一致性：检查角色定妆照、IPAdapter 配置、各场景关键帧。"""
import json
import urllib.request
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))

# 1. job 配置：IPAdapter / PuLID / 角色映射
s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
print("=== 角色定妆照 (IP-Adapter 参考图) ===")
cast_dir = OUT / "cast"
if cast_dir.exists():
    for f in sorted(cast_dir.glob("*")):
        print(f"  {f.name} ({f.stat().st_size//1024}KB)")
else:
    print("  cast 目录不存在")

# 2. 各场景关键帧 + IPAdapter 锚定情况
print("\n=== 各场景关键帧与 IPAdapter 定妆照 ===")
for sid in range(1, 6):
    d = OUT / f"scene_{sid:03d}"
    if not d.exists():
        continue
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    # 找该场景场景1-2张关键帧
    kfs = [p for p in pngs if "ipadapter" in p.name or "scene_" in p.name or "shot" in p.name][:2]
    print(f"  场景{sid}: {len(pngs)}张png")
    for p in kfs:
        print(f"    {p.name} ({p.stat().st_size//1024}KB)")

# 3. 是否每个场景都用了同一角色定妆照（检查 IPAdapter 映射是否跨场景复用）
print("\n=== 角色定妆照文件（全 project）===")
for f in sorted(OUT.rglob("*.png")):
    if "portrait" in f.name.lower() or "cast" in str(f).lower():
        print(f"  {f.name} ({f.stat().st_size//1024}KB)")

# 4. 配置文件里 IPAdapter 设置
print("\n=== 角色一致性配置（从 job 检查）===")
# 从 launcher_config 或 settings 检查
import os
cfg = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\launcher_config.json"))
if cfg.exists():
    d = json.loads(cfg.read_text(encoding="utf-8"))
    print("  launcher_config:", {k: d[k] for k in d})
