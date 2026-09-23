"""Orchestrator.run_assets 测试：批量场景 → 引擎/质量门/成本 → manifest 落盘。

用 mock 引擎（不真实生成），验证编排层正确性；真实引擎链路已由
test_pipeline_integration.py 覆盖。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import BaseEngine, ClipResult  # noqa: E402
from pipeline.orchestrator import Orchestrator, SceneReq  # noqa: E402
from config.settings import Settings, Engines, EngineCloud, Queue  # noqa: E402

GOOD = Path("OpenMontage/projects/overtime-cat/renders/final.mp4")


class MockGoodEngine(BaseEngine):
    name = "mock_good"
    kind = "cloud"

    def is_available(self):
        return True

    async def generate(self, req):
        return ClipResult(video_path=GOOD, engine=self.name, seed=req.seed, cost_usd=0.1)


async def test_run_assets():
    import shutil
    settings = Settings()
    settings.queue = Queue(max_concurrency=2, budget_usd=5.0, resume=True)
    orch = Orchestrator(settings)
    # 注入 mock 引擎（绕过 _build_engines 的可用性探测）
    orch._build_engines = lambda: [MockGoodEngine()]

    scenes = [
        SceneReq(id="s1", prompt="cat walks to bowl", duration_seconds=3.0),
        SceneReq(id="s2", prompt="man types at night", duration_seconds=4.0),
        SceneReq(id="s3", prompt="office wide shot", duration_seconds=5.0),
    ]
    out_dir = Path("output/pipeline_test")
    if out_dir.exists():          # 清理残留（含 queue_state.json，避免持久化跳过）
        shutil.rmtree(out_dir)
    manifest = await orch.run_assets(scenes, output_dir=out_dir)

    assert manifest["queue"]["done"] == 3, manifest["queue"]
    assert len(manifest["scenes"]) == 3
    for item in manifest["scenes"]:
        assert item["quality"]["passed"] is True, item
        assert item["engine"] == "mock_good"
    assert abs(manifest["cost"]["spent_usd"] - 0.3) < 1e-6, manifest["cost"]

    # manifest 落盘验证
    mpath = out_dir / "assets.json"
    assert mpath.exists()
    reloaded = json.loads(mpath.read_text(encoding="utf-8"))
    assert len(reloaded["scenes"]) == 3

    print(f"✅ Orchestrator.run_assets: 3 场景完成, 全过质量门, "
          f"成本=${manifest['cost']['spent_usd']}, manifest={mpath}")


def test_from_settings():
    """编排器配置驱动：settings 影响并发/预算。"""
    from config.settings import Settings, Queue
    s = Settings()
    s.queue = Queue(max_concurrency=3, budget_usd=7.0, resume=False)
    orch = Orchestrator(s)
    assert orch.settings.queue.max_concurrency == 3
    assert orch.tracker.budget_usd == 7.0
    print("✅ Orchestrator 配置驱动: 并发/预算来自 settings")


def main():
    asyncio.run(test_run_assets())
    test_from_settings()
    print("ORCHESTRATOR TEST OK")


if __name__ == "__main__":
    main()
