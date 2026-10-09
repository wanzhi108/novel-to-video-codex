"""资产缓存（app/asset_cache.py）+ 编排层复用 回归测试。

目标：同参产物（提示词/种子/分辨率/时长/模型）二次生成直接复用，
避免"同一镜重新跑一遍 8 分钟"。
"""
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _params(**over):
    base = {"prompt": "a man packing boxes", "seed": 42, "width": 960, "height": 1728,
            "duration_seconds": 4.0, "model": "wan5b", "steps": 8}
    base.update(over)
    return base


def test_cache_module_api():
    from app import asset_cache

    for name in ("cache_key", "AssetCache"):
        assert hasattr(asset_cache, name), f"app.asset_cache 缺少 {name}"
    for name in ("lookup", "store", "stats", "path_for"):
        assert hasattr(asset_cache.AssetCache, name), f"AssetCache 缺少 {name}"


def test_cache_key_stable_and_sensitive():
    from app.asset_cache import cache_key

    assert cache_key(_params()) == cache_key(_params()), "同参必须同键"
    assert cache_key(_params()) != cache_key(_params(seed=43)), "种子不同应不同键"
    assert cache_key(_params()) != cache_key(_params(prompt="other")), "提示词不同应不同键"
    # 键顺序不影响结果（canonical 化）
    k1 = cache_key({"a": 1, "b": 2})
    k2 = cache_key({"b": 2, "a": 1})
    assert k1 == k2


def test_lookup_miss_then_hit(tmp_path):
    from app.asset_cache import AssetCache, cache_key

    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 2048)
    cache = AssetCache(tmp_path / "cache", enabled=True)
    key = cache_key(_params())

    assert cache.lookup(key) is None, "首次应未命中"
    stored = cache.store(key, src)
    assert stored.exists() and stored.read_bytes() == src.read_bytes()

    hit = cache.lookup(key)
    assert hit is not None and hit.exists()
    assert hit.read_bytes() == src.read_bytes()


def test_disabled_cache_never_hits(tmp_path):
    from app.asset_cache import AssetCache, cache_key

    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 16)
    cache = AssetCache(tmp_path / "cache", enabled=False)
    key = cache_key(_params())
    cache.store(key, src)
    assert cache.lookup(key) is None, "缓存关闭时不得命中"


def test_lookup_self_heals_missing_file(tmp_path):
    from app.asset_cache import AssetCache, cache_key

    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 16)
    cache = AssetCache(tmp_path / "cache", enabled=True)
    key = cache_key(_params())
    stored = cache.store(key, src)
    stored.unlink()  # 人为删除产物
    assert cache.lookup(key) is None, "产物不存在应视为未命中"
    assert cache.stats()["entries"] == 0, "失效条目应从索引中清除"


def test_stats_counts(tmp_path):
    from app.asset_cache import AssetCache, cache_key

    cache = AssetCache(tmp_path / "cache", enabled=True)
    for i in range(3):
        f = tmp_path / f"s{i}.mp4"
        f.write_bytes(b"y" * 32)
        cache.store(cache_key(_params(seed=i)), f)
    st = cache.stats()
    assert st["entries"] == 3 and st["enabled"] is True


async def test_orchestrator_reuses_cache_on_second_run(tmp_path, monkeypatch):
    """第二次运行同一批场景：引擎生成次数应为 0（全部命中缓存）。"""
    from config.settings import Queue, Settings
    from engines.base import BaseEngine, ClipResult
    from pipeline.orchestrator import Orchestrator, SceneReq
    from quality import gate as qgate

    # 质量门只打桩探测层（无 ffmpeg 依赖），判定逻辑保持真实执行
    def _fake_probe(self, path):
        p = pathlib.Path(path)
        if not p.exists():
            return {"error": "不存在"}
        return {"format": {"duration": "5.0", "size": str(p.stat().st_size)},
                "streams": [{"codec_type": "video", "width": 1080, "height": 1920,
                             "avg_frame_rate": "24/1"}]}

    monkeypatch.setattr(qgate.QualityGate, "probe", _fake_probe, raising=True)
    monkeypatch.setattr(qgate.QualityGate, "count_frames", lambda self, p: 120, raising=True)

    calls = {"n": 0}

    class CountingEngine(BaseEngine):
        name = "counting"
        kind = "local"

        def __init__(self, out_dir):
            self.out_dir = pathlib.Path(out_dir)
            self.out_dir.mkdir(parents=True, exist_ok=True)

        def is_available(self):
            return True

        async def generate(self, req):
            calls["n"] += 1
            clip = self.out_dir / f"take_{calls['n']}.mp4"
            clip.write_bytes(b"\x00" * 20000)
            return ClipResult(video_path=clip, engine=self.name, seed=1, cost_usd=0.0)

    def _settings(cache: bool):
        s = Settings()
        s.queue = Queue(max_concurrency=1, budget_usd=5.0, resume=False,
                        cache_enabled=cache, cache_dir=str(tmp_path / "cache"))
        return s

    scenes = [SceneReq(id="s1", prompt="alpha", duration_seconds=3.0),
              SceneReq(id="s2", prompt="beta", duration_seconds=3.0)]

    # 第一次：缓存开启但为空 → 未命中，全部真实生成，并写入缓存
    orch1 = Orchestrator(_settings(True))
    orch1._build_engines = lambda: [CountingEngine(tmp_path / "a1")]
    m1 = await orch1.run_assets(scenes, output_dir=tmp_path / "run1")
    assert calls["n"] == 2, calls
    assert all(item.get("cached") is False for item in m1["scenes"]), m1["scenes"]

    # 第二次：同一 cache_dir → 全部命中，零生成
    calls["n"] = 0
    orch2 = Orchestrator(_settings(True))
    orch2._build_engines = lambda: [CountingEngine(tmp_path / "a2")]
    m2 = await orch2.run_assets(
        [SceneReq(id="s1", prompt="alpha", duration_seconds=3.0),
         SceneReq(id="s2", prompt="beta", duration_seconds=3.0)],
        output_dir=tmp_path / "run2",
    )
    assert calls["n"] == 0, f"第二次运行不应再调用引擎，实际 {calls['n']} 次"
    assert all(item["cached"] is True for item in m2["scenes"]), m2["scenes"]
