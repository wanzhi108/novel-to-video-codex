"""质量门闭环测试：一次过门 / 换seed重试后过门 / 全失败抛错。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import BaseEngine, ClipResult, EngineError, GenerateRequest  # noqa: E402
from engines.quality_loop import GenerationGate  # noqa: E402
from quality.gate import QualityGate  # noqa: E402

GOOD_VIDEO = Path("OpenMontage/projects/overtime-cat/renders/final.mp4")  # 30s 真视频
BAD_VIDEO = Path("story2/shot_01_kf.png")  # 图片冒充视频（gate 必失败）


class MockEngine(BaseEngine):
    def __init__(self, name: str, fail_first: int = 0, bad_path: Path | None = None):
        self.name = name
        self.calls = 0
        self.fail_first = fail_first
        self.bad_path = bad_path

    async def generate(self, req):
        self.calls += 1
        if self.calls <= self.fail_first and self.bad_path:
            return ClipResult(video_path=self.bad_path, engine=self.name, seed=req.seed)
        return ClipResult(video_path=GOOD_VIDEO, engine=self.name, seed=req.seed)


async def test_pass_first_try():
    eng = MockEngine("mock_good")
    gate = GenerationGate([eng], QualityGate())
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert clip.quality_report["passed"] is True, clip.quality_report
    assert eng.calls == 1
    print("✅ 一次过门: 引擎调用1次, passed=True")


async def test_retry_reseed():
    eng = MockEngine("mock_flaky", fail_first=1, bad_path=BAD_VIDEO)
    gate = GenerationGate([eng], QualityGate(), config=None)  # 默认 max_retries=2
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert eng.calls == 2, f"期望重试后共 2 次调用，实际 {eng.calls}"
    assert clip.quality_report["passed"] is True
    hist = clip.quality_report["retry_history"]
    assert hist[0]["passed"] is False and hist[1]["passed"] is True
    print(f"✅ 换seed重试: 调用2次, history=[{hist[0]['passed']},{hist[1]['passed']}] → passed")


async def test_all_fail():
    eng = MockEngine("mock_always_bad", fail_first=99, bad_path=BAD_VIDEO)
    gate = GenerationGate([eng], QualityGate(), config=None)
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert clip.quality_report["passed"] is False
    assert len(clip.quality_report["retry_history"]) == 3  # max_retries+1
    print(f"✅ 全失败: 3 次尝试均未过门，返回带 quality_report 的产物（不静默）")


def main():
    asyncio.run(test_pass_first_try())
    asyncio.run(test_retry_reseed())
    asyncio.run(test_all_fail())
    print("QUALITY_LOOP TEST OK")


if __name__ == "__main__":
    main()
