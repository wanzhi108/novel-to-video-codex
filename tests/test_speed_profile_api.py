"""速度档位（预览 / 资产缓存）在 API 与配置层的贯通测试。

目标：让"预览档 + 资产缓存"能一键开关（API / launcher 配置），而不是只能手改 yaml。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_speed_profile_endpoint_reports_state(client, app_module):
    r = client.get("/api/speed-profile")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("preview", "cache_enabled", "preview_gain", "cache_stats"):
        assert key in body, f"缺少字段 {key}: {body}"
    assert isinstance(body["preview"], bool)
    assert body["preview_gain"]["est_time_ratio"] < 1.0
    assert "entries" in body["cache_stats"]


def test_launcher_config_accepts_speed_toggles(client):
    r = client.post("/api/launcher-config", json={"preview": True, "cache_enabled": True})
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["preview"] is True and cfg["cache_enabled"] is True
    # 落盘校验
    disk = json.loads((ROOT / "launcher_config.json").read_text(encoding="utf-8"))
    assert disk["preview"] is True and disk["cache_enabled"] is True
    # 复位，避免影响其它测试/后续运行
    client.post("/api/launcher-config", json={"preview": False, "cache_enabled": False})


def test_launcher_config_rejects_wrong_speed_toggle_type(client):
    r = client.post("/api/launcher-config", json={"preview": "yes"})
    assert r.status_code == 400, r.text


def test_settings_read_env_overrides(monkeypatch):
    """launcher 通过环境变量把速度档位传给服务进程。"""
    monkeypatch.setenv("NOVEL2VID_PREVIEW", "true")
    monkeypatch.setenv("NOVEL2VID_ASSET_CACHE", "1")
    import importlib
    import config.settings as cs

    importlib.reload(cs)
    s = cs.load_settings() if hasattr(cs, "load_settings") else None
    local = cs.EngineLocal()
    assert local.preview is True, "环境变量 NOVEL2VID_PREVIEW 应打开预览档"
    if s is not None:
        assert s.engines.local.preview is True
    # 还原模块默认（避免污染后续测试）
    monkeypatch.delenv("NOVEL2VID_PREVIEW", raising=False)
    monkeypatch.delenv("NOVEL2VID_ASSET_CACHE", raising=False)
    importlib.reload(cs)


def test_launcher_exports_speed_toggles_to_env():
    """launcher 必须把 launcher_config.json 的开关导出为环境变量，否则管道读不到。"""
    src = (ROOT / "scripts" / "launcher.py").read_text(encoding="utf-8")
    assert "NOVEL2VID_PREVIEW" in src, "launcher 未导出预览档开关"
    assert "NOVEL2VID_ASSET_CACHE" in src, "launcher 未导出资产缓存开关"
    assert "launcher_config.json" in src, "launcher 未读取 launcher_config.json"


def test_speed_profile_documented_in_settings_yaml():
    text = (ROOT / "settings.yaml").read_text(encoding="utf-8")
    assert "preview" in text and "cache_enabled" in text
