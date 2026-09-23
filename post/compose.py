"""视频合成（设计文档 §2.1 post/）—— FFmpeg 段级拼接 + 字幕 + BGM。

实现要点（参考 story2/assemble.py 与 main.py merge_videos_with_transitions）：
- xfade 链式转场（≤20 段；失败自动降级 fade → concat）
- ASS 字幕烧录（配合 post/subtitles.py 精确时间轴）
- BGM 混音（对白 ducking：sidechaincompress）
- 全程 ffmpeg -y 覆盖写（规避沙箱删除拦截，story2 GOTCHAS #15）

用法：
    from post.compose import compose_video
    out = await compose_video(
        clips=["clip1.mp4", "clip2.mp4"],
        output="final.mp4",
        subtitles={"texts": [...], "timings": [...], "styles": [...]},
        bgm="bgm.mp3", bgm_volume=0.25)
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .subtitles import Timing, to_ass

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
FPS = 30


async def _run(cmd: list[str], timeout: float = 600,
               cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                               cwd=str(cwd) if cwd else None))


async def probe_duration(path: Path) -> float:
    r = await _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=30)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


async def probe_has_audio(path: Path) -> bool:
    r = await _run([FFPROBE, "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=index", "-of", "csv=p=0", str(path)], timeout=30)
    return bool(r.stdout.strip())


def _ff_path(p: Path) -> str:
    """Windows 路径转 ffmpeg 滤镜可用形式（C:/x → C\\:/x）。"""
    s = str(Path(p).resolve()).replace("\\", "/")
    import re
    return re.sub(r"^([A-Za-z]):", r"\1\\:", s)


async def concat_xfade(clips: list[Path], output: Path, transition: str = "fade") -> Path:
    """xfade 链式拼接。段数 > 20 或失败时降级 concat。"""
    if not clips:
        raise ValueError("clips 为空")
    clips = [Path(c).resolve() for c in clips]
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        await _run([FFMPEG, "-y", "-i", str(clips[0]), "-c", "copy", str(output)])
        return output
    try:
        if len(clips) <= 20:
            await _xfade_chain(clips, output, transition)
            if output.exists() and output.stat().st_size > 1000:
                return output
    except Exception as exc:  # noqa: BLE001
        print(f"[Compose] xfade 失败({exc})，降级 concat", flush=True)
    # 降级：concat
    list_file = output.parent / f"{output.stem}_list.txt"
    list_file.write_text(
        "\n".join(f"file '{_ff_path(p)}'" for p in clips), encoding="utf-8")
    await _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c", "copy", str(output)])
    return output


async def _xfade_chain(clips: list[Path], output: Path, transition: str) -> None:
    """双输入 xfade 链（逐段与累积流交叉淡化），同时拼接音频轨。"""
    n = len(clips)
    durations = [await probe_duration(p) for p in clips]
    input_args: list[str] = []
    for clip in clips:
        input_args += ["-i", str(clip)]

    # 视频 xfade 链（offset 计算：下一个 xfade 偏移 = 当前输出时长 - 过渡时长）
    # 正确性关键：offset + duration 必须 <= 第一个输入时长，否则被 ffmpeg 静默丢弃。
    dur = 1.0
    vf = f"[0:v][1:v]xfade=transition={transition}:duration={dur}:offset={max(0.0, durations[0] - dur)}[v1]"
    cur = durations[0] + durations[1] - dur if n > 1 else durations[0]
    for i in range(2, n):
        offset = max(0.0, cur - dur)
        prev = f"v{i-1}"
        vf += f";[{prev}][{i}:v]xfade=transition={transition}:duration={dur}:offset={offset}[v{i}]"
        cur += durations[i] - dur
    vout = f"v{n-1}" if n > 1 else "0:v"

    # 音频：若全部输入有音频轨，用 concat 拼接（时长以视频为准）
    audio_flags = await asyncio.gather(*(probe_has_audio(p) for p in clips))
    has_audio = all(audio_flags)
    cmd: list[str]
    if has_audio:
        af = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
        fc = f"{vf};{af}"
        cmd = [FFMPEG, "-y", *input_args, "-filter_complex", fc,
               "-map", f"[{vout}]", "-map", "[aout]", "-shortest",
               "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-preset", "medium",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               str(output)]
    else:
        cmd = [FFMPEG, "-y", *input_args, "-filter_complex", vf,
               "-map", f"[{vout}]", "-r", str(FPS),
               "-c:v", "libx264", "-crf", "20", "-preset", "medium",
               "-pix_fmt", "yuv420p", str(output)]
    r = await _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"xfade 失败: {r.stderr[-300:]}")


async def burn_subtitles(video: Path, output: Path, texts: list[str],
                         timings: list[Timing], styles: Optional[list[str]] = None,
                         fonts_dir: Optional[Path] = None) -> Path:
    """ASS 字幕烧录（精确时间轴）。

    Windows 注意：ffmpeg ass filter 对盘符冒号(C:)解析易错，故在输出目录内
    以相对文件名运行（story2 同款方案，见 GOTCHAS #11）。
    """
    ass_text = to_ass(timings, texts, styles)
    video = Path(video).resolve()
    output = Path(output).resolve()
    workdir = output.parent
    workdir.mkdir(parents=True, exist_ok=True)
    ass_name = f"{output.stem}.ass"
    (workdir / ass_name).write_text(ass_text, encoding="utf-8")

    vf = f"ass={ass_name}"
    if fonts_dir:
        vf += f":fontsdir={fonts_dir}"

    cmd = [
        FFMPEG, "-y", "-i", str(video),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        str(output),
    ]
    r = await _run(cmd, cwd=workdir)
    if r.returncode != 0:
        raise RuntimeError(f"字幕烧录失败: {r.stderr[-300:]}")
    return output


async def mix_bgm(video: Path, bgm: Path, output: Path, bgm_volume: float = 0.25,
                  ducking: bool = True) -> Path:
    """BGM 混音（可选对白 ducking：sidechaincompress）。"""
    video = Path(video).resolve()
    bgm = Path(bgm).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # -i 输入用原始路径（勿转义盘符冒号，只有 filter 内部才需要 _ff_path）
    vp, bp = str(video), str(bgm)
    if ducking:
        # 对白(主) 压低 BGM(侧链)
        fc = (f"[1:a]volume={bgm_volume}[bgm];"
              f"[0:a][bgm]sidechaincompress=threshold=0.008:ratio=5:attack=20:release=400[amix]")
        cmd = [FFMPEG, "-y", "-i", vp, "-i", bp,
               "-filter_complex", fc,
               "-map", "0:v", "-map", "[amix]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               str(output)]
    else:
        cmd = [FFMPEG, "-y", "-i", vp, "-i", bp,
               "-filter_complex", f"[1:a]volume={bgm_volume}[bgm]",
               "-map", "0:v", "-map", "0:a", "-map", "[bgm]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-shortest", str(output)]
    r = await _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"BGM 混音失败: {r.stderr[-300:]}")
    return output


async def mux_narration(video: Path, narration: Path, output: Path) -> Path:
    """配音轨接入视频，带时长对齐（视频短于配音时 tpad 冻结末帧延展）。

    视频自带音频 → amix 叠加配音；视频无音频 → 配音直接作音轨。
    -shortest 语义：以较长者（配音）为输出时长，视频补帧到对齐。
    """
    video = Path(video).resolve()
    narration = Path(narration).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    vp, np = str(video), str(narration)
    vdur = await probe_duration(video)
    adur = await probe_duration(narration)
    diff = max(0.0, adur - vdur)

    if diff > 0.5:
        # 视频冻结末帧补足到配音时长（保动作原生节奏 + 保全部台词）
        fc = f"[0:v]tpad=stop_mode=clone:stop_duration={diff:.2f}[v]"
        cmd = [FFMPEG, "-y", "-i", vp, "-i", np, "-filter_complex", fc,
               "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(output)]
    elif await probe_has_audio(video):
        fc = ("[1:a]volume=1.0[narr];"
              "[0:a][narr]amix=inputs=2:duration=first:dropout_transition=2[amix]")
        cmd = [FFMPEG, "-y", "-i", vp, "-i", np, "-filter_complex", fc,
               "-map", "0:v", "-map", "[amix]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-shortest", str(output)]
    else:
        cmd = [FFMPEG, "-y", "-i", vp, "-i", np,
               "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-shortest", str(output)]
    r = await _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"配音混音失败: {r.stderr[-300:]}")
    return output


async def compose_video(clips: list[Path], output: Path,
                        subtitles: Optional[dict] = None,
                        bgm: Optional[Path] = None,
                        bgm_volume: float = 0.25,
                        narration: Optional[Path] = None,
                        transition: str = "fade") -> Path:
    """完整合成：拼接 → 配音对齐 → BGM → 字幕。

    narration: 外部配音轨（wav/mp3）。传入时自动做时长对齐（视频短则冻结补帧）。
    subtitles: {"texts": [...], "timings": [Timing...], "styles": [...], "fonts_dir": ...}
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    current = await concat_xfade(clips, output.parent / f"{output.stem}_concat.mp4", transition)
    if narration:
        narrated = output.parent / f"{output.stem}_narrated.mp4"
        current = await mux_narration(current, narration, narrated)
    if bgm:
        mixed = output.parent / f"{output.stem}_mixed.mp4"
        current = await mix_bgm(current, bgm, mixed, bgm_volume)
    if subtitles:
        subbed = output.parent / f"{output.stem}_subbed.mp4"
        current = await burn_subtitles(
            current, subbed,
            texts=subtitles["texts"], timings=subtitles["timings"],
            styles=subtitles.get("styles"), fonts_dir=subtitles.get("fonts_dir"))
    # 最终产物（重命名到目标）
    if current.resolve() != output.resolve():
        await _run([FFMPEG, "-y", "-i", str(current), "-c", "copy", str(output)])
    return output
