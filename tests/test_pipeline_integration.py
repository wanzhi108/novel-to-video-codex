"""工业化骨架端到端集成冒烟（mock 引擎，不真实生成）。

验证链路：TaskQueue（并发/续传）→ GenerationGate（质量门+重试）
          → CostTracker（预算）→ 结果落盘可追溯。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import BaseEngine, ClipResult, GenerateRequest  # noqa: E402
from engines.quality_loop import GenerationGate  # noqa: E402
from quality.gate import QualityGate  # noqa: E402
from scheduler.cost import CostTracker  # noqa: E402
from scheduler.tasks import Task, TaskQueue  # noqa: E402

GOOD = Path("OpenMontage/projects/overtime-cat/renders/final.mp4")
BAD = Path("story2/shot_01_kf.png")


class MockCloudEngine(BaseEngine):
    """模拟云端引擎：计费 + 前 n 次返回坏产物。"""

    def __init__(self, name: str, cost: float, fail_first: int = 0):
        self.name = name
        self.cost = cost
        self.calls = 0
        self.fail_first = fail_first

    async def generate(self, req):
        self.calls += 1
        path = BAD if self.calls <= self.fail_first else GOOD
        return ClipResult(video_path=path, engine=self.name, seed=req.seed,
                          cost_usd=self.cost)

    def estimate_cost(self, req):
        return self.cost


async def main():
    # 1. 组装：一个"永远失败"引擎 + 一个"永远成功"引擎
    bad_forever = MockCloudEngine("bad_mock", cost=0.30, fail_first=99)
    good = MockCloudEngine("good_mock", cost=0.40)
    tracker = CostTracker(budget_usd=2.0, mode="cap")

    # scene-1 走 [bad, good]（验证 reseed 后 switch_engine 换引擎）
    gate_a = GenerationGate([bad_forever, good], QualityGate())
    # scene-2/3 直接走 good
    gate_b = GenerationGate([good], QualityGate())

    # 2. 三个场景任务入队
    q = TaskQueue(max_concurrency=2)
    clips = []

    async def make_scene(i: int, gate):
        async def run():
            req = GenerateRequest(prompt=f"scene {i} motion", duration_seconds=5.0,
                                  output_name=f"scene_{i}")
            eid = tracker.estimate("mock_cloud", f"i2v scene {i}", 0.30)
            if not tracker.reserve(eid):
                raise RuntimeError("预算不足")
            clip = await gate.generate(req)
            tracker.reconcile(eid, clip.cost_usd)
            clips.append(clip)
        return run

    q.submit(Task(id="scene-1", run=await make_scene(1, gate_a)))
    q.submit(Task(id="scene-2", run=await make_scene(2, gate_b)))
    q.submit(Task(id="scene-3", run=await make_scene(3, gate_b)))

    await q.run()

    # 3. 断言
    prog = q.progress()
    assert prog["done"] == 3, f"期望 3 完成: {prog}"
    assert len(clips) == 3
    passed = sum(1 for c in clips if c.quality_report and c.quality_report.get("passed"))
    assert passed == 3, f"期望 3 个都过质量门: {[c.quality_report for c in clips]}"
    # scene-1: bad 尝试 2 次（reseed 后仍坏）→ switch_engine 到 good → 成功
    assert bad_forever.calls == 2, f"bad_mock 应调用 2 次: {bad_forever.calls}"
    assert good.calls == 3, f"good_mock 应调用 3 次(scene-1 换入 + scene-2/3): {good.calls}"
    # scene-1 的 retry_history 应体现 switch_engine
    s1 = [c for c in clips if c.quality_report and c.engine == "good_mock"]
    hist = s1[0].quality_report["retry_history"]
    assert hist[0]["engine"] == "bad_mock" and hist[1]["engine"] == "bad_mock"
    assert hist[2]["engine"] == "good_mock", f"scene-1 应换引擎成功: {hist}"
    # 成本统计：3 个场景都用 good(0.40)
    summary = tracker.summary()
    assert abs(summary["spent_usd"] - 1.20) < 1e-6, f"期望花费 1.20: {summary}"
    assert summary["remaining_usd"] > 0.5

    print(f"✅ 集成冒烟通过: 3 任务完成, 质量门全过, 成本=${summary['spent_usd']}, "
          f"剩余=${summary['remaining_usd']:.2f}")
    print(f"   bad_mock={bad_forever.calls} 次(2次后换引擎), good_mock={good.calls} 次")
    print(f"   scene-1 历史: {[h['engine'] for h in hist]} → 换引擎成功")
    print("INTEGRATION OK")


if __name__ == "__main__":
    asyncio.run(main())
