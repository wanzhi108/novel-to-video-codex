"""拼接 6 个 A+C 镜(统一 1408x2560@48fps)成连贯开场。"""
import os
import subprocess, sys
from pathlib import Path

FFMPEG = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffmpeg.exe")
FFPROBE = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffprobe.exe")
OUT_DIR = Path(r"D:\novel-to-video-codex\output\wan5b_ac")
files = [OUT_DIR / f"ac_shot{i}.mp4" for i in range(1, 7)]
for f in files:
    if not f.exists() or f.stat().st_size < 10000:
        print("缺:", f.name); sys.exit(1)
listf = OUT_DIR / "concat.txt"
listf.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
out = OUT_DIR / "ac_opening.mp4"
r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", str(out)],
                   capture_output=True, text=True)
if r.returncode != 0:
    print("ERR:", r.stderr[-1500:]); sys.exit(1)
print("SAVED:", out, round(out.stat().st_size/1e6,1), "MB", flush=True)
p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-show_entries",
                    "stream=width,height,r_frame_rate,nb_frames", "-of", "default=noprint_wrappers=1", str(out)],
                   capture_output=True, text=True)
print(p.stdout.strip(), flush=True)
