"""CosyVoice speaker 选角（app/voice_cast.py 的 CosyVoice 侧）回归测试。

背景：CosyVoice2 服务预设 speaker 只有 **3 男 + 3 女 + 1 中性**（见 cosyvoice2/server.py
的 SPEAKER_DEFS 与 main.py 的 COSYVOICE_SPEAKERS），而 main.py 原本按角色逐个匹配
（`get_cosyvoice_speaker`）→ 与 edge-tts 一样会"多个角色撞同一把声音"。
本组测试固化：同剧角色 speaker 互不相同、确定性、人工锁定优先、旁白占位、超容量降级，
并且**音色池必须与 main.py / 服务端清单一致**（防止编造不存在的 speaker）。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakeChar:
    def __init__(self, name, gender="男", cosyvoice_voice="", voice_locked=False):
        self.name = name
        self.gender = gender
        self.cosyvoice_voice = cosyvoice_voice
        self.voice_id = ""
        self.voice_name = ""
        self.voice_candidates = []
        self.voice_locked = voice_locked


def _main_pool() -> set[str]:
    src = (ROOT / "scripts" / "main.py").read_text(encoding="utf-8")
    block = src[src.index("COSYVOICE_SPEAKERS = ["):]
    block = block[: block.index("]")]
    return set(re.findall(r'\(\s*"([a-z_]+)"\s*,', block))


def _server_pool() -> set[str]:
    src = (ROOT / "cosyvoice2" / "server.py").read_text(encoding="utf-8")
    block = src[src.index("SPEAKER_DEFS = ["):]
    block = block[: block.index("]\n")]
    return set(re.findall(r'\(\s*"([a-z_]+)"\s*,', block))


def test_cosyvoice_cast_module_api():
    from app import voice_cast

    for name in ("COSYVOICE_POOL", "cast_cosyvoice", "apply_cosyvoice_casting",
                 "cosyvoice_pool_ids"):
        assert hasattr(voice_cast, name), f"voice_cast 缺少 {name}"


def test_pool_matches_main_and_server_speakers():
    from app.voice_cast import cosyvoice_pool_ids

    pool = set(cosyvoice_pool_ids())
    assert pool, "CosyVoice 音色池为空"
    assert pool <= _main_pool(), f"池中含 main.py 未定义的 speaker: {pool - _main_pool()}"
    assert pool <= _server_pool(), f"池中含服务端未注册的 speaker: {pool - _server_pool()}"


def test_same_gender_characters_get_distinct_speakers():
    from app.voice_cast import apply_cosyvoice_casting

    chars = [FakeChar("王总", "男"), FakeChar("小杨", "男"), FakeChar("李叔", "男")]
    apply_cosyvoice_casting(chars)
    vals = [c.cosyvoice_voice for c in chars]
    assert len(set(vals)) == 3, f"男声 speaker 未去重: {vals}"


def test_over_capacity_degrades_without_raising():
    from app.voice_cast import apply_cosyvoice_casting

    chars = [FakeChar(f"男{i}", "男") for i in range(5)]  # 男声池仅 3
    details = apply_cosyvoice_casting(chars)
    assert all(c.cosyvoice_voice for c in chars)
    assert any(d["reason"] == "over_capacity" for d in details), details


def test_casting_is_deterministic():
    from app.voice_cast import apply_cosyvoice_casting

    def build():
        return [FakeChar("甲", "男"), FakeChar("乙", "男"), FakeChar("丙", "女"), FakeChar("丁", "女")]

    a, b = build(), build()
    apply_cosyvoice_casting(a)
    apply_cosyvoice_casting(b)
    assert [c.cosyvoice_voice for c in a] == [c.cosyvoice_voice for c in b]


def test_locked_speaker_is_respected_and_reserved():
    from app.voice_cast import apply_cosyvoice_casting

    chars = [FakeChar("主角", "男", cosyvoice_voice="chinese_male_mature", voice_locked=True),
             FakeChar("配角", "男", cosyvoice_voice="chinese_male_mature")]
    apply_cosyvoice_casting(chars)
    assert chars[0].cosyvoice_voice == "chinese_male_mature", "人工指定不得被覆盖"
    assert chars[1].cosyvoice_voice != "chinese_male_mature", "被占用的 speaker 不得再分配"


def test_narrator_speaker_not_given_to_characters():
    from app.voice_cast import apply_cosyvoice_casting

    chars = [FakeChar("甲", "男"), FakeChar("乙", "男")]
    apply_cosyvoice_casting(chars, narrator_speaker="chinese_male_deep")
    assert all(c.cosyvoice_voice != "chinese_male_deep" for c in chars), "旁白 speaker 不得被角色占用"


def test_unknown_current_speaker_is_replaced_with_pool_member():
    """角色身上若带着池外（不存在）的 speaker，应被替换为池内成员。"""
    from app.voice_cast import apply_cosyvoice_casting, cosyvoice_pool_ids

    chars = [FakeChar("甲", "男", cosyvoice_voice="not_a_real_speaker")]
    apply_cosyvoice_casting(chars)
    assert chars[0].cosyvoice_voice in cosyvoice_pool_ids(), chars[0].cosyvoice_voice
