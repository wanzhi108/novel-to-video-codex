"""审查已完成场景(1-5)成片的技术指标 + 视觉质量。"""
import os
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

from quality.visual import assess_video  # noqa: E402

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    vs = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    fmt = d.get("format", {})
    return {
        "w": vs.get("width"), "h": vs.get("height"),
        "fps": vs.get("r_frame_rate"), "nb_frames": vs.get("nb_frames"),
        "dur": float(fmt.get("duration", 0)), "size": int(fmt.get("size", 0)),
    }


print("=" * 78)
print("审查已完成场景成片 (scene_00X_final.mp4)")
print("=" * 78)

for sid in range(1, 6):
    d = OUT / f"scene_{sid:03d}"
    # 找成片：优先 final，其次 with_bgm，再 industrial
    cand = None
    for name in [f"scene_{sid:03d}_final.mp4", f"scene_{sid:03d}_with_bgm.mp4",
                 f"scene_{sid:03d}_sfx.mp4", f"industrial_{sid}.mp4"]:
        p = d / name
        if p.exists():
            cand = p
            break
    if not cand:
        print(f"\n场景 {sid}: 成片未找到")
        continue

    tech = probe(cand)
    print(f"\n【场景 {sid}】{cand.name}  ({cand.stat().st_size//1024}KB)")
    if tech:
        fps_num = tech["fps"].split("/")[0] if tech["fps"] else "?"
        print(f"  尺寸: {tech['w']}x{tech['h']}  帧率: {tech['fps']}  帧数: {tech['nb_frames']}  时长: {tech['dur']:.2f}s")
    # 视觉评估
    vq = assess_video(str(cand))
    print(f"  清晰度: sharp_min={vq['sharpness_min']} sharp_mean={vq['sharpness_mean']} "
          f"运动: {vq['motion']} 黑帧: {vq['black_frames']} -> {'⚠️'+str(vq['issues']) if not vq['passed'] else '✅ 通过'}")
