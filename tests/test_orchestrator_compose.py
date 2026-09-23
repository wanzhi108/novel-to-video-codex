"""Orchestrator.run_compose 测试（真实 story2 素材）。"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import Orchestrator  # noqa: E402
from post.compose import probe_duration  # noqa: E402
from post.subtitles import build_line_timings  # noqa: E402


async def main():
    segs = [Path(f"story2/videos/shot_01_{i:02d}.mp4") for i in range(4)]
    if not segs[0].exists():
        print("跳过（无 story2 素材）")
        return
    out_dir = Path("output/orch_compose_test")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    orch = Orchestrator()
    final = out_dir / "final.mp4"
    narration = Path("story2/voice_lines/scene_1.wav")
    timings = build_line_timings([1.2, 2.3, 0.9, 1.5], gap=0.45)
    texts = ["小杨，你这方案，狗都不要。", "明天不用来了。",
             "所有人都觉得，他完了。", "可他只是笑了笑。"]
    bgm = Path("bgm/epic.mp3")

    await orch.run_compose(
        segs, final,
        narration=narration if narration.exists() else None,
        subtitles={"texts": texts, "timings": timings},
        bgm=bgm if bgm.exists() else None,
        bgm_volume=0.15)

    assert final.exists() and final.stat().st_size > 10000
    dur = await probe_duration(final)
    print(f"✅ Orchestrator.run_compose: {final.name} ({dur:.1f}s, {final.stat().st_size/1e6:.1f}MB)")
    print("ORCHESTRATOR COMPOSE TEST OK")


if __name__ == "__main__":
    asyncio.run(main())
