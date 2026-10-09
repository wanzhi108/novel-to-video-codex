"""音色选角（app/voice_cast.py）回归测试。

背景（2026-10-09 实测）：`VOICE_MATCHING_RULES` 把多个不同角色映射到同一音色
（4 类男主全 → 云健、4 类女主全 → 晓晓），且 edge-tts 官方中文音色**只有 14 个**
（男 6 / 女 8，已由 `edge_tts.list_voices()` 实测确认）。一部剧里角色声音分不开，
是听感上最直接的"AI 味"。

本测试固化：
- 同剧不同角色音色两两不同（在池容量内）；
- 同一角色跨镜/跨集稳定（纯函数、确定性）；
- 人工指定（voice_locked）优先且占用不被抢；
- 旁白音色不与角色冲突；
- 超容量时降级而不是抛异常；
- 音色池只含**实测存在**的 14 个 id。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# edge_tts.list_voices() 于 2026-10-09 实测返回的中文音色全集
VERIFIED_ZH_VOICES = {
    "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunjianNeural",
    "zh-CN-YunxiNeural", "zh-CN-YunxiaNeural", "zh-CN-YunyangNeural",
    "zh-CN-liaoning-XiaobeiNeural", "zh-CN-shaanxi-XiaoniNeural",
    "zh-HK-HiuGaaiNeural", "zh-HK-HiuMaanNeural", "zh-HK-WanLungNeural",
    "zh-TW-HsiaoChenNeural", "zh-TW-HsiaoYuNeural", "zh-TW-YunJheNeural",
}


class FakeChar:
    def __init__(self, name, gender="男", voice_id="", voice_locked=False, age_range="青年"):
        self.name = name
        self.gender = gender
        self.voice_id = voice_id
        self.voice_name = ""
        self.voice_candidates = []
        self.voice_locked = voice_locked
        self.age_range = age_range


def test_voice_cast_module_api():
    from app import voice_cast

    for name in ("VOICE_POOL", "cast_voices", "apply_casting", "pool_ids"):
        assert hasattr(voice_cast, name), f"voice_cast 缺少 {name}"


def test_pool_contains_only_verified_voice_ids():
    from app.voice_cast import pool_ids

    unknown = set(pool_ids()) - VERIFIED_ZH_VOICES
    assert not unknown, f"音色池含未验证（可能不存在的）voice id: {unknown}"
    assert VERIFIED_ZH_VOICES <= set(pool_ids()), "音色池应覆盖全部 14 个实测中文音色"


def test_same_style_characters_get_distinct_voices():
    """三个都命中"沉稳"的男性角色，必须拿到三个不同音色。"""
    from app.voice_cast import apply_casting

    chars = [
        FakeChar("王总", voice_id="zh-CN-YunjianNeural"),
        FakeChar("李叔", voice_id="zh-CN-YunjianNeural"),
        FakeChar("赵哥", voice_id="zh-CN-YunjianNeural"),
    ]
    details = apply_casting(chars)
    ids = [c.voice_id for c in chars]
    assert len(set(ids)) == 3, f"角色音色未去重: {ids}"
    assert len({d["reason"] for d in details}) >= 1


def test_casting_is_deterministic():
    from app.voice_cast import apply_casting

    def build():
        return [FakeChar("甲", voice_id="zh-CN-YunjianNeural"),
                FakeChar("乙", voice_id="zh-CN-YunjianNeural"),
                FakeChar("丙", gender="女", voice_id="zh-CN-XiaoxiaoNeural"),
                FakeChar("丁", gender="女", voice_id="zh-CN-XiaoxiaoNeural")]

    a, b = build(), build()
    apply_casting(a)
    apply_casting(b)
    assert [c.voice_id for c in a] == [c.voice_id for c in b], "同一输入必须得到同一分配"


def test_locked_voice_is_respected_and_reserved():
    from app.voice_cast import apply_casting

    chars = [FakeChar("主角", voice_id="zh-CN-YunyangNeural", voice_locked=True),
             FakeChar("配角", voice_id="zh-CN-YunyangNeural")]
    apply_casting(chars)
    assert chars[0].voice_id == "zh-CN-YunyangNeural", "人工指定不得被覆盖"
    assert chars[1].voice_id != "zh-CN-YunyangNeural", "被人工占用的音色不得分给他人"


def test_narrator_voice_not_given_to_characters():
    from app.voice_cast import apply_casting

    chars = [FakeChar("甲", voice_id="zh-CN-YunxiNeural"),
             FakeChar("乙", voice_id="zh-CN-YunxiNeural")]
    apply_casting(chars, narrator_voice="zh-CN-YunxiNeural")
    assert all(c.voice_id != "zh-CN-YunxiNeural" for c in chars), "旁白音色不得被角色占用"


def test_over_capacity_degrades_without_raising():
    from app.voice_cast import apply_casting

    chars = [FakeChar(f"男{i}", voice_id="zh-CN-YunjianNeural") for i in range(9)]  # 男声池仅 6
    details = apply_casting(chars)
    assert len(details) == 9
    assert all(c.voice_id for c in chars), "超容量也必须给出音色"
    assert any(d["reason"] == "over_capacity" for d in details), "超容量应被标记"


def test_candidates_filled_for_frontend_picker():
    from app.voice_cast import apply_casting

    chars = [FakeChar("甲", gender="女", voice_id="zh-CN-XiaoxiaoNeural")]
    apply_casting(chars)
    cands = chars[0].voice_candidates
    assert cands, "应填充候选项供前端音色下拉"
    assert chars[0].voice_id not in cands, "候选项中不应包含当前已选音色"


def test_works_with_plain_dicts():
    from app.voice_cast import apply_casting

    chars = [{"name": "甲", "gender": "男", "voice_id": "zh-CN-YunjianNeural"},
             {"name": "乙", "gender": "男", "voice_id": "zh-CN-YunjianNeural"}]
    details = apply_casting(chars)
    assert len(details) == 2
    assert chars[0]["voice_id"] != chars[1]["voice_id"]


def test_character_model_has_voice_locked_default_false():
    from app.models import Character

    assert Character(name="甲").voice_locked is False, "人工锁定标记默认应为 False"
