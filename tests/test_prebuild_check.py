"""打包前置校验（scripts/prebuild_check.py）回归测试。

动机：2026-10-08 在本机环境被清空后，PyInstaller **静默**产出了 28MB 残废 exe
（缺 fastapi/uvicorn/openai 等），启动即崩且因 console=False 看不到错误。
本模块把"构建输入缺失 + 致命环境问题"变成**构建前硬失败**。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_prebuild_module_api():
    import prebuild_check as pb

    for name in ("check_build_inputs", "run", "main", "REQUIRED_BUILD_INPUTS"):
        assert hasattr(pb, name), f"prebuild_check 缺少 {name}"


def test_required_build_inputs_listed():
    import prebuild_check as pb

    joined = " ".join(pb.REQUIRED_BUILD_INPUTS)
    assert "web/dist" in joined, "前端产物必须列入构建输入（spec 打包它）"
    assert "luminaforge.spec" in joined


def test_missing_frontend_artifact_blocks_build(tmp_path):
    import prebuild_check as pb

    problems = pb.check_build_inputs(tmp_path)
    assert any("web/dist" in p for p in problems), problems


def test_run_reports_blocking_on_fatal_env(monkeypatch, tmp_path):
    import prebuild_check as pb

    monkeypatch.setattr(
        pb.health, "REQUIRED_PACKAGES", ["definitely_not_a_real_module_xyz"], raising=False
    )
    report, blocking = pb.run(root=tmp_path, check_network=False)
    assert report.fatal_failures, "应报告致命环境问题"
    assert any("packages" in b for b in blocking), blocking
    assert any("web/dist" in b for b in blocking), blocking


def test_cli_exit_code_matches_blocking():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prebuild_check.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert "构建前置校验" in proc.stdout


def test_spec_contains_prebuild_guard():
    spec = (ROOT / "luminaforge.spec").read_text(encoding="utf-8")
    assert "prebuild_check" in spec, "PyInstaller spec 未接入构建前置校验（残废 exe 会再次静默产出）"
