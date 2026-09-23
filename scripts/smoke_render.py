"""真实出片冒烟：ComfyUIEngine 本地生成一段最短 LTX I2V，走质量门。

用法：venv\Scripts\python.exe scripts\smoke_render.py [首帧图]
依赖：ComfyUI :8188 在线（--lowvram 模式）。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.local import ComfyUIEngine  # noqa: E402
from engines.base import GenerateRequest  # noqa: E402
from quality.gate import QualityGate  # noqa: E402


async def main() -> int:
    frame = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("story2/shot_01_kf.png")
    if not frame.exists():
        print(f"首帧不存在: {frame}")
        return 1

    engine = ComfyUIEngine()
    print(f"[SmokeRender] ComfyUI 可用: {engine.is_available()}")
    if not engine.is_available():
        return 1

    req = GenerateRequest(
        prompt="slow cinematic push-in, the man with glasses looks up calmly, subtle head movement, tense office atmosphere",
        first_frame=frame,
        width=960, height=1728,
        duration_seconds=1.4,      # 33 帧 @24fps（LTX 最短安全值）
        fps=24,
        output_name="smoke_render",
        output_dir=Path("output/local_clips"),
        timeout_seconds=1200.0,
    )
    print(f"[SmokeRender] 提交: I2V {req.width}x{req.height} 33f@24fps, 首帧 {frame.name}")
    t0 = time.time()
    try:
        clip = await engine.generate(req)
    except Exception as exc:  # noqa: BLE001
        print(f"[SmokeRender] ❌ 生成失败: {exc}")
        return 1
    elapsed = time.time() - t0
    print(f"[SmokeRender] ✅ 生成完成: {clip.video_path} ({elapsed:.0f}s) seed={clip.seed}")

    # 质量门
    gate = QualityGate()
    report = await gate.check_video(clip.video_path, expect_duration=req.duration_seconds)
    mark = "PASS" if report["passed"] else "FAIL"
    print(f"[SmokeRender] 质量门 {mark}: {report['resolution']} {report['duration']}s "
          f"frames={report['frames']} issues={report['issues']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
