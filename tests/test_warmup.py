"""ComfyUI 冷启动预热（scripts/warmup.py）回归测试。

背景：Wan 5B 冷启动/重载模型实测约 31 分钟，是"每天出片"最痛的一次性成本。
预热脚本负责把"可达性检查 → 节点/模型加载 → 计时报告"做成一条命令。
本测试全程不依赖真实 ComfyUI（用注入的假客户端）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """记录请求路径的假 httpx.Client。"""

    def __init__(self, *a, **kw):
        self.calls: list[str] = []
        self.fail = kw.pop("fail", False)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        self.calls.append(url)
        if self.fail:
            raise ConnectionError("模拟不可达")
        if url.endswith("/system_stats"):
            return _FakeResponse(200, {"system": {"comfyui_version": "test"}})
        return _FakeResponse(200, {"KSampler": {}})


def test_warmup_module_api():
    import warmup

    for name in ("warm_up", "format_report", "main"):
        assert hasattr(warmup, name), f"warmup 缺少 {name}"


def test_warmup_unreachable_reports_failure():
    from warmup import warm_up

    report = warm_up(base_url="http://127.0.0.1:59999", client_factory=lambda **kw: _FakeClient(fail=True))
    assert report["ok"] is False
    assert "不可达" in report["summary"] or "失败" in report["summary"]
    assert report["steps"], "应记录尝试过的步骤"


def test_warmup_success_touches_stats_and_object_info():
    from warmup import format_report, warm_up

    fake = _FakeClient()
    report = warm_up(base_url="http://127.0.0.1:8188", client_factory=lambda **kw: fake)
    assert report["ok"] is True
    assert any("system_stats" in u for u in fake.calls), fake.calls
    assert any("object_info" in u for u in fake.calls), fake.calls
    assert report["elapsed_seconds"] >= 0
    assert "预热" in format_report(report)


def test_warmup_cli_exit_code_and_output():
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "warmup.py"), "--url", "http://127.0.0.1:59999",
         "--timeout", "1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert "预热" in proc.stdout
