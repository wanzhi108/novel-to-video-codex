"""质量门闭环测试：一次过门 / 换seed重试后过门 / 全失败抛错。

媒体样本由 conftest 的 `sample_video` / `fake_video` 夹具**现场生成**：
此前引用的 `OpenMontage/**`、`story2/**` 大资产已移出 git 索引，CI 上没有它们
→ 3 个用例在 runner 上必挂（2026-10-11 首次真跑 CI 实测）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import BaseEngine, ClipResult, EngineError, GenerateRequest  # noqa: E402
from engines.quality_loop import GenerationGate  # noqa: E402
from quality.gate import QualityGate  # noqa: E402


class MockEngine(BaseEngine):
    def __init__(self, name: str, good_path: Path, fail_first: int = 0,
                 bad_path: Path | None = None):
        self.name = name
        self.calls = 0
        self.fail_first = fail_first
        self.bad_path = bad_path
        self.good_path = good_path

    async def generate(self, req):
        self.calls += 1
        if self.calls <= self.fail_first and self.bad_path:
            return ClipResult(video_path=self.bad_path, engine=self.name, seed=req.seed)
        return ClipResult(video_path=self.good_path, engine=self.name, seed=req.seed)


async def test_pass_first_try(sample_video):
    eng = MockEngine("mock_good", good_path=sample_video)
    gate = GenerationGate([eng], QualityGate())
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert clip.quality_report["passed"] is True, clip.quality_report
    assert eng.calls == 1
    print("✅ 一次过门: 引擎调用1次, passed=True")


async def test_retry_reseed(sample_video, fake_video):
    eng = MockEngine("mock_flaky", good_path=sample_video, fail_first=1, bad_path=fake_video)
    gate = GenerationGate([eng], QualityGate(), config=None)  # 默认 max_retries=2
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert eng.calls == 2, f"期望重试后共 2 次调用，实际 {eng.calls}"
    assert clip.quality_report["passed"] is True
    hist = clip.quality_report["retry_history"]
    assert hist[0]["passed"] is False and hist[1]["passed"] is True
    print(f"✅ 换seed重试: 调用2次, history=[{hist[0]['passed']},{hist[1]['passed']}] → passed")


async def test_all_fail(sample_video, fake_video):
    eng = MockEngine("mock_always_bad", good_path=sample_video, fail_first=99, bad_path=fake_video)
    gate = GenerationGate([eng], QualityGate(), config=None)
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)
    assert clip.quality_report["passed"] is False
    assert len(clip.quality_report["retry_history"]) == 3  # max_retries+1
    print(f"✅ 全失败: 3 次尝试均未过门，返回带 quality_report 的产物（不静默）")


def main():
    # 媒体样本由 conftest 夹具生成，直跑 __main__ 拿不到夹具 → 统一走 pytest
    print("请用 pytest 运行（样本视频由 conftest 夹具现场生成）：")
    print("  pytest tests/test_quality_loop.py -q")


if __name__ == "__main__":
    main()
