"""依赖钉版门禁：requirements.txt 不允许浮动版本，且必须提供 lock 快照。

动机（2026-10-08 实测事故）：本机 Python 环境被清空 + pip 无网络时，
浮动依赖让"同一份代码"构建出 28MB 的残废 exe —— 依赖不可复现 = 交付不可复现。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _entries(path: pathlib.Path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            yield line


def test_requirements_are_exactly_pinned():
    floating = []
    for line in _entries(ROOT / "requirements.txt"):
        pkg = line.split(";", 1)[0].strip()
        if "==" not in pkg:
            floating.append(line)
    assert not floating, "requirements.txt 存在未钉版依赖（禁止 >= / 无版本）：\n  " + "\n  ".join(floating)


def test_requirements_lock_snapshot_exists():
    lock = ROOT / "requirements.lock"
    assert lock.exists(), "缺少 requirements.lock（环境快照），无法复现构建"
    lines = [l for l in _entries(lock)]
    assert len(lines) >= 8, f"requirements.lock 内容过少（{len(lines)} 行），疑似未生成"
    assert any("==" in l for l in lines), "requirements.lock 未包含钉版条目"
    assert re.search(r"fastapi==", lock.read_text(encoding="utf-8")), "lock 中缺少核心依赖 fastapi"


def test_requirements_dev_are_pinned():
    dev = ROOT / "requirements-dev.txt"
    if not dev.exists():
        return
    floating = [l for l in _entries(dev) if "==" not in l.split(";", 1)[0]]
    # 允许"受控区间"仅在显式标注的行（本项目用 == 或 >=x,<y 的封闭区间）
    bad = [l for l in floating if not re.search(r">=\s*[\d.]+\s*,\s*<\s*[\d.]+", l)]
    assert not bad, "requirements-dev.txt 存在开放区间依赖：\n  " + "\n  ".join(bad)
