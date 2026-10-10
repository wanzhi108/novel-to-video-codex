# -*- coding: utf-8 -*-
"""NovelForge 交接包消费测试（D 轴 D3 · LuminaForge 侧）。

盯住：
1. **校验必须严格**（版本/缺正文/缺章节/坏 JSON 都要给出可操作的错误，而不是半懂不懂地吃掉）；
2. **字段零映射**：上游 characters 的键名与 `app/models.py::Character` 一致，能直接构造；
3. **落盘产物可直接用于出片**：novel.txt 喂 generate_storyboard，characters.json 喂选角；
4. **真机往返**：如果本机存在 NovelForge 仓库，就用它的 handoff_export 造包再吃掉——
   这才叫"衔接验证"，而不是两边各自 mock。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import novelforge_handoff as nfh  # noqa: E402
from app.models import Character  # noqa: E402

NOVELFORGE = Path(r"D:\projects\NovelForge")


def _handoff(**over):
    base = {
        "schema": "novelforge.handoff/1",
        "generated_at": "2026-10-11T01:00:00",
        "source": {"app": "NovelForge", "version": "10.1.0", "build_date": "2026-10-11"},
        "book": {"title": "雨夜将至", "author": "张三", "genre": "都市",
                 "chapters": 1, "words": 120},
        "style_anchor": "青灰色调，冷峻短句",
        "characters": [
            {"name": "林澈", "gender": "男", "age_range": "青年", "role_type": "主角",
             "personality": "隐忍", "appearance": "瘦高，眼下有青影", "body_type": "",
             "clothing": "深色外套", "mentions": 12},
        ],
        "chapters": [{"num": 1, "title": "雨夜", "heading": "第1章 雨夜", "words": 120,
                      "text": "夜里十一点，写字楼的灯还亮着。"}],
        "scenes_seed": [{"id": "c001-s001", "chapter": 1, "chapter_title": "雨夜",
                         "index": 0, "kind": "narration", "text": "夜里十一点。"}],
        "novel_text": "第1章 雨夜\n\n夜里十一点，写字楼的灯还亮着。",
    }
    base.update(over)
    return base


# ───────── 校验 ─────────

def test_parse_schema():
    assert nfh.parse_schema("novelforge.handoff/1") == 1
    with pytest.raises(nfh.HandoffError):
        nfh.parse_schema("luminaforge.handoff/1")
    with pytest.raises(nfh.HandoffError):
        nfh.parse_schema("novelforge.handoff/x")


def test_validate_rejects_bad_payloads():
    with pytest.raises(nfh.HandoffError, match="JSON 对象"):
        nfh.validate(["not", "a", "dict"])
    with pytest.raises(nfh.HandoffError, match="版本"):
        nfh.validate(_handoff(schema="novelforge.handoff/99"))
    with pytest.raises(nfh.HandoffError, match="novel_text"):
        nfh.validate(_handoff(novel_text="   "))
    with pytest.raises(nfh.HandoffError, match="chapters"):
        nfh.validate(_handoff(chapters=[]))
    with pytest.raises(nfh.HandoffError, match="num"):
        nfh.validate(_handoff(chapters=[{"title": "没有章号"}]))
    with pytest.raises(nfh.HandoffError, match="characters"):
        nfh.validate(_handoff(characters={"不是": "数组"}))


def test_validate_accepts_good_payload():
    assert nfh.validate(_handoff())["schema"] == "novelforge.handoff/1"


def test_load_reports_missing_and_broken_json(tmp_path):
    with pytest.raises(nfh.HandoffError, match="不存在"):
        nfh.load(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{不是 json", encoding="utf-8")
    with pytest.raises(nfh.HandoffError, match="合法 JSON"):
        nfh.load(bad)


# ───────── 映射 ─────────

def test_to_characters_is_zero_mapping_into_Character_model():
    chars = nfh.to_characters(_handoff())
    assert len(chars) == 1
    c = Character(**chars[0])          # 必须能直接构造，否则字段名就错了
    assert c.name == "林澈" and c.role_type == "主角" and c.appearance.startswith("瘦高")
    assert c.gender == "男" and c.age_range == "青年"


def test_to_characters_drops_unknown_keys_and_blank_names():
    data = _handoff(characters=[{"name": "A", "花里胡哨": "x", "role_type": "配角"},
                                {"name": "  "}, {"role_type": "没有名字"}])
    chars = nfh.to_characters(data)
    assert [c["name"] for c in chars] == ["A"]
    assert set(chars[0]) == set(nfh.CHARACTER_FIELDS)


def test_to_storyboard_input_shape():
    plan = nfh.to_storyboard_input(_handoff())
    assert plan["novel_text"].startswith("第1章 雨夜")
    assert plan["style_anchor"] == "青灰色调，冷峻短句"
    assert plan["title"] == "雨夜将至" and plan["chapters"] == 1
    assert len(plan["characters"]) == 1 and plan["scenes_seed"]
    assert plan["source"]["version"] == "10.1.0"


def test_summary_is_informative():
    s = nfh.summary(_handoff())
    assert "雨夜将至" in s and "张三" in s and "NovelForge" in s and "场景候选 1" in s


# ───────── 落盘 ─────────

def test_import_to_workspace_writes_usable_files(tmp_path):
    res = nfh.import_to_workspace(_handoff(), tmp_path / "job1")
    d = Path(res["dir"])
    assert (d / "novel.txt").read_text(encoding="utf-8").startswith("第1章 雨夜")
    chars = json.loads((d / "characters.json").read_text(encoding="utf-8"))
    assert Character(**chars[0]).name == "林澈"
    assert json.loads((d / "scenes_seed.json").read_text(encoding="utf-8"))[0]["kind"] == "narration"
    assert json.loads((d / "handoff.json").read_text(encoding="utf-8"))["schema"].endswith("/1")
    assert (d / "style_anchor.txt").read_text(encoding="utf-8") == "青灰色调，冷峻短句"
    assert set(res["written"]) == {"novel.txt", "characters.json", "scenes_seed.json",
                                   "handoff.json", "style_anchor.txt"}


def test_import_without_style_anchor_skips_file(tmp_path):
    res = nfh.import_to_workspace(_handoff(style_anchor=""), tmp_path / "job2")
    assert not (Path(res["dir"]) / "style_anchor.txt").exists()
    assert "style_anchor.txt" not in res["written"]


# ───────── CLI ─────────

def test_cli_end_to_end(tmp_path, capsys):
    hp = tmp_path / "给视频管线.json"
    hp.write_text(json.dumps(_handoff(), ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    import import_novelforge as cli

    code = cli.main([str(hp), "--out", str(tmp_path / "out"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and Path(out["dir"]).exists()
    assert (Path(out["dir"]) / "novel.txt").exists()


def test_cli_rejects_bad_handoff(tmp_path, capsys):
    hp = tmp_path / "bad.json"
    hp.write_text(json.dumps({"schema": "other/1"}, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    import import_novelforge as cli

    assert cli.main([str(hp)]) == 2
    assert "交接包不可用" in capsys.readouterr().out


# ───────── 真机往返（两个仓库真实衔接） ─────────

@pytest.mark.skipif(not NOVELFORGE.exists(), reason="本机没有 NovelForge 仓库")
def test_real_roundtrip_from_novelforge_repo(tmp_path):
    """用 NovelForge 自己的 handoff_export 造假数据 → 本仓库消费。

    这才是"衔接验证"：同一份文件在两个仓库之间真实流动，
    而不是两边各自对着自己的 mock 断言。
    """
    script = tmp_path / "emit.py"
    script.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, r'{NOVELFORGE}')\n"
        "import handoff_export as hx\n"
        "meta = {'title': '往返验证', 'author': '张三', 'genre': '都市',\n"
        "        'numbering_style': 'cn_title', 'numbering_template': ''}\n"
        "tracker = {'characters': {'林澈': {'role_type': '主角', 'gender': '男',\n"
        "           'appearance': '瘦高'}}}\n"
        "h = hx.build_handoff(meta, [(1, '雨夜', '夜里十一点。\\n\\n“不再想想？”王总说。')],\n"
        "                     tracker=tracker, style_anchor='青灰色调',\n"
        "                     source={'app': 'NovelForge', 'version': '10.1.0'})\n"
        f"out = r'{tmp_path / 'handoff.json'}'\n"
        "open(out, 'w', encoding='utf-8').write(json.dumps(h, ensure_ascii=False))\n"
        "print(out)\n", encoding="utf-8")

    py = NOVELFORGE / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        pytest.skip("NovelForge venv 不可用")
    r = subprocess.run([str(py), str(script)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    hp = tmp_path / "handoff.json"
    assert hp.exists(), r.stdout

    data = nfh.load(hp)
    assert data["source"]["app"] == "NovelForge"
    res = nfh.import_to_workspace(data, tmp_path / "out")
    d = Path(res["dir"])
    text = (d / "novel.txt").read_text(encoding="utf-8")
    assert "第1章 雨夜" in text and "王总说" in text
    chars = json.loads((d / "characters.json").read_text(encoding="utf-8"))
    assert Character(**chars[0]).name == "林澈"
    scenes = json.loads((d / "scenes_seed.json").read_text(encoding="utf-8"))
    assert [s["kind"] for s in scenes] == ["narration", "dialogue"], scenes
