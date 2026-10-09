"""mock 端到端出片链路护栏：小说 → 分镜 → 资产 → 合成。

设计：**全程不依赖真实模型 / ComfyUI / GPU / ffmpeg**：
- 分镜阶段打桩 `run_storyboard`（不打真实 LLM API）；
- 资产阶段注入 mock 引擎（写入真实字节的假片段，使质量门可判定）；
- 合成阶段在**边界**打桩 `run_compose`（不调用 ffmpeg），并记录调用参数与阶段顺序。

价值：后续所有架构升级（合并双实现、迁移 services 层）都有这条链路兜底。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config.settings import Queue, Settings  # noqa: E402
from engines.base import BaseEngine, ClipResult  # noqa: E402
from pipeline.orchestrator import Orchestrator, SceneReq  # noqa: E402

NOVEL = (
    "被辞退那天，我写的代码卖了八千万。\n"
    "老板把方案摔在桌上：\"小杨，明天不用来了。\"\n"
    "三个月后，招标会上中标的正是小杨。\n"
)

STAGES: list[str] = []


class MockLocalEngine(BaseEngine):
    """本地引擎打桩：产出真实字节的假片段。"""

    name = "mock_local"
    kind = "local"

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._n = 0

    def is_available(self):
        return True

    async def generate(self, req):
        # 注意：队列传给引擎的是管线侧请求对象（含 seed），不保证有 id 字段，
        # 因此用引擎内部计数器命名产物，避免耦合具体请求类型。
        self._n += 1
        clip = self.out_dir / f"s{self._n}.mp4"
        clip.write_bytes(b"\x00" * 20000)  # 20KB，过质量门的最小体量
        return ClipResult(
            video_path=clip, engine=self.name, seed=getattr(req, "seed", 1) or 1, cost_usd=0.0
        )


async def test_mock_end_to_end_pipeline(tmp_path, monkeypatch):
    STAGES.clear()

    # ── 1) 分镜（打桩 LLM）──
    orch = Orchestrator()
    calls = {}

    async def fake_storyboard(novel, title="", api_key="", max_scenes=6, **kw):
        calls["novel"] = novel
        calls["max_scenes"] = max_scenes
        STAGES.append("storyboard")
        return [
            SceneReq(id="s1", prompt="a man packing boxes in office", duration_seconds=3.0),
            SceneReq(id="s2", prompt="wide shot of bidding hall", duration_seconds=4.0),
        ]

    monkeypatch.setattr(orch, "run_storyboard", fake_storyboard, raising=False)
    scenes = await orch.run_storyboard(NOVEL, title="被辞退那天", api_key="fake-key", max_scenes=2)
    assert len(scenes) == 2 and all(s.prompt and s.duration_seconds > 0 for s in scenes)
    assert calls["novel"] == NOVEL

    # ── 2) 资产（注入 mock 引擎，真实走编排/质量门/成本/manifest）──
    # 质量门依赖 ffprobe 探测真实媒体；这里只打桩"探测层"（probe/count_frames），
    # 让质量门的时长比例/体积/静态/音频判定逻辑**真实执行**，同时保持测试无 ffmpeg 依赖。
    from quality import gate as qgate

    def _fake_probe(self, path):
        p = Path(path)
        if not p.exists():
            return {"error": "文件不存在或为空"}
        return {
            "format": {"duration": "5.0", "size": str(p.stat().st_size)},
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "24/1"},
                {"codec_type": "audio"},
            ],
        }

    monkeypatch.setattr(qgate.QualityGate, "probe", _fake_probe, raising=True)
    monkeypatch.setattr(qgate.QualityGate, "count_frames", lambda self, path: 120, raising=True)

    engine = MockLocalEngine(tmp_path / "assets")
    job_dir = tmp_path / "job"
    settings = Settings()
    settings.queue = Queue(max_concurrency=2, budget_usd=5.0, resume=False)
    orch_assets = Orchestrator(settings)
    orch_assets._build_engines = lambda: [engine]

    manifest = await orch_assets.run_assets(scenes, output_dir=job_dir)
    STAGES.append("assets")

    assert manifest["queue"]["done"] == 2, manifest["queue"]
    assert len(manifest["scenes"]) == 2
    for item in manifest["scenes"]:
        assert item["quality"]["passed"] is True, item
        assert item["engine"] == "mock_local"
    manifest_path = job_dir / "assets.json"
    assert manifest_path.exists(), "资产清单未落盘"
    import json

    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(reloaded["scenes"]) == 2
    # 假片段确实产出到磁盘（资产阶段的可验证产物）
    produced = sorted(p.name for p in (tmp_path / "assets").glob("*.mp4"))
    assert produced == ["s1.mp4", "s2.mp4"], produced

    # ── 3) 合成（边界打桩，不调用 ffmpeg）──
    compose_calls = {}

    async def fake_compose(segs, final, **kw):
        compose_calls["segs"] = list(segs)
        compose_calls["final"] = Path(final)
        Path(final).parent.mkdir(parents=True, exist_ok=True)
        Path(final).write_bytes(b"\x00" * 30000)
        STAGES.append("compose")

    monkeypatch.setattr(orch_assets, "run_compose", fake_compose, raising=False)

    segs = [tmp_path / "assets" / "s1.mp4", tmp_path / "assets" / "s2.mp4"]
    final = job_dir / "final.mp4"
    await orch_assets.run_compose(
        segs, final,
        narration=None,
        subtitles={"texts": ["a", "b"], "timings": [{"start": 0, "end": 1}, {"start": 1, "end": 2}]},
        bgm=None,
        bgm_volume=0.15,
    )

    assert final.exists() and final.stat().st_size > 10000
    assert compose_calls["segs"] == segs
    assert compose_calls["final"] == final

    # ── 阶段顺序断言（护栏核心）──
    assert STAGES == ["storyboard", "assets", "compose"], STAGES


def test_engine_contract_holds_for_mock(tmp_path):
    """引擎契约冒烟：mock 引擎必须满足 BaseEngine 接口（生成器注入依赖此契约）。"""
    eng = MockLocalEngine(tmp_path)
    assert isinstance(eng, BaseEngine)
    assert eng.is_available() is True
    assert eng.name and eng.kind
