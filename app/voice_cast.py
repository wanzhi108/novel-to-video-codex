"""音色选角（voice casting）：让同一部剧里的角色"听得出是不同人"。

问题（2026-10-09 实测）：`VOICE_MATCHING_RULES` 把多个不同气质映射到同一音色
（男_青年_沉稳 / 男_中年_沉稳 / 男_老年_沧桑 / 男_反派_阴沉 → 全部云健；
女_青年_温柔 / 女_中年_沉稳 / 女_老年_慈祥 / 女_反派_凌厉 → 全部晓晓），
而 edge-tts 官方中文音色只有 14 个（男 6 / 女 8，`edge_tts.list_voices()` 实测）。
结果是"全剧两把声音"，听感上 AI 味最重。

本模块只做一件确定性的事：**在池容量内，让同剧角色音色两两不同；人工指定的保持不动。**
- 叶子模块（仅标准库），入参可用对象或 dict（鸭子类型）；
- 纯函数：同输入必同输出（跨镜/跨集一致）；
- 超容量时降级（复用音色）而不是抛异常。
"""
from __future__ import annotations

from typing import Any, Iterable

# 音色池：仅收录 2026-10-09 由 edge_tts.list_voices() 实测存在的中文音色（共 14 个）
VOICE_POOL: dict[str, list[dict]] = {
    "男": [
        {"id": "zh-CN-YunjianNeural", "name": "云健",
         "tags": ["青年", "中年", "沉稳", "沧桑", "阴沉", "默认"]},
        {"id": "zh-CN-YunxiNeural", "name": "云希", "tags": ["青年", "活力", "阳光"]},
        {"id": "zh-CN-YunxiaNeural", "name": "云夏", "tags": ["少年", "清朗"]},
        {"id": "zh-CN-YunyangNeural", "name": "云扬", "tags": ["播报", "正式", "严肃"]},
        {"id": "zh-TW-YunJheNeural", "name": "雲哲", "tags": ["台湾腔", "青年"]},
        {"id": "zh-HK-WanLungNeural", "name": "雲龍", "tags": ["粤语", "中年"]},
    ],
    "女": [
        {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "tags": ["青年", "温柔", "慈祥", "默认"]},
        {"id": "zh-CN-XiaoyiNeural", "name": "晓依", "tags": ["青年", "活泼", "清纯"]},
        {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北", "tags": ["东北", "活泼"]},
        {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮", "tags": ["陕西"]},
        {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻", "tags": ["台湾腔", "温柔"]},
        {"id": "zh-TW-HsiaoYuNeural", "name": "曉雨", "tags": ["台湾腔", "青年"]},
        {"id": "zh-HK-HiuGaaiNeural", "name": "曉佳", "tags": ["粤语"]},
        {"id": "zh-HK-HiuMaanNeural", "name": "曉曼", "tags": ["粤语", "温柔"]},
    ],
}

_NAME_BY_ID = {v["id"]: v["name"] for vs in VOICE_POOL.values() for v in vs}


def pool_ids(gender: str | None = None) -> list[str]:
    """音色池中的 voice id（可按性别过滤）。"""
    if gender in VOICE_POOL:
        return [v["id"] for v in VOICE_POOL[gender]]
    return [v["id"] for vs in VOICE_POOL.values() for v in vs]


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def _gender_of(char: Any) -> str:
    g = _get(char, "gender", "")
    return g if g in VOICE_POOL else "男"


def _pool_for(char: Any) -> list[dict]:
    return VOICE_POOL[_gender_of(char)]


def _cast_in_pool(characters: Iterable[Any], pool_by_gender: dict, current_attr: str, *,
                  narrator_value: str = "", preferred: dict[str, str] | None = None,
                  locked_attr: str = "voice_locked") -> list[dict]:
    """通用选角核心：同剧去重、人工锁定优先、旁白占位、超容量降级（确定性）。

    `current_attr` 是角色身上已有音色字段名（edge 用 voice_id，CosyVoice 用 cosyvoice_voice）；
    字段值若不在池内（陈旧/不存在的音色）一律视为无，避免把非法值原样保留。
    返回每项：{name, value, candidates, reason}
    """
    occupied: set[str] = set()
    if narrator_value:
        occupied.add(narrator_value)
    preferred = preferred or {}
    details: list[dict] = []

    for char in characters:
        gender = _get(char, "gender", "")
        pool = pool_by_gender.get(gender) or pool_by_gender.get("男") or []
        ids = [v["id"] for v in pool]
        id_set = set(ids)
        name = _get(char, "name", "") or ""
        current = _get(char, current_attr, "") or ""
        if current not in id_set:
            current = ""
        locked = bool(_get(char, locked_attr, False))
        prefer = preferred.get(name, "")
        if prefer not in id_set:
            prefer = ""

        chosen = ""
        reason = ""
        if locked and current:
            chosen, reason = current, "locked"
        elif prefer:
            chosen, reason = prefer, "preferred"
        elif current and current not in occupied:
            chosen, reason = current, "rule"
        else:
            free = [i for i in ids if i not in occupied and i != current]
            if free:
                # 池内取第一个未被占用的（池顺序固定 → 确定性）
                chosen, reason = free[0], "pool"
            else:  # 池已被占满（含旁白占位）→ 降级复用，并显式标记
                fallback = [i for i in ids if i != narrator_value] or ids
                chosen, reason = fallback[0], "over_capacity"

        if reason != "over_capacity" and chosen in occupied and not locked:
            free = [i for i in ids if i not in occupied]
            if free:
                chosen, reason = free[0], "pool"

        occupied.add(chosen)
        details.append({
            "name": name,
            "value": chosen,
            "candidates": [i for i in ids if i != chosen],
            "reason": reason or "pool",
        })
    return details


def cast_voices(characters: Iterable[Any], *, narrator_voice: str = "",
                preferred: dict[str, str] | None = None) -> list[dict]:
    """Edge-TTS 侧选角明细（**不改动入参**）。

    返回每项：{name, voice_id, voice_name, candidates, reason}
    reason ∈ {"locked", "preferred", "rule", "pool", "over_capacity"}
    """
    return [
        {**d, "voice_id": d["value"], "voice_name": _NAME_BY_ID.get(d["value"], "")}
        for d in _cast_in_pool(characters, VOICE_POOL, "voice_id",
                               narrator_value=narrator_voice, preferred=preferred)
    ]


def apply_casting(characters: Iterable[Any], *, narrator_voice: str = "",
                  preferred: dict[str, str] | None = None) -> list[dict]:
    """就地写回 `voice_id` / `voice_name` / `voice_candidates`，返回分配明细。"""
    details = cast_voices(characters, narrator_voice=narrator_voice, preferred=preferred)
    chars = list(characters)
    for char, detail in zip(chars, details):
        _set(char, "voice_id", detail["voice_id"])
        _set(char, "voice_name", detail["voice_name"])
        _set(char, "voice_candidates", detail["candidates"])
    return details


# ─── CosyVoice2 speaker 选角 ────────────────────────────────────────────────
# 池必须与 main.py 的 COSYVOICE_SPEAKERS 以及 cosyvoice2/server.py 的 SPEAKER_DEFS 一致
# （tests/test_cosyvoice_cast.py 有契约校验）：服务端只预设 3 男 + 3 女 + 1 中性，
# 若不选角，一部剧里多个同性角色会共用同一把声音。
COSYVOICE_POOL: dict[str, list[dict]] = {
    "男": [
        {"id": "chinese_male_deep", "name": "男·低沉", "tags": ["沉稳", "大气", "低沉", "默认"]},
        {"id": "chinese_male_young", "name": "男·清朗", "tags": ["活力", "阳光", "清朗"]},
        {"id": "chinese_male_mature", "name": "男·中年", "tags": ["中年", "沧桑", "播报"]},
    ],
    "女": [
        {"id": "chinese_female_soft", "name": "女·温柔", "tags": ["温柔", "柔和", "内敛", "默认"]},
        {"id": "chinese_female_bright", "name": "女·活泼",
         "tags": ["活泼", "俏皮", "灵动", "清纯"]},
        {"id": "chinese_female_calm", "name": "女·沉稳", "tags": ["慈祥", "沉稳", "中年"]},
    ],
    "中性": [{"id": "default", "name": "通用/旁白", "tags": ["通用", "旁白"]}],
}

_CV_NAME_BY_ID = {v["id"]: v["name"] for vs in COSYVOICE_POOL.values() for v in vs}


def cosyvoice_pool_ids(gender: str | None = None) -> list[str]:
    """CosyVoice speaker 池（可按性别过滤）。"""
    if gender in COSYVOICE_POOL:
        return [v["id"] for v in COSYVOICE_POOL[gender]]
    return [v["id"] for vs in COSYVOICE_POOL.values() for v in vs]


def cast_cosyvoice(characters: Iterable[Any], *, narrator_speaker: str = "",
                   preferred: dict[str, str] | None = None) -> list[dict]:
    """CosyVoice speaker 选角明细（**不改动入参**）。"""
    return [
        {**d, "cosyvoice_voice": d["value"], "speaker_name": _CV_NAME_BY_ID.get(d["value"], "")}
        for d in _cast_in_pool(characters, COSYVOICE_POOL, "cosyvoice_voice",
                               narrator_value=narrator_speaker, preferred=preferred)
    ]


def apply_cosyvoice_casting(characters: Iterable[Any], *, narrator_speaker: str = "",
                            preferred: dict[str, str] | None = None) -> list[dict]:
    """就地写回 `cosyvoice_voice`，返回分配明细。"""
    details = cast_cosyvoice(characters, narrator_speaker=narrator_speaker, preferred=preferred)
    chars = list(characters)
    for char, detail in zip(chars, details):
        _set(char, "cosyvoice_voice", detail["cosyvoice_voice"])
    return details

