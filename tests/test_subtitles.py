"""post/subtitles 测试：精确时间轴 vs 均分对比 + ASS/SRT 生成。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from post.subtitles import (  # noqa: E402
    build_line_timings, even_split_timings, to_ass, to_srt)


def test_precise_timings():
    # 3 句，时长不等：1.2s / 2.3s / 0.9s，句间 0.45s
    durs = [1.2, 2.3, 0.9]
    timings = build_line_timings(durs, gap=0.45)
    assert len(timings) == 3
    # 第一句: [0, 1.2]
    assert abs(timings[0].start - 0.0) < 1e-6 and abs(timings[0].end - 1.2) < 1e-6
    # 第二句: [1.2+0.45, +2.3] = [1.65, 3.95]
    assert abs(timings[1].start - 1.65) < 1e-6 and abs(timings[1].end - 3.95) < 1e-6
    # 第三句: [3.95+0.45, +0.9] = [4.40, 5.30]
    assert abs(timings[2].start - 4.40) < 1e-6 and abs(timings[2].end - 5.30) < 1e-6
    # 每句时长 == 实际音频时长（精确 vs 均分的本质差异）
    for t, d in zip(timings, durs):
        assert abs((t.end - t.start) - d) < 1e-6
    print("✅ 精确时间轴: 逐句累加正确（非均分）")

    # 对比均分：3 句总 5.3s 均分 → 每句 1.767s，与真实时长差异显著
    even = even_split_timings(5.3, 3)
    diffs = [abs((e.end - e.start) - d) for e, d in zip(even, durs)]
    print(f"   均分偏差示例: {[round(d, 2) for d in diffs]}s（精确法为 0s）")
    assert max(diffs) > 0.5  # 均分偏差显著


def test_ass_srt_output():
    timings = build_line_timings([1.0, 2.0], gap=0.3)
    texts = ["你好，世界", "第二句台词"]
    ass = to_ass(timings, texts, speaker_styles=["Narr", "Default"])
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Narr" in ass
    assert "Dialogue: 0,0:00:01.30,0:00:03.30,Default" in ass
    assert "你好，世界" in ass

    srt = to_srt(timings, texts)
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:01,300 --> 00:00:03,300" in srt
    print("✅ ASS/SRT 生成: 时间码与样式正确")


def main():
    test_precise_timings()
    test_ass_srt_output()
    print("SUBTITLES TEST OK")


if __name__ == "__main__":
    main()
