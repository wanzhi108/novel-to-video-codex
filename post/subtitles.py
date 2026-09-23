"""精确字幕时间轴（本地优化 L1：解决"音画不同步/字幕对不上"）。

现状问题（代码事实）：main.py / story2 的兜底 ASS 生成用
`total_duration * i / n` **均分**每句时长——与 TTS 实际读音时长不符，
导致字幕提前/滞后于配音。

本模块提供**逐句精确时间轴**：基于每句 TTS 音频的真实时长累加
（含句间留白 GAP），生成 ASS/SRT。

用法：
    from post.subtitles import build_line_timings, to_ass, to_srt
    timings = build_line_timings(line_durations=[1.2, 2.3, 0.9], gap=0.45)
    ass = to_ass(timings, texts=["你好", "世界", "结束"], speaker_styles=...)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Timing:
    start: float
    end: float


def build_line_timings(line_durations: list[float], gap: float = 0.45,
                       lead_in: float = 0.0) -> list[Timing]:
    """逐句精确时间轴：按每句真实音频时长累加，句间插入留白。

    Args:
        line_durations: 每句 TTS 音频的真实时长（秒，由 ffprobe 测得）。
        gap: 句间静音（秒）。与 gen_dialogue.py 的 GAP=0.45 一致。
        lead_in: 片头预留（秒），默认 0。

    Returns:
        [(start, end), ...]，end-start == 对应句子时长（不含留白）。
    """
    timings: list[Timing] = []
    cursor = lead_in
    for dur in line_durations:
        timings.append(Timing(start=cursor, end=cursor + dur))
        cursor += dur + gap
    return timings


def even_split_timings(total_duration: float, n: int, lead_in: float = 0.0) -> list[Timing]:
    """均分时间轴（旧逻辑，保留用于对比/兜底）。"""
    if n <= 0:
        return []
    step = total_duration / n
    return [Timing(start=lead_in + i * step, end=lead_in + (i + 1) * step) for i in range(n)]


def _fmt_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def to_ass(timings: list[Timing], texts: list[str],
           speaker_styles: Optional[list[str]] = None,
           width: int = 1080, height: int = 1920) -> str:
    """生成 ASS 字幕。speaker_styles 与 texts 等长（Style 名）。"""
    if len(texts) != len(timings):
        raise ValueError(f"texts({len(texts)}) 与 timings({len(timings)}) 长度不一致")
    styles = speaker_styles or (["Default"] * len(texts))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,36,&H00FFFFFF,&H00000000,&H80000000,&H64000000,0,0,0,0,100,100,0,0,1,2.5,1.5,2,60,60,30,1
Style: Narr,Microsoft YaHei,32,&H00FFFFFF,&H00000000,&H80000000,&H96000000,0,0,0,0,100,100,0,0,1,3,2,2,60,60,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for t, text, style in zip(timings, texts, styles):
        safe = text.replace("\n", r"\N")
        events.append(
            f"Dialogue: 0,{_fmt_ass(t.start)},{_fmt_ass(t.end)},{style},,0,0,0,,{safe}")
    return header + "\n".join(events) + "\n"


def _fmt_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(timings: list[Timing], texts: list[str]) -> str:
    """生成 SRT 字幕。"""
    if len(texts) != len(timings):
        raise ValueError("texts 与 timings 长度不一致")
    lines = []
    for i, (t, text) in enumerate(zip(timings, texts), 1):
        lines.append(f"{i}\n{_fmt_srt(t.start)} --> {_fmt_srt(t.end)}\n{text}\n")
    return "\n".join(lines)
