"""收集当前作品总体指标：分辨率/时长/音轨/字幕，用于对比红果漫剧标准。"""
import os
import json
import subprocess
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                       "-show_format", "-show_streams", str(p)],
                      capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    vs = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
    fmt = d.get("format", {})
    return {"w": vs.get("width"), "h": vs.get("height"),
            "dur": float(fmt.get("duration", 0) or 0),
            "size": int(fmt.get("size", 0) or 0), "has_audio": has_audio}


# 1. 各场景成片
print("=== 各场景成片指标 ===")
total_dur = 0
for sid in range(1, 6):
    d = OUT / f"scene_{sid:03d}"
    cand = None
    for name in [f"scene_{sid:03d}_final.mp4", f"scene_{sid:03d}_with_bgm.mp4"]:
        if (d / name).exists():
            cand = d / name
            break
    if not cand:
        continue
    t = probe(cand)
    if t:
        total_dur += t["dur"]
        print(f"  {cand.name}: {t['w']}x{t['h']} {t['dur']:.1f}s {t['size']//1024}KB audio={'是' if t['has_audio'] else 'NO'}")

print(f"\n  场景1-5总时长: {total_dur:.1f}s")

# 2. 是否有整体成片 / 字幕 / BGM
print("\n=== 项目级成片/字幕/BGM ===")
for f in OUT.glob("*.mp4"):
    print(f"  {f.name} ({f.stat().st_size//1024}KB)")
print("  字幕文件(.srt/.ass):", [f.name for f in OUT.rglob("*.srt")] + [f.name for f in OUT.rglob("*.ass")])
print("  BGM:", [f.name for f in (r"D:\novel-to-video-codex\bgm").glob("*.mp3")] if (r"D:\novel-to-video-codex\bgm").exists() else "bgm目录不存在")

# 3. 角色一致性（关键帧数量）
print("\n=== 角色定妆照 / 关键帧 ===")
for sid in range(1, 6):
    d = OUT / f"scene_{sid:03d}"
    pngs = sorted(d.glob("*.png"))
    print(f"  场景{sid}: {len(pngs)} 张关键帧")
