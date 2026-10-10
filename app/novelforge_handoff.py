# -*- coding: utf-8 -*-
"""NovelForge 交接包读取（D 轴 D3）——上游小说生成 → 本仓库出片。

## 为什么放在 app/ 而不是塞进 main.py
本仓库的 `scripts/main.py` 已经 1.1 万行；衔接逻辑必须**零项目内依赖、可单测**，
否则又是一段没人敢动的胶水。这里只做三件事：校验、映射、落盘。

## 契约来源
上游 NovelForge 的 `handoff_export.py`（schema `novelforge.handoff/1`）导出：
- `novel_text`  ← 直接喂本仓库 `pipeline/storyboard.generate_storyboard(novel_text, ...)`
- `characters`  ← 字段名与 `app/models.py::Character` 对齐（name/gender/age_range/role_type/
  personality/appearance/body_type/clothing），可**零映射**构造 Character
- `style_anchor` ← 出图风格约束（本仓库最怕人物/场景前后不一致）
- `scenes_seed`  ← 段落级场景候选（对话/叙述 + 章号），供分镜参考边界
校验失败必须**明确报错**，不允许"半懂不懂地吃掉"上游数据。
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PREFIX = "novelforge.handoff/"
SUPPORTED_VERSIONS = (1,)

# 与 app/models.py::Character 完全一致的字段（多出来的键会被丢弃，避免构造报错）
CHARACTER_FIELDS = ("name", "gender", "age_range", "personality", "role_type",
                    "appearance", "body_type", "clothing")


class HandoffError(ValueError):
    """交接包不合法（信息要能直接告诉用户怎么修）。"""


def parse_schema(schema: str) -> int:
    """从 `novelforge.handoff/1` 里取出版本号；格式不对就报错。"""
    s = (schema or "").strip()
    if not s.startswith(SCHEMA_PREFIX):
        raise HandoffError(f"不是 NovelForge 交接包：schema={schema!r}（应以 {SCHEMA_PREFIX} 开头）")
    tail = s[len(SCHEMA_PREFIX):].strip()
    if not tail.isdigit():
        raise HandoffError(f"schema 版本号无法解析：{schema!r}")
    return int(tail)


def validate(data: dict) -> dict:
    """校验交接包（返回原数据，便于链式调用）。"""
    if not isinstance(data, dict):
        raise HandoffError("交接包必须是 JSON 对象")
    ver = parse_schema(data.get("schema", ""))
    if ver not in SUPPORTED_VERSIONS:
        raise HandoffError(f"交接包版本 {ver} 不受支持（本仓库支持 {list(SUPPORTED_VERSIONS)}）")
    text = data.get("novel_text")
    if not isinstance(text, str) or not text.strip():
        raise HandoffError("交接包缺少正文：novel_text 为空（无法生成分镜）")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise HandoffError("交接包缺少章节列表 chapters")
    for i, c in enumerate(chapters):
        if not isinstance(c, dict) or "num" not in c:
            raise HandoffError(f"第 {i + 1} 个章节条目缺少 num 字段")
    if not isinstance(data.get("characters", []), list):
        raise HandoffError("characters 必须是数组")
    return data


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise HandoffError(f"交接包不存在: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HandoffError(f"交接包不是合法 JSON: {e}") from e
    return validate(data)


def to_characters(data: dict) -> list[dict]:
    """映射成本仓库 `app/models.py::Character` 可**零改动**构造的字典。"""
    out = []
    for c in data.get("characters", []):
        if not isinstance(c, dict) or not (c.get("name") or "").strip():
            continue
        out.append({k: (c.get(k) or "") for k in CHARACTER_FIELDS})
    return out


def to_storyboard_input(data: dict) -> dict:
    """组装本仓库生成分镜所需输入（`generate_storyboard` 吃 novel_text）。"""
    book = data.get("book") or {}
    return {
        "novel_text": data["novel_text"],
        "style_anchor": (data.get("style_anchor") or "").strip(),
        "characters": to_characters(data),
        "title": book.get("title") or "",
        "genre": book.get("genre") or "",
        "chapters": len(data.get("chapters") or []),
        "words": book.get("words") or len(data["novel_text"]),
        "scenes_seed": data.get("scenes_seed") or [],
        "source": data.get("source") or {},
    }


def summary(data: dict) -> str:
    """一行摘要（CLI 打印用）。"""
    book = data.get("book") or {}
    src = data.get("source") or {}
    return (f"《{book.get('title') or '未命名'}》/ {book.get('author') or '未署名'} · "
            f"{len(data.get('chapters') or [])} 章 · {len(data.get('novel_text') or ''):,} 字 · "
            f"人物 {len(to_characters(data))} · 场景候选 {len(data.get('scenes_seed') or [])} · "
            f"来自 {src.get('app', 'NovelForge')} v{src.get('version', '?')}")


def import_to_workspace(data: dict, dest_dir: str | Path,
                        filename: str = "novel.txt") -> dict:
    """落盘成出片工作目录可用的文件。

    产出：
    - `novel.txt`        —— 分镜生成直接读的全文（`generate_storyboard`）
    - `characters.json`  —— 与 `app/models.py::Character` 同字段的人物表
    - `scenes_seed.json` —— 段落级场景候选（分镜边界参考）
    - `handoff.json`     —— 交接包原样副本（可追溯来源版本）
    - `style_anchor.txt` —— 出现风格锚点（有才写）
    """
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    plan = to_storyboard_input(data)

    (d / filename).write_text(plan["novel_text"], encoding="utf-8")
    (d / "characters.json").write_text(
        json.dumps(plan["characters"], ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "scenes_seed.json").write_text(
        json.dumps(plan["scenes_seed"], ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "handoff.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    written = [filename, "characters.json", "scenes_seed.json", "handoff.json"]
    if plan["style_anchor"]:
        (d / "style_anchor.txt").write_text(plan["style_anchor"], encoding="utf-8")
        written.append("style_anchor.txt")

    return {"dir": str(d), "written": written, "summary": summary(data),
            "next": f"python pipeline/cli.py ... 或调用 generate_storyboard(读取 {d / filename})"}
