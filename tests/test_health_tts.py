"""配音引擎自检（environments 体检里的 tts_engines 项）。

配音决定成片听感，用户需要一眼看到当前在哪一档：
edge-tts（通用音色）/ Kokoro / CosyVoice2 服务（音色克隆 + 情绪控制）。
"""
import pathlib
import socket
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import health  # noqa: E402


def test_tts_check_is_part_of_report(tmp_path):
    report = health.check_environment(output_dir=tmp_path, check_network=False)
    names = {c.name for c in report.checks}
    assert "tts_engines" in names, f"环境体检缺少配音引擎检查: {sorted(names)}"
    c = next(c for c in report.checks if c.name == "tts_engines")
    assert "edge-tts" in c.detail


def test_missing_edge_tts_is_fatal(monkeypatch):
    monkeypatch.setattr(health, "_has_module", lambda m: False)
    c = health._check_tts_engines(check_network=False)
    assert c.ok is False and c.level == "fatal", "缺 edge-tts 应视为致命（配音不可用）"


def test_kokoro_only_is_warning(monkeypatch):
    monkeypatch.setattr(health, "_has_module", lambda m: m == "edge_tts")
    c = health._check_tts_engines(check_network=False)
    assert c.ok is True and c.level == "warn"
    assert "kokoro ✗" in c.detail


def test_cosyvoice_service_readiness_detected(monkeypatch):
    """真起一个监听端口，验证 :50000 就绪探测确实有效。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        monkeypatch.setattr(health, "_has_module", lambda m: True)
        c = health._check_tts_engines(check_network=True, port=port, timeout=1.0)
        assert "✓ 就绪" in c.detail, c.detail
    finally:
        srv.close()


def test_cosyvoice_not_probed_when_offline_mode(monkeypatch):
    monkeypatch.setattr(health, "_has_module", lambda m: True)
    c = health._check_tts_engines(check_network=False)
    assert "未探测" in c.detail, "离线模式不应发起端口探测"
