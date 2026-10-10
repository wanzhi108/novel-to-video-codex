# -*- coding: utf-8 -*-
"""把 NovelForge 交接包导入本仓库出片工作目录（D 轴 D3）。

用法：
    python scripts/import_novelforge.py <给视频管线.json> [--out DIR] [--json]

典型流程（两个项目衔接）：
    1) NovelForge 打包产出 → 得到 `输出/给视频管线.json`
    2) 本命令导入 → 目录里出现 novel.txt / characters.json / scenes_seed.json / style_anchor.txt
    3) 用 novel.txt 跑分镜：`pipeline/storyboard.generate_storyboard(novel_text)`
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import novelforge_handoff as nfh  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导入 NovelForge 交接包（给视频管线.json）")
    ap.add_argument("handoff", help="NovelForge 导出的 给视频管线.json 路径")
    ap.add_argument("--out", default="", help="输出目录（默认 <交接包所在目录>/novelforge_import）")
    ap.add_argument("--json", action="store_true", help="以 JSON 打印结果")
    args = ap.parse_args(argv)

    src = Path(args.handoff)
    out = Path(args.out) if args.out else (src.parent / "novelforge_import")
    try:
        data = nfh.load(src)
        result = nfh.import_to_workspace(data, out)
    except nfh.HandoffError as e:
        print(f"✗ 交接包不可用: {e}")
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("NovelForge → LuminaForge 交接导入")
        print("=" * 58)
        print(f"  来源: {src}")
        print(f"  内容: {result['summary']}")
        print(f"  落盘: {result['dir']}")
        for f in result["written"]:
            print(f"    · {f}")
        print("-" * 58)
        print("  下一步: 用 novel.txt 生成分镜（pipeline/storyboard.generate_storyboard）")
        print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
