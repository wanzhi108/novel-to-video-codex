"""P2 加固回归测试（先红后绿）。

覆盖：
① `/api/launcher-config` 请求体上限 + 字段白名单/类型校验 + 禁止写 api_key
② 内部异常文本不得经 HTTP 500 回传（静态门禁）
③ 未知非 API 路径返回 404，而 SPA 客户端路由仍回退 index.html
"""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import main as m  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402



# ── ① launcher-config 加固 ─────────────────────────────────
def test_launcher_config_rejects_oversize_json_body(monkeypatch, client):
    monkeypatch.setattr(m, "MAX_JSON_BODY_BYTES", 1024, raising=False)
    payload = json.dumps({"auto_cosyvoice": True, "junk": "A" * 8192}).encode()
    r = client.post(
        "/api/launcher-config", content=payload, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413, r.text


def test_launcher_config_rejects_unknown_field(client):
    r = client.post("/api/launcher-config", json={"evil_field": "x"})
    assert r.status_code == 400, r.text
    assert "evil_field" in r.text


def test_launcher_config_rejects_wrong_type(client):
    r = client.post("/api/launcher-config", json={"auto_cosyvoice": "yes"})
    assert r.status_code == 400, r.text


def test_launcher_config_refuses_api_key_write(client):
    r = client.post("/api/launcher-config", json={"api_key": "sk-evil-should-not-be-stored"})
    assert r.status_code == 400, r.text
    cfg = ROOT / "launcher_config.json"
    if cfg.exists():
        assert "sk-evil-should-not-be-stored" not in cfg.read_text(encoding="utf-8")


def test_launcher_config_accepts_known_field(client):
    r = client.post("/api/launcher-config", json={"auto_cosyvoice": True})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["auto_cosyvoice"] is True


# ── ② 内部异常文本不外泄 ───────────────────────────────────
def test_no_internal_exception_text_in_http_500():
    src = (ROOT / "scripts" / "main.py").read_text(encoding="utf-8")
    leaks = re.findall(r'HTTPException\(500,\s*f"[^"]*\{(?:e|str\(e\))[^"]*"', src)
    assert not leaks, f"仍有 {len(leaks)} 处 500 回传内部异常文本：{leaks[:3]}"


# ── ③ 404 语义 ─────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/config/settings.py", "/scripts/main.py", "/nope.json", "/api/nope"])
def test_unknown_asset_or_api_path_returns_404(path, client):
    r = client.get(path)
    assert r.status_code == 404, f"{path} -> {r.status_code}"


def test_spa_client_route_still_served(client):
    r = client.get("/some/client/route")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")
