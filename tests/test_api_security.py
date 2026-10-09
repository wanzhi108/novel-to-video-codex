"""接口安全回归测试 —— 覆盖本轮 P0 修复。

1) 服务绑定：不得再出现 `host="0.0.0.0"`，docker 端口必须显式绑回环
2) 媒体文件响应：必须做路径包含性校验（防任意文件读取）
3) 导出接口：必须对 API Key 脱敏
"""
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import main as m  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402



def _multipart(obj, filename="job.json"):
    b = uuid.uuid4().hex
    body = (
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode()
        + json.dumps(obj).encode()
        + f"\r\n--{b}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={b}"


# ── 1) 绑定 ────────────────────────────────────────────────
def test_no_wildcard_bind_in_sources():
    for rel in ("scripts/main.py", "scripts/launcher.py", "cosyvoice2/server.py"):
        p = ROOT / rel
        if not p.exists():
            continue
        bad = [
            ln for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
            if 'host="0.0.0.0"' in ln or "host='0.0.0.0'" in ln
        ]
        assert not bad, f"{rel} 仍绑定 0.0.0.0: {bad}"


def test_docker_ports_bound_to_loopback():
    p = ROOT / "docker-compose.yml"
    if not p.exists():
        pytest.skip("no docker-compose.yml")
    for mapping in re.findall(r'-\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="ignore")):
        if ":" in mapping:
            assert mapping.startswith("127.0.0.1:"), f"docker 端口未绑定回环: {mapping}"


# ── 2) 路径包含性 ──────────────────────────────────────────
def test_safe_media_path_blocks_outside():
    with pytest.raises(HTTPException) as e:
        m.safe_media_path(r"C:\Windows\win.ini")
    assert e.value.status_code == 403


def test_safe_media_path_allows_output_dir():
    f = m.OUTPUT_DIR / "_sec_test_ok.txt"
    f.write_text("ok", encoding="utf-8")
    try:
        assert m.safe_media_path(str(f)).exists()
    finally:
        f.unlink(missing_ok=True)


def test_scene_image_rejects_path_outside_output(client):
    jid = "sectest01"
    job = m.JobState(id=jid)
    job.scenes = [m.Scene(id=1, image_path=r"C:\Windows\win.ini")]
    m.jobs[jid] = job
    try:
        r = client.get(f"/api/scene-image/{jid}/1")
        assert r.status_code == 403, r.text
    finally:
        m.jobs.pop(jid, None)


def test_tts_preview_rejects_prefix_sibling(client):
    p = m.OUTPUT_DIR / "_tts_preview_EVIL" / "a.mp3"
    r = client.get("/api/tts-preview-audio", params={"path": str(p)})
    assert r.status_code == 403, r.text


# ── 3) 导入校验 + 导出脱敏 ─────────────────────────────────
def test_import_rejects_illegal_job_id(client):
    body, ctype = _multipart({"id": "..\\_dsh_decoy", "novel_text": "x"})
    r = client.post("/api/jobs/import", content=body, headers={"Content-Type": ctype})
    assert r.status_code == 400, r.text


def test_import_sanitizes_absolute_media_paths(client):
    jid = "sectestimp"
    body, ctype = _multipart({
        "id": jid, "novel_text": "x", "novel_title": "t",
        "scenes": [{"id": 1, "image_path": r"C:\Windows\win.ini",
                    "video_path": r"..\..\secret.mp4"}],
    })
    try:
        r = client.post("/api/jobs/import", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 200, r.text
        sc = m.jobs[jid].scenes[0]
        assert sc.image_path is None and sc.video_path is None
    finally:
        client.delete(f"/api/job/{jid}")
        m.jobs.pop(jid, None)


def test_export_redacts_api_key(client):
    jid = "sectestexp"
    body, ctype = _multipart({
        "id": jid, "novel_text": "x", "novel_title": "t",
        "deepseek_key": "sk-test-leak-1234567890",
    })
    try:
        r = client.post("/api/jobs/import", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 200, r.text
        r2 = client.get(f"/api/jobs/{jid}/export")
        assert r2.status_code == 200, r2.text
        assert "sk-test-leak-1234567890" not in r2.text
        assert r2.json()["job"].get("deepseek_key", "") == ""
    finally:
        client.delete(f"/api/job/{jid}")
        m.jobs.pop(jid, None)


# ── 4) P1：CSRF / Host 校验 ─────────────────────────────────
def test_trusted_host_and_origin_rules():
    assert m.host_is_trusted("127.0.0.1:8190") is True
    assert m.host_is_trusted("localhost:8190") is True
    assert m.host_is_trusted("192.168.1.102:8190") is True   # 私有 IP 字面量（局域网自建）
    assert m.host_is_trusted("evil.example.com") is False    # 域名 → 防 DNS rebinding
    assert m.origin_is_trusted("http://127.0.0.1:8190") is True
    assert m.origin_is_trusted("null") is True               # file:// 页面交由 Host 判定
    assert m.origin_is_trusted("http://evil.example.com") is False


def test_cross_origin_post_blocked(client):
    r = client.post(
        "/api/create-job", content=b"",
        headers={"Origin": "http://evil.example.com", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403, r.text
    assert "CSRF" in r.text


def test_same_origin_post_allowed(client):
    r = client.post("/api/create-job", content=b"", headers={"Origin": "http://127.0.0.1:8190"})
    assert r.status_code == 200, r.text
    m.jobs.pop(r.json()["job_id"], None)


def test_websocket_rejects_cross_origin(client):
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws/progress/wssec", headers={"Origin": "http://evil.example.com"}
        ) as ws:
            ws.send_text("x")


def test_websocket_allows_same_origin(client):
    # Starlette 的 WS 测试客户端默认发 Host: testserver，这里显式给出真实 Host
    with client.websocket_connect(
        "/ws/progress/wssec2",
        headers={"Origin": "http://127.0.0.1:8190", "Host": "127.0.0.1:8190"},
    ) as ws:
        ws.send_text("ping")


# ── 5) P1：上传限额与文件名清洗 ─────────────────────────────
def test_upload_over_limit_returns_413(monkeypatch, client):
    from app import security as _sec  # 限值已下沉到 app.security
    monkeypatch.setattr(_sec, "MAX_UPLOAD_BYTES", 1024)
    monkeypatch.setattr(_sec, "MAX_UPLOAD_MB", 0)
    body, ctype = _multipart({"id": "sectestbig", "novel_text": "x"})
    body = body.replace(b'"x"', b'"' + b"y" * 4096 + b'"')
    r = client.post("/api/jobs/import", content=body, headers={"Content-Type": ctype})
    assert r.status_code == 413, r.text


def test_upload_filename_traversal_neutralized():
    assert m.safe_upload_name("..\\..\\evil.png") == "evil.png"
    assert m.safe_upload_name("../../evil.mp3") == "evil.mp3"
    assert m.safe_upload_name("") == "upload.bin"
    assert m.safe_upload_name(None) == "upload.bin"
