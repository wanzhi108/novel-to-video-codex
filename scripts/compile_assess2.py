"""修正：查项目级字幕/BGM/整体成片。"""
import os
import json
import subprocess
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
BGM = Path(r"D:\novel-to-video-codex\bgm")

print("=== 项目级成片 ===")
for f in OUT.glob("*.mp4"):
    print(f"  {f.name} ({f.stat().st_size//1024}KB)")

print("\n=== 字幕文件 ===")
srt = list(OUT.rglob("*.srt")) + list(OUT.rglob("*.ass"))
print("  .srt/.ass:", [f.name for f in srt] if srt else "(无字幕文件)")

# 各场景是否有 audio 轨的配音内容（抽查场景1音频时长）
print("\n=== 场景1 音频轨时长（判断配音是否接入）===")
sc1 = OUT / "scene_001"
for name in ["scene_001_final.mp4", "scene_001_extracted.wav"]:
    p = sc1 / name
    if p.exists():
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                           "-show_format", "-show_streams", str(p)],
                          capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout)
        af = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
        dur = float(d.get("format", {}).get("duration", 0) or 0)
        print(f"  {name}: audio_dur={af.get('duration','?')}s format_dur={dur:.2f}s")

print("\n=== BGM ===")
print("  bgm 目录存在:", BGM.exists(), BGM)
if BGM.exists():
    print("  mp3:", [f.name for f in BGM.glob("*.mp3")])
# 场景1是否有 bgm 混音文件
print("\n=== 场景1 BGM/混音 ===")
for f in sc1.glob("*bgm*"):
    print(f"  {f.name} ({f.stat().st_size//1024}KB)")
