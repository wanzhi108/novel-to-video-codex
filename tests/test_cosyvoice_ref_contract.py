"""CosyVoice 参考音频 ↔ prompt_text 契约测试（防止 2026-10-10 那类缺陷复发）。

缺陷回顾（实测证据）：
- D1：`/generate` 对预设 speaker 固定使用 `REGISTERED_SPKE_ID` → 所有角色同一把声音。
- D2：7 个 speaker 的 `prompt_text` 与参考音频真实内容 **7/7 不一致**（编造文本）
      → 零样本对齐错误，同一句输出 18.4s（edge-tts 仅 5.9s），语气发闷生硬。
- D3：`mood` 读入后从未使用，`MOOD_INSTRUCT` 是死代码 → 完全没有情绪控制。

本测试把三条都钉住。
"""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SERVER = ROOT / "cosyvoice2" / "server.py"
CN_REFS_JSON = ROOT / "cosyvoice2" / "cn_refs.json"
CN_REFS_DIR = ROOT / "cosyvoice2" / "cn_refs"


def _server_src() -> str:
    return SERVER.read_text(encoding="utf-8")


def _speaker_defs() -> list[tuple[str, str, str, str]]:
    src = _server_src()
    block = src[src.index("SPEAKER_DEFS = ["):]
    block = block[: block.index("]")]
    return re.findall(
        r'\(\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\)', block)


def _truth() -> dict:
    data = json.loads(CN_REFS_JSON.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else (data.get("value") or [])
    return {it["wav"]: (it.get("ref_text") or "").strip() for it in items if it.get("wav")}


def test_every_speaker_prompt_matches_reference_transcript():
    truth = _truth()
    defs = _speaker_defs()
    assert defs, "未解析到 SPEAKER_DEFS"
    bad = []
    for sid, _gender, wav, prompt in defs:
        real = truth.get(wav)
        if real is None:
            bad.append(f"{sid}: 参考音频 {wav} 不在 cn_refs.json 中")
        elif real != prompt.strip():
            bad.append(f"{sid}: prompt={prompt!r} ≠ 真实={real!r}")
    assert not bad, "prompt_text 与参考音频真实转录不一致（会导致拖长/生硬）:\n  " + "\n  ".join(bad)


@pytest.mark.skipif(not CN_REFS_DIR.exists(),
                    reason="参考音频是本地资产（cosyvoice2/cn_refs 未随仓库分发）；有资产时才校验")
def test_referenced_reference_wavs_exist():
    missing = [wav for _sid, _g, wav, _p in _speaker_defs() if not (CN_REFS_DIR / wav).exists()]
    assert not missing, f"SPEAKER_DEFS 引用了不存在的参考音频: {missing}"


def test_speaker_gender_matches_reference_filename():
    """男 speaker 必须用男声参考，女 speaker 用女声参考（否则角色性别都是错的）。"""
    bad = []
    for sid, gender, wav, _p in _speaker_defs():
        if gender == "男" and "男" not in wav:
            bad.append(f"{sid}({gender}) → {wav}")
        if gender == "女" and "女" not in wav:
            bad.append(f"{sid}({gender}) → {wav}")
    assert not bad, f"speaker 性别与参考音频不符: {bad}"


def test_canonical_prompt_matches_registered_reference():
    """注册 cosy_default 用的转写必须等于其参考音频（cn03）的真实转录。"""
    src = _server_src()
    m = re.search(r'CANONICAL_PROMPT\s*=\s*"([^"]*)"', src)
    assert m, "未找到 CANONICAL_PROMPT"
    default_wav = _speaker_defs()[0][2]
    assert m.group(1).strip() == _truth()[default_wav], "CANONICAL_PROMPT 与 default 参考音频不一致"


def test_generate_uses_requested_speaker_not_a_constant():
    """D1 防复发：预设 speaker 必须走 preset_<voice>，不能固定用注册常量。"""
    src = _server_src()
    assert 'f"preset_{voice}"' in src, "未按请求的 speaker 选择零样本 id"
    gen = src[src.index('@app.post("/generate")'):]
    assert "zero_shot_spk_id=spk_id" in gen, "generate 仍可能固定使用常量 spk id"


def test_mood_instruct_is_actually_used():
    """D3 防复发：MOOD_INSTRUCT 必须被真正调用（否则情绪控制是死代码）。"""
    src = _server_src()
    assert "MOOD_INSTRUCT.get(mood" in src, "mood 未映射到 instruct_text"
    assert "inference_instruct2(" in src, "未调用 instruct2，情绪无法生效"
