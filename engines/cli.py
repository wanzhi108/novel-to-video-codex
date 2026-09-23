"""云端引擎 CLI 诊断入口。

用法：
    python -m engines.cli status          # 所有 provider 可用性 + 修复指引
    python -m engines.cli check <provider> # 单 provider 详细状态
"""
from __future__ import annotations

import argparse
import json
import sys


def cmd_status(args) -> int:
    from .cloud import CloudEngine, _PROVIDERS

    engine = CloudEngine(prefer=args.prefer)
    report = engine.status_report()
    print("=" * 70)
    print("CloudEngine provider 状态报告")
    print("=" * 70)
    ready = []
    for name, info in report.items():
        mark = "✅" if info["status"] == "AVAILABLE" else "❌"
        print(f"{mark} {name:<16} [{info['status']}] (优先级 {info['priority']})")
        print(f"     {info['note']}")
        if info["status"] != "AVAILABLE":
            spec = _PROVIDERS[name]
            print(f"     需要 key: {' / '.join(spec['env_keys'])}（填入 OpenMontage/.env）")
        else:
            ready.append(name)
    print("-" * 70)
    if ready:
        print(f"可用 provider: {', '.join(ready)}")
    else:
        print("当前没有任何云端 provider 可用（key 为空）。")
        print("把真实 key 填入 D:\\novel-to-video-codex\\OpenMontage\\.env 后重跑本命令。")
    return 0


def cmd_check(args) -> int:
    from .cloud import CloudEngine, _PROVIDERS

    if args.provider not in _PROVIDERS:
        print(f"未知 provider: {args.provider}；可选: {', '.join(_PROVIDERS)}")
        return 2
    engine = CloudEngine(prefer=args.provider)
    print(json.dumps({args.provider: engine.status_report()[args.provider]}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="engines 云端引擎诊断")
    sub = parser.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="所有 provider 状态")
    p_status.add_argument("--prefer", default=None, help="优先 provider 名称")
    p_check = sub.add_parser("check", help="单 provider 状态")
    p_check.add_argument("provider", help="provider 名称")
    args = parser.parse_args()
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "check":
        return cmd_check(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
