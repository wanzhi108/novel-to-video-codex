"""打包前置校验 —— 在 PyInstaller 构建前跑，缺核心依赖或前端产物即**硬失败**。

背景（2026-10-08 实测事故）：本机 Python 环境被清空且 pip 无网络时，
PyInstaller 仍"成功"产出一个 28MB 的残废 exe（缺 fastapi/uvicorn/openai 等），
启动即崩溃，且因 console=False 看不到任何报错 —— 直到手动检索二进制才发现。

因此把"构建输入齐全 + 环境致命项为零"变成构建的**前置条件**：
- `luminaforge.spec` 顶部会调用本脚本，返回码非 0 直接中止构建；
- 也可手动执行：`python scripts/prebuild_check.py`。

退出码：0 = 可构建；1 = 存在阻断项。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import health  # noqa: E402

# 构建必需的输入产物（缺失会导致 exe 打包出不完整/不可用）
REQUIRED_BUILD_INPUTS = [
    "web/dist/index.html",   # 前端构建产物（spec 打包 web/dist；缺失会打出无界面 exe）
    "luminaforge.spec",      # 构建配置自身
    "settings.yaml",         # 运行时默认配置模板
    ".env.example",          # 环境变量模板
]


def check_build_inputs(root: Path = ROOT) -> list[str]:
    """返回缺失的构建输入说明列表（空列表 = 齐全）。"""
    problems = []
    for rel in REQUIRED_BUILD_INPUTS:
        if not (Path(root) / rel).exists():
            problems.append(f"缺少构建输入: {rel}")
    return problems


def run(root: Path = ROOT, *, check_network: bool = False):
    """执行环境自检 + 构建输入检查，返回 (report, blocking)。"""
    report = health.check_environment(output_dir=Path(root) / "output", check_network=check_network)
    blocking = [f"致命环境问题: {c.name} —— {c.detail}" for c in report.fatal_failures]
    blocking += check_build_inputs(root)
    return report, blocking


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LuminaForge 打包前置校验")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--network", action="store_true", help="同时探测 ComfyUI（默认不探测）")
    parser.add_argument("--root", default=str(ROOT), help="项目根目录")
    args = parser.parse_args(argv)

    report, blocking = None, []
    try:
        report, blocking = run(Path(args.root), check_network=args.network)
    except Exception as exc:  # 自检脚本自身失败也必须阻断构建
        blocking = [f"前置校验无法执行: {type(exc).__name__}: {exc}"]

    if args.json:
        print(json.dumps(
            {
                "ok": not blocking,
                "blocking": blocking,
                "checks": [c.__dict__ for c in report.checks] if report else [],
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(health.format_report(report) if report else "[PreBuild] 环境自检未能执行")
        if blocking:
            print("\n[PreBuild] ❌ 构建前置校验失败，阻断以下问题：")
            for b in blocking:
                print(f"  - {b}")
            print("\n  修复建议：pip install -r requirements.txt；若缺 web/dist，"
                  "在 web/ 下执行 npm ci && npm run build 后重试。")
        else:
            print("\n[PreBuild] ✅ 构建前置校验通过（构建输入齐全、无致命环境问题）")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
