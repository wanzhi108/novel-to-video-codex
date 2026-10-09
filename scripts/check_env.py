"""环境自检 CLI。

用法：
    python scripts/check_env.py            # 人类可读报告（有致命项时退出码 1）
    python scripts/check_env.py --json     # 机器可读
    python scripts/check_env.py --no-network  # 跳过 ComfyUI 探测（离线/CI）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import health  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LuminaForge 环境自检")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--no-network", action="store_true", help="跳过网络探测（离线/CI）")
    args = parser.parse_args(argv)

    report = health.check_environment(check_network=not args.no_network)

    if args.json:
        payload = {
            "ok": report.ok,
            "checks": [c.__dict__ for c in report.checks],
            "fatal_failures": [c.name for c in report.fatal_failures],
            "warnings": [c.name for c in report.warnings],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(health.format_report(report))

    return health.exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
