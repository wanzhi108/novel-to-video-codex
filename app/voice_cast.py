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


def cast_voices(characters: Iterable[Any], *, narrator_voice: str = "",
                preferred: dict[str, str] | None = None) -> list[dict]:
    """计算分配明细（**不改动入参**），供调用方预览或落盘。

    返回每项：{name, voice_id, voice_name, candidates, reason}
    reason ∈ {"locked", "rule", "pool", "over_capacity"}
    """
    occupied: set[str] = set()
    if narrator_voice:
        occupied.add(narrator_voice)
    preferred = preferred or {}
    details: list[dict] = []

    for char in characters:
        pool = _pool_for(char)
        name = _get(char, "name", "") or ""
        current = _get(char, "voice_id", "") or ""
        locked = bool(_get(char, "voice_locked", False))
        prefer = preferred.get(name, "")

        chosen = ""
        reason = ""
        if locked and current:
            chosen, reason = current, "locked"
        elif prefer and prefer in {v["id"] for v in pool}:
            chosen, reason = prefer, "preferred"
        elif current and current not in occupied:
            chosen, reason = current, "rule"
        else:
            free = [v["id"] for v in pool if v["id"] not in occupied and v["id"] != current]
            if free:
                # 池内取第一个未被占用的（池顺序固定 → 确定性）
                chosen, reason = free[0], "pool"
            else:  # 池已被占满（含旁白占位）→ 降级复用，并显式标记
                fallback = [v["id"] for v in pool if v["id"] != narrator_voice] or [pool[0]["id"]]
                chosen, reason = fallback[0], "over_capacity"

        if reason != "over_capacity" and chosen in occupied and not locked:
            # 兜底：任何情况下都不把已占用音色分给他人
            free = [v["id"] for v in pool if v["id"] not in occupied]
            if free:
                chosen, reason = free[0], "pool"

        occupied.add(chosen)
        details.append({
            "name": name,
            "voice_id": chosen,
            "voice_name": _NAME_BY_ID.get(chosen, ""),
            "candidates": [v["id"] for v in pool if v["id"] != chosen],
            "reason": reason or "pool",
        })
    return details


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
