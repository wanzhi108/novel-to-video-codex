"""环境自检（app/health.py）回归测试。

目标：把"缺包/缺 ffmpeg/ComfyUI 不可达/无模型/目录不可写"这类问题
在启动阶段结构化暴露，而不是运行到一半才炸。
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_health_module_exposes_api():
    from app import health

    for name in ("check_environment", "format_report", "exit_code", "Check", "Report", "REQUIRED_PACKAGES"):
        assert hasattr(health, name), f"app.health 缺少 {name}"


def test_environment_report_shape(monkeypatch, tmp_path):
    from app import health

    report = health.check_environment(output_dir=tmp_path, check_network=False)
    assert isinstance(report, health.Report)
    assert report.checks, "自检没有任何检查项"
    names = {c.name for c in report.checks}
    for expected in ("python", "packages", "ffmpeg", "output_dir"):
        assert expected in names, f"缺少检查项 {expected}"
    for c in report.checks:
        assert c.level in ("fatal", "warn", "info"), c
        assert isinstance(c.ok, bool) and c.detail


def test_missing_core_package_is_fatal(monkeypatch, tmp_path):
    from app import health

    monkeypatch.setattr(health, "REQUIRED_PACKAGES", ["definitely_not_a_real_module_xyz"], raising=False)
    report = health.check_environment(output_dir=tmp_path, check_network=False)
    pkg = next(c for c in report.checks if c.name == "packages")
    assert pkg.ok is False and pkg.level == "fatal"
    assert health.exit_code(report) == 1, "致命项缺失时退出码应为 1"


def test_optional_missing_package_is_warning(monkeypatch, tmp_path):
    from app import health

    monkeypatch.setattr(health, "OPTIONAL_PACKAGES", ["definitely_not_a_real_module_xyz"], raising=False)
    report = health.check_environment(output_dir=tmp_path, check_network=False)
    opt = next(c for c in report.checks if c.name == "optional_packages")
    assert opt.ok is False and opt.level == "warn"
    assert health.exit_code(report) == 0, "仅警告不应导致非零退出码"


def test_report_is_human_readable(tmp_path):
    from app import health

    text = health.format_report(health.check_environment(output_dir=tmp_path, check_network=False))
    assert "python" in text.lower()
    assert "✅" in text or "❌" in text or "[" in text


def test_cli_runs_and_prints_report():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_env.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode in (0, 1), f"CLI 异常退出：{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "环境自检" in proc.stdout or "Environment" in proc.stdout
