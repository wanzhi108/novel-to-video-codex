"""story2 完整成片合成（P5 本地样片）—— 复用 post.compose 工业化链路。

输入（story2 已生成产物）：story2/videos/shot_XX_YY.mp4 + voice_lines + subs
输出：output/story2_final_{MMDD}.mp4

用法：venv\Scripts\python.exe scripts\compose_story2.py [--bgm bgm\epic.mp3] [--no-subtitles]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from post.compose import FFMPEG, _run, compose_video  # noqa: E402

STORY2 = Path("story2")
VIDEOS = STORY2 / "videos"
VOICE = STORY2 / "voice_lines"
SUBS = STORY2 / "subs"
OUT = Path("output")


def load_shots() -> list[dict]:
    return json.loads((STORY2 / "shots.json").read_text(encoding="utf-8"))["shots"]


def shot_segments(shot: dict) -> list[Path]:
    segs = shot.get("segments") or []
    return [VIDEOS / f"shot_{shot['id']:02d}_{i:02d}.mp4" for i in range(len(segs))
            if (VIDEOS / f"shot_{shot['id']:02d}_{i:02d}.mp4").exists()]


def merge_ass_scenes(ass_paths: list[Path]) -> str:
    """合并 4 个场景 ASS 为完整时间轴（按场景起始偏移累加）。"""
    header = None
    events = []
    cursor = 0.0
    for ap in ass_paths:
        text = ap.read_text(encoding="utf-8")
        if "[Events]" in text and header is None:
            header = text.split("[Events]")[0] + "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                m = re.match(r"Dialogue:\s*(\d+),(\d+):(\d+):([\d.]+),(\d+):(\d+):([\d.]+),(.*)", line)
                if m:
                    layer, h1, m1, s1, h2, m2, s2, rest = m.groups()
                    t1 = int(h1) * 3600 + int(m1) * 60 + float(s1) + cursor
                    t2 = int(h2) * 3600 + int(m2) * 60 + float(s2) + cursor
                    events.append(f"Dialogue: {layer},{_fmt(t1)},{_fmt(t2)},{rest}")
        cursor += _scene_duration(ap)
    return (header or "") + "\n".join(events) + "\n"


def _scene_duration(ass_path: Path) -> float:
    last = 0.0
    for line in ass_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"Dialogue:.*?,(\d+):(\d+):([\d.]+),(\d+):(\d+):([\d.]+),", line)
        if m:
            last = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6))
    return last


def _fmt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


async def concat_narration_probe(scene_wavs: list[Path], output: Path) -> Path:
    """配音轨拼接（带错误检查与逐段降级）。"""
    from post.compose import probe_duration
    output = Path(output).resolve()
    list_file = output.parent / f"{output.stem}_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in scene_wavs), encoding="utf-8")
    r = await _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output)])
    if r.returncode != 0 or not output.exists() or (await probe_duration(output)) < 1.0:
        print(f"  ⚠️ concat 配音失败({r.stderr[-120:]})，改用逐段拼接")
        tmp = output.parent / f"{output.stem}_tmp.wav"
        await _run([FFMPEG, "-y", "-i", str(scene_wavs[0].resolve()), "-c", "copy", str(tmp)])
        for wav in scene_wavs[1:]:
            merged = output.parent / f"{output.stem}_m.wav"
            r2 = await _run([FFMPEG, "-y", "-i", str(tmp), "-i", str(wav.resolve()),
                             "-filter_complex", "concat=n=2:v=0:a=1[a]",
                             "-map", "[a]", "-c:a", "pcm_s16le", str(merged)])
            if r2.returncode == 0:
                tmp.unlink(missing_ok=True)
                tmp = merged
        if tmp.exists():
            await _run([FFMPEG, "-y", "-i", str(tmp), "-c", "copy", str(output)])
    return output


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bgm", default=None, help="BGM 文件（默认 bgm/epic.mp3）")
    parser.add_argument("--no-subtitles", action="store_true", help="跳过字幕")
    args = parser.parse_args()

    shots = load_shots()
    workdir = OUT / "story2_work"
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. 收集 4 镜视频段
    clips: list[Path] = []
    scene_wavs: list[Path] = []
    scene_ass: list[Path] = []
    for shot in shots:
        segs = shot_segments(shot)
        if not segs:
            print(f"  ⚠️ shot_{shot['id']} 无视频段，跳过")
            continue
        clips.extend(segs)
        wav = VOICE / f"scene_{shot['id']}.wav"
        if wav.exists():
            scene_wavs.append(wav)
        ass = SUBS / f"scene{shot['id']}.ass"
        if ass.exists():
            scene_ass.append(ass)
    print(f"[ComposeStory2] {len(shots)} 镜, {len(clips)} 段, {len(scene_wavs)} 配音, {len(scene_ass)} 字幕")

    # 2. 配音轨
    narration = workdir / "narration.wav"
    await concat_narration_probe(scene_wavs, narration)

    # 3. 字幕（可选）
    subtitles = None
    if not args.no_subtitles and scene_ass:
        merged_ass = merge_ass_scenes(scene_ass)
        ass_file = workdir / "merged.ass"
        ass_file.write_text(merged_ass, encoding="utf-8")
        # 转成 compose_video 需要的 {texts, timings, styles}？直接用 ass 文件烧录更稳：
        subtitles = {"ass_file": ass_file}  # 由下方自定义流程处理

    # 4. 完整合成（compose_video：拼接→配音对齐→BGM→字幕）
    final = (OUT / f"story2_final_{time.strftime('%m%d')}.mp4").resolve()
    bgm_path = Path(args.bgm) if args.bgm else Path("bgm/epic.mp3")
    bgm_path = bgm_path if bgm_path.exists() else None

    if subtitles:
        # 带 ass 文件的流程：compose_video 到 BGM 后，手动烧 ass
        from post.compose import burn_subtitles, mix_bgm, mux_narration
        current = workdir / "concat.mp4"
        from post.compose import concat_xfade
        current = await concat_xfade(clips, current)
        current = await mux_narration(current, narration, workdir / "narrated.mp4")
        if bgm_path:
            current = await mix_bgm(current, bgm_path, workdir / "bgm.mp4", bgm_volume=0.18)
        ass_name = subtitles["ass_file"].name
        r = await _run([FFMPEG, "-y", "-i", str(current.resolve()),
                        "-vf", f"ass={ass_name}",
                        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                        str(final)], cwd=workdir)
        if r.returncode != 0:
            print(f"  ⚠️ 字幕烧录失败({r.stderr[-200:]})，跳过字幕")
            await _run([FFMPEG, "-y", "-i", str(current.resolve()), "-c", "copy", str(final)])
    else:
        await compose_video(clips, final, narration=narration, bgm=bgm_path, bgm_volume=0.18)

    from post.compose import probe_duration
    dur = await probe_duration(final)
    size = final.stat().st_size / (1024 * 1024)
    print(f"\n🎬 成片: {final} ({dur:.1f}s, {size:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
