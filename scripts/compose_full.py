"""用 ffmpeg concat demuxer 稳定拼接15场景成片。"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")
from post.compose import FFMPEG  # noqa: E402

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
clips = []
for i in range(1, 16):
    p1 = OUT / f"scene_{i:03d}" / f"scene_{i:03d}_final.mp4"
    p2 = OUT / f"scene_{i:03d}_final.mp4"
    if p1.exists():
        clips.append(p1)
    elif p2.exists():
        clips.append(p2)

# 所有片段二次编码为统一格式(960x1728, 24fps, h264+aac)再concat（保证流兼容）
norm_dir = OUT / "_norm"
norm_dir.mkdir(exist_ok=True)
norm_clips = []
for i, c in enumerate(clips):
    n = norm_dir / f"n_{i:02d}.mp4"
    # 统一分辨率/帧率/编码，避免 concat 流不兼容
    r = subprocess.run(
        [FFMPEG, "-y", "-i", str(c), "-vf", "scale=960:1728:force_original_aspect_ratio=decrease,"
         "pad=960:1728:(ow-iw)/2:(oh-ih)/2", "-r", "24", "-c:v", "libx264", "-crf", "20",
         "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
         "-ac", "2", "-shortest", str(n)],
        capture_output=True, text=True, timeout=300)
    if n.exists() and n.stat().st_size > 1000:
        norm_clips.append(n)
        print(f"归一 {i}: {n.stat().st_size//1024}KB")
    else:
        print(f"归一 {i} 失败: {r.stderr[-100:]}")

# concat demuxer
list_file = norm_dir / "list.txt"
with open(list_file, "w", encoding="utf-8") as f:
    for n in norm_clips:
        f.write(f"file '{n.resolve()}'\n")

final = OUT / "深夜赶工_完整成片.mp4"
r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(final)], capture_output=True, text=True, timeout=300)
size = final.stat().st_size if final.exists() else 0
print(f"\n{'✅' if size > 1000 else '❌'} 完整成片: {final} ({size//1024}KB)")
if size <= 1000:
    print("stderr:", r.stderr[-200:])
