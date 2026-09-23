"""post/compose 集成测试：真实 LTX 产物 → xfade 拼接 → 精确字幕 → BGM 混音。"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from post.compose import (  # noqa: E402
    burn_subtitles, compose_video, concat_xfade, mix_bgm, probe_duration)
from post.subtitles import build_line_timings  # noqa: E402


async def main():
    clip = Path("output/local_clips/smoke_render.mp4")
    if not clip.exists():
        print(f"跳过（无真实产物）: {clip}")
        return
    out_dir = Path("output/compose_test")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # 1. 拼接（同段复制 2 份模拟多镜）
    clips = [clip, clip]
    concat = await concat_xfade(clips, out_dir / "concat.mp4")
    d = await probe_duration(concat)
    print(f"✅ xfade 拼接: {concat.name} 时长 {d:.2f}s（期望≈{await probe_duration(clip) * 2 - 1:.2f}s）")

    # 2. 精确字幕烧录（3 句台词，时长不等）
    timings = build_line_timings([1.0, 1.4, 0.8], gap=0.3)
    texts = ["小杨，你这方案，狗都不要。", "明天不用来了。", "所有人都觉得，他完了。"]
    subbed = await burn_subtitles(concat, out_dir / "subbed.mp4", texts, timings)
    print(f"✅ 精确字幕烧录: {subbed.name}")

    # 3. BGM 混音（用 bgm/epic.mp3）
    bgm = Path("bgm/epic.mp3")
    if bgm.exists():
        mixed = await mix_bgm(subbed, bgm, out_dir / "mixed.mp4", bgm_volume=0.2)
        print(f"✅ BGM 混音: {mixed.name}")

    # 4. 完整 compose_video 一步到位
    final = await compose_video(
        clips, out_dir / "final.mp4",
        subtitles={"texts": texts, "timings": timings},
        bgm=bgm if bgm.exists() else None)
    fd = await probe_duration(final)
    print(f"✅ compose_video 全链: {final.name} 时长 {fd:.2f}s")
    assert final.exists() and final.stat().st_size > 10000
    print("COMPOSE TEST OK")


if __name__ == "__main__":
    asyncio.run(main())
