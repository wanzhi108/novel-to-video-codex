"""把 6 个 Wan5B 镜合成连贯开场片段（统一 1408x2560 @48fps 后拼接）。"""
import os
import subprocess, sys, os
from pathlib import Path

FFMPEG = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffmpeg.exe")
OUT_DIR = Path(r"D:\novel-to-video-codex\output\wan5b_opening")
WORK = OUT_DIR / "_norm"
WORK.mkdir(parents=True, exist_ok=True)

# shot 顺序与源文件
shots = [
    ("wan5b_opening.mp4", "s1"),   # shot1 药铺前堂 (2816x5120)
    ("wan5b_shot2.mp4", "s2"),     # shot2 摸黑起身 (2816x5120)
    ("wan5b_shot3.mp4", "s3"),     # shot3 后院煎药 (1408x2560)
    ("wan5b_shot4.mp4", "s4"),     # shot4 碾薄荷 (1408x2560)
    ("wan5b_shot5.mp4", "s5"),     # shot5 掌柜对话 (1408x2560)
    ("wan5b_shot6.mp4", "s6"),     # shot6 划痕 (1408x2560)
]

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFMPEG ERR:", r.stderr[-1500:], flush=True)
        sys.exit(1)
    return r

norm_files = []
for src, tag in shots:
    srcp = OUT_DIR / src
    if not srcp.exists():
        print(f"缺: {src}", flush=True); sys.exit(1)
    dst = WORK / f"{tag}_norm.mp4"
    # 统一 1408x2560 @48fps h264 yuv420p（9:16 保比例）
    run([FFMPEG, "-y", "-i", str(srcp), "-vf", "scale=1408:2560:force_original_aspect_ratio=decrease,"
        "pad=1408:2560:(ow-iw)/2:(oh-ih)/2", "-r", "48", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", str(dst)])
    norm_files.append(dst)
    print(f"归一化 {src} -> {dst.name} ({round(dst.stat().st_size/1e6,1)}MB)", flush=True)

# concat（重编码确保一致）
listf = WORK / "concat.txt"
listf.write_text("".join(f"file '{f.as_posix()}'\n" for f in norm_files), encoding="utf-8")
out = OUT_DIR / "opening_sequence.mp4"
run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listf), "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", str(out)])
print("SAVED:", out, round(out.stat().st_size/1e6,1), "MB", flush=True)
# probe
probe = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffprobe.exe")
r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-show_entries",
                    "stream=width,height,r_frame_rate,nb_frames", "-of", "default=noprint_wrappers=1", str(out)],
                   capture_output=True, text=True)
print(r.stdout.strip(), flush=True)
