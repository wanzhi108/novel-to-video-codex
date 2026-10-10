"""架构收敛第二阶段 · 第一批：把 main.py 的纯构建函数与数据表迁到 engines/prompts.py。

做法（先取证、后搬迁、再验证）：
1. 用 ast 精确定位 4 个符号（2 张表 + 2 个纯函数）并取源码片段；
2. 生成 `engines/prompts.py`（表改名公开、函数改名公开）；
3. main.py 中删除原定义，改为一处 `from engines.prompts import ... as _旧名` 别名导入
   —— 15 处调用点零改动（这是"先收敛来源、不动调用面"的低风险迁移方式）；
4. 迁移前后用同一组固定输入对比输出，确保行为完全一致。

    python scripts/migrate_prompts_to_engines.py --check    # 只报计划
    python scripts/migrate_prompts_to_engines.py --apply     # 执行
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "scripts" / "main.py"
TARGET = ROOT / "engines" / "prompts.py"

TABLES = ("_CAMERA_PRESETS", "_CAMERA_MAP_SIMPLE")
FUNCS = ("_build_series_filename", "_build_camera_prompt")

HEADER = '''"""生成侧提示词与命名的纯构建逻辑（自 scripts/main.py 迁出）。

迁移背景：main.py 长期独自膨胀（>12000 行）且**完全不 import engines/**，
同一套生成逻辑在两代系统里各写一遍。本模块是"架构收敛第二阶段"的第一批迁移对象：
只搬**纯构建、无 I/O**的部分，行为按黄金快照逐字对齐（tests/test_prompts_migration.py）。

main.py 侧通过 `from engines.prompts import ... as _旧名` 别名导入，
因此 15 处 `_CAMERA_PRESETS` 调用点无需改动即可收敛到单一来源。
"""
from __future__ import annotations

'''


def _segments(src: str):
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: dict[str, tuple[str, int, int]] = {}
    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.FunctionDef):
            name = node.name
        if name in TABLES or name in FUNCS:
            seg = "".join(lines[node.lineno - 1:node.end_lineno])
            out[name] = (seg, node.lineno, node.end_lineno)
    return out


def _renamed(seg: str, old: str, new: str) -> str:
    if seg.startswith(old):
        return new + seg[len(old):]
    return seg.replace(old, new, 1)


def build_plan() -> dict:
    src = MAIN.read_text(encoding="utf-8")
    segs = _segments(src)
    missing = [n for n in (*TABLES, *FUNCS) if n not in segs]
    return {"segments": segs, "missing": missing}


def apply(dry: bool = False) -> dict:
    plan = build_plan()
    if plan["missing"]:
        raise SystemExit(f"未在 main.py 找到: {plan['missing']}")
    segs = plan["segments"]

    table_src = "\n\n".join(
        _renamed(segs[n][0].rstrip("\n"), n, n.lstrip("_")) for n in TABLES)
    func_src = "\n\n".join(
        _renamed(segs[n][0].rstrip("\n"), n, n.replace("_build_", "build_", 1))
        for n in FUNCS)
    func_src = (func_src
                .replace("_CAMERA_PRESETS", "CAMERA_PRESETS")
                .replace("_CAMERA_MAP_SIMPLE", "CAMERA_MAP_SIMPLE"))
    module = f"{HEADER}\n{table_src}\n\n\n{func_src}\n"

    if dry:
        return {"module_lines": len(module.splitlines()),
                "removed_lines": sum(e - s + 1 for _seg, s, e in segs.values()),
                "aliases": [f"{n.lstrip('_')} as {n}" for n in (*TABLES, *FUNCS)]}

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(module, encoding="utf-8")

    # main.py：删除 4 处定义（自下而上），并插入一处别名导入
    lines = MAIN.read_text(encoding="utf-8").splitlines(keepends=True)
    spans = sorted((s, e) for _seg, s, e in segs.values())
    insert_at = min(s for s, _e in spans) - 1
    alias_line = (
        "from engines.prompts import (  # noqa: E402  # 架构收敛第二阶段：迁出后保持旧名\n"
        "    CAMERA_MAP_SIMPLE as _CAMERA_MAP_SIMPLE,\n"
        "    CAMERA_PRESETS as _CAMERA_PRESETS,\n"
        "    build_camera_prompt as _build_camera_prompt,\n"
        "    build_series_filename as _build_series_filename,\n"
        ")\n"
    )
    for s, e in sorted(spans, reverse=True):
        del lines[s - 1:e]
    lines.insert(insert_at, alias_line)
    MAIN.write_text("".join(lines), encoding="utf-8")

    return {"module_lines": len(module.splitlines()),
            "removed_lines": sum(e - s + 1 for _seg, s, e in segs.values()),
            "main_lines_after": len(lines)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把 main.py 的纯构建逻辑迁到 engines/prompts.py")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    result = apply(dry=not args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
