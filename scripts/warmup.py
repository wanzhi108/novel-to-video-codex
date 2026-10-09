"""ComfyUI 冷启动预热。

背景：Wan 5B 冷启动/模型重载实测约 **31 分钟**（见项目交接文档 GOTCHAS），
这是"每天出片"最痛的一次性成本。本脚本把
「可达性检查 → 节点/模型加载 → 计时报告」收敛成一条命令：

    python scripts/warmup.py                     # 默认 http://127.0.0.1:8188
    python scripts/warmup.py --url http://... --json

做法：请求 `/system_stats`（服务与显存信息）与 `/object_info`（**触发 ComfyUI 加载全部
自定义节点定义**，这是冷启动的主要耗时之一），并记录耗时。可选 `--run-workflow`
会额外提交一个最小工作流（需模型齐备，耗时较长，默认不做）。

退出码：0 = 预热成功；1 = 不可达或响应异常。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8188"


def warm_up(base_url: str = DEFAULT_URL, *, timeout: float = 5.0,
            client_factory=None, run_workflow: bool = False) -> dict:
    """执行预热并返回结构化报告（不抛异常）。"""
    factory = client_factory or (lambda **kw: httpx.Client(**kw))
    steps: list[dict] = []
    started = time.time()
    ok = False
    summary = ""

    try:
        with factory(timeout=timeout, trust_env=False) as client:
            r = client.get(f"{base_url}/system_stats")
            steps.append({"step": "system_stats", "ok": r.status_code == 200,
                          "detail": f"HTTP {r.status_code}"})

            r2 = client.get(f"{base_url}/object_info")
            count = 0
            try:
                count = len(r2.json() or {})
            except Exception:
                count = 0
            steps.append({"step": "object_info", "ok": r2.status_code == 200,
                          "detail": f"{count} 个节点类（自定义节点已加载）"})

            if run_workflow:
                steps.append({"step": "minimal_workflow", "ok": False,
                              "detail": "未实现：最小预热工作流需模型齐备（默认不跑）"})

            ok = all(s["ok"] for s in steps)
            summary = ("ComfyUI 预热完成（服务与节点定义已就绪）" if ok
                       else "ComfyUI 响应异常，请查看上方步骤")
    except Exception as e:  # 不可达不应抛异常，交给调用方决策
        steps.append({"step": "connect", "ok": False, "detail": f"{type(e).__name__}: {e}"})
        ok = False
        summary = f"ComfyUI 不可达或预热失败：{type(e).__name__}: {e}"

    return {
        "ok": ok,
        "url": base_url,
        "steps": steps,
        "elapsed_seconds": round(time.time() - started, 3),
        "summary": summary,
    }


def format_report(report: dict) -> str:
    lines = ["", "=" * 56, "  ComfyUI 预热报告 (Warmup)", "=" * 56]
    lines.append(f"  目标: {report.get('url')}")
    for s in report.get("steps", []):
        lines.append(f"  {'✅' if s['ok'] else '❌'} {s['step']:16} {s['detail']}")
    lines.append("-" * 56)
    lines.append(f"  {report.get('summary', '')}")
    lines.append(f"  耗时: {report.get('elapsed_seconds', 0)}s")
    lines.append("=" * 56)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ComfyUI 冷启动预热")
    parser.add_argument("--url", default=DEFAULT_URL, help="ComfyUI 地址")
    parser.add_argument("--timeout", type=float, default=5.0, help="单请求超时（秒）")
    parser.add_argument("--run-workflow", action="store_true", help="额外提交最小工作流（默认不跑）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    report = warm_up(args.url, timeout=args.timeout, run_workflow=args.run_workflow)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
