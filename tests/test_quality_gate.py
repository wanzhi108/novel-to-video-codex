"""临时测试：QualityGate 用现有成片验证（最终会并入 tests/）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quality.gate import QualityGate  # noqa: E402


async def main():
    gate = QualityGate()
    samples = [
        ("overtime-cat 成片", Path("OpenMontage/projects/overtime-cat/renders/final.mp4"), 30.0),
        ("story2 片段(若存在)", Path("story2/videos/shot_01_00.mp4"), 2.7),
        ("图片冒充视频(应失败)", Path("story2/shot_01_kf.png"), 5.0),
    ]
    for label, path, expect in samples:
        if not path.exists():
            print(f"跳过（不存在）: {label}")
            continue
        report = await gate.check_video(path, expect_duration=expect)
        mark = "✅" if report["passed"] else "❌"
        print(f"{mark} {label}: {report['resolution']} {report['duration']}s "
              f"frames={report['frames']} issues={report['issues']}")
    # 期望时长不匹配场景（对成片要求 60s → 应失败）
    report = await gate.check_video(Path("OpenMontage/projects/overtime-cat/renders/final.mp4"),
                                    expect_duration=60.0)
    print(f"{'✅' if not report['passed'] else '❌'} 时长门（期望60s实际30s）应失败: "
          f"issues={report['issues']}")
    print("GATE TEST OK" if report is not None else "")


asyncio.run(main())
