"""架构收敛第二阶段 · 第一批迁移的回归测试。

迁移内容：`scripts/main.py` 的两张数据表（`_CAMERA_PRESETS` / `_CAMERA_MAP_SIMPLE`）
与两个纯构建函数（`_build_series_filename` / `_build_camera_prompt`）→ `engines/prompts.py`。

本测试固定三件事：
1. **行为等价**：与迁移前捕获的黄金快照（tests/golden/prompts_baseline.json）逐字一致；
2. **确实搬走**：main.py 里不再有这些定义（防止"复制一份"的伪迁移）；
3. **调用面零改动**：main.py 仍以旧名别名使用（15 处调用点未改），且已 import engines。
"""
import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

GOLDEN = ROOT / "tests" / "golden" / "prompts_baseline.json"
MAIN = ROOT / "scripts" / "main.py"
MIGRATED = ("_CAMERA_PRESETS", "_CAMERA_MAP_SIMPLE", "_build_series_filename",
            "_build_camera_prompt")


def _golden() -> dict:
    assert GOLDEN.exists(), "缺少迁移黄金快照（应由 migrate_prompts_to_engines.py 流程生成）"
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_outputs_match_golden_snapshot():
    """迁移后的模块输出必须与迁移前 main.py 的输出逐字一致。

    命名里含当天日期（MMDD），所以快照必须**注入当时捕获的日期**：
    否则一到第二天就失败（2026-10-11 跨午夜时实测 1010→1011）。
    """
    from engines import prompts

    base = _golden()
    for cam, expected in base["camera_prompt"].items():
        assert prompts.build_camera_prompt(cam) == expected, f"运镜 {cam!r} 输出漂移"
    # 从黄金快照反推捕获日期，保证快照永久有效（其余部分仍逐字比对）
    frozen = base["series_filename"]["a"].rsplit("_", 1)[-1]
    assert frozen.isdigit() and len(frozen) == 4, f"快照日期段异常: {frozen!r}"
    assert prompts.build_series_filename("被辞退那天", "职场", 3,
                                        date_str=frozen) == base["series_filename"]["a"]
    assert prompts.build_series_filename("坏/标题:非法*字符?", "", 1,
                                        date_str=frozen) == base["series_filename"]["b"]
    assert prompts.build_series_filename("", "甜宠", 12,
                                        date_str=frozen) == base["series_filename"]["c"]
    assert sorted(prompts.CAMERA_PRESETS.keys()) == base["camera_presets_keys"]
    assert prompts.CAMERA_MAP_SIMPLE == base["camera_map_simple"]


def test_series_filename_defaults_to_today():
    """默认路径仍用当天日期（注入参数只服务于测试，不改变生产行为）。"""
    from datetime import datetime
    from engines import prompts

    got = prompts.build_series_filename("被辞退那天", "职场", 3)
    assert got.endswith("_" + datetime.now().strftime("%m%d"))


def test_symbols_no_longer_defined_in_main():
    """防伪迁移：main.py 里不能再有这些定义（只能有别名导入）。"""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    assigned = set()
    defined = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            assigned.add(node.targets[0].id)
        elif isinstance(node, ast.FunctionDef):
            defined.add(node.name)
    assert not (assigned & set(MIGRATED)), f"main.py 仍定义数据表: {assigned & set(MIGRATED)}"
    assert not (defined & set(MIGRATED)), f"main.py 仍定义函数: {defined & set(MIGRATED)}"


def test_main_imports_engines_layer_and_keeps_legacy_aliases():
    """main.py 必须从 engines 层导入（打破"完全不 import engines/"的历史状态），
    同时用旧名别名保持调用点零改动。"""
    src = MAIN.read_text(encoding="utf-8")
    assert "from engines.prompts import" in src, "main.py 未接入 engines 层"
    for old, new in (("_CAMERA_PRESETS", "CAMERA_PRESETS"),
                     ("_CAMERA_MAP_SIMPLE", "CAMERA_MAP_SIMPLE"),
                     ("_build_camera_prompt", "build_camera_prompt"),
                     ("_build_series_filename", "build_series_filename")):
        assert f"{new} as {old}" in src, f"缺少别名导入 {new} as {old}"


def test_call_sites_not_churned():
    """调用面零改动的证据：旧名在 main.py 中仍被大量使用。"""
    src = MAIN.read_text(encoding="utf-8")
    assert src.count("_CAMERA_PRESETS") >= 10, "预设表调用点数量异常（疑似漏改或误删）"
    assert src.count("_build_camera_prompt") >= 1
    assert src.count("_build_series_filename") >= 1


def test_migrated_functions_are_pure_no_io():
    """迁移目标是"纯构建、无 I/O"：源码里不应出现网络/子进程/文件写。"""
    src = (ROOT / "engines" / "prompts.py").read_text(encoding="utf-8")
    for bad in ("subprocess", "requests.", "urllib", "httpx", "open(", "socket"):
        assert bad not in src, f"迁移模块引入了 I/O 依赖: {bad}"
