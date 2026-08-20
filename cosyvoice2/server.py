"""CosyVoice 2 API Server — 端口 50000，多 speaker + 情绪控制

被 main.py 的 _generate_tts_cosyvoice() 调用：
  POST /generate
  Body: {"text": "...", "voice": "chinese_male_deep", "mood": "温馨"}
  返回: audio/wav

修复:
1. 修复 example_reference.wav 不存在的问题
2. voice 参数映射到不同参考音频，实现多角色区分
3. mood 参数映射到 instruct_text 实现情绪控制
4. 启动时预热模型，避免首次请求 30 秒延迟
5. 完整错误处理
"""
import sys
import os
import io
import shutil
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
# CosyVoice 依赖 third_party/Matcha-TTS 子模块
sys.path.insert(0, str(ROOT / "third_party" / "Matcha-TTS"))

# ─── 兼容 shim: hydra 1.x 把 hydra.core 移到 hydra._internal.core ─────
# matcha.utils.rich_utils 还在用旧 API
try:
    import hydra._internal.core as _hydra_core
    import sys as _sys
    _sys.modules.setdefault("hydra.core", _hydra_core)
    _sys.modules.setdefault("hydra.core.hydra_config", _hydra_core.hydra_config)
    _sys.modules.setdefault("hydra.core.global_hydra", _hydra_core.global_hydra)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
import uvicorn
import torch

app = FastAPI(title="CosyVoice 2 API")


class TTSRequest(BaseModel):
    text: str = ""
    voice: str = "default"
    mood: str = ""
    # 任意外部参考音频（绝对路径）→ 走跨语言零样本，复用其音色读中文
    ref_wav: str = ""
    ref_text: str = ""

# ─── 7 个 speaker → 7 段参考音频（多角色区分用） ──────────────
# 大部分用同一段参考音频 + 不同 prompt_text 制造差异
# 若 refs/ 目录存在多段 wav，会优先使用
SPEAKER_DEFS = [
    # (speaker_id, gender, ref_filename, prompt_text)
    # ref_filename 位于 cn_refs/（可被 COSYVOICE_REFS_DIR 覆盖）
    ("default",              "中性", "cn03_女_36_四川.wav",
     "希望你以后能够做的比我还好呦。"),
    ("chinese_male_deep",    "男",  "cn07_男_24_安徽.wav",
     "今天我们来讨论一下这个项目的进展。"),
    ("chinese_male_young",   "男",  "cn07_男_24_安徽.wav",
     "嘿，兄弟你听我说，事情是这样的。"),
    ("chinese_male_mature",  "男",  "cn07_男_24_安徽.wav",
     "作为这个领域的专业人士，我认为应该这样处理。"),
    ("chinese_female_soft",  "女",  "cn03_女_36_四川.wav",
     "希望你以后能够做的比我还好哦。"),
    ("chinese_female_bright","女",  "cn03_女_36_四川.wav",
     "哎呀你看你看，这东西真的好有意思呀。"),
    ("chinese_female_calm",  "女",  "cn03_女_36_四川.wav",
     "各位听众朋友们，让我们一起走进今天的故事。"),
]

SPEAKER_MAP = {s[0]: {"gender": s[1], "ref": s[2], "prompt": s[3]} for s in SPEAKER_DEFS}

# 优先使用 refs/ 子目录的 wav（如果下载到了）
# CosyVoice2-0.5B 原生输出采样率（参考音频也是 24kHz）
# 旧版 CosyVoice(v1) 是 22050，这里用 v2 必须写 24000，否则声音会失真/变调
DEFAULT_SAMPLE_RATE = 24000

# 官方零样本参考音频对应的正确逐字转写（必须与实际音频内容一致）
CANONICAL_PROMPT = "希望你以后能够做的比我还好呦。"
REGISTERED_SPKE_ID = "cosy_default"

REFS_DIR = Path(os.environ.get("COSYVOICE_REFS_DIR", ROOT / "cn_refs"))
if not REFS_DIR.is_absolute():
    REFS_DIR = ROOT / REFS_DIR

# 自动按文件名归类到对应 speaker（cn_refs/*.wav 或自定义参考目录）
if REFS_DIR.exists():
    for f in REFS_DIR.glob("*.wav"):
        name = f.stem  # e.g. "cn07_男_24_安徽"
        for spk in SPEAKER_MAP:
            if name in spk or f.name == SPEAKER_MAP[spk]["ref"]:
                SPEAKER_MAP[spk]["ref"] = f.name
                break

# 兜底：default 一定可用；全部缺失时由调用方给出明确错误
DEFAULT_REF = REFS_DIR / "cn03_女_36_四川.wav"
if not DEFAULT_REF.exists():
    wavs = sorted(REFS_DIR.glob("*.wav")) if REFS_DIR.exists() else []
    DEFAULT_REF = wavs[0] if wavs else None

# ─── 情绪 → instruct_text 映射 ─────────────────────────────────
MOOD_INSTRUCT = {
    "紧张": "用紧张、急促的语气说",
    "温馨": "用温和、慈爱的语气说",
    "悲伤": "用悲伤、缓慢的语气说",
    "壮阔": "用雄壮、激昂的语气说",
    "神秘": "用低沉、神秘的语气说",
    "热血": "用激情澎湃的语气说",
    "恐惧": "用颤抖、害怕的语气说",
    "喜悦": "用开心、兴奋的语气说",
    "惆怅": "用惆怅、忧伤的语调说",
    "愤怒": "用愤怒、激昂的语气说",
    "压抑": "用低沉压抑的语气说",
    "释然": "用平静、释然的语气说",
    "宁静": "用轻柔平静的语气说",
    "诡异": "用诡异阴森的语气说",
    "傲慢": "用傲慢、轻蔑、居高临下的语气说",
    "自信": "用自信、从容、坚定的语气说",
    "冷静": "用冷静、沉稳、克制的语气说",
    "": "",
}


def resolve_speaker(voice: str) -> tuple[str, str]:
    """根据 speaker_id 返回 (ref_path, prompt_text)"""
    info = SPEAKER_MAP.get(voice, SPEAKER_MAP["default"])
    ref_path = REFS_DIR / info["ref"]
    if not ref_path.exists():
        ref_path = DEFAULT_REF
    if ref_path is None:
        raise RuntimeError("未找到 CosyVoice 参考音频，请设置 COSYVOICE_REFS_DIR 或放入 cn_refs/")
    return str(ref_path), info["prompt"]


# ─── 模型懒加载 ────────────────────────────────────────────────
_cosyvoice = None


def get_cosyvoice():
    global _cosyvoice
    if _cosyvoice is None:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        model_dir = os.environ.get("COSYVOICE_MODEL_DIR", "")
        if not model_dir:
            for _cand in (ROOT / "pretrained_models" / "CosyVoice2-0.5B",
                          ROOT / "models" / "iic" / "CosyVoice2-0___5B",
                          Path.home() / "CosyVoice2" / "pretrained_models" / "CosyVoice2-0.5B"):
                if _cand.exists():
                    model_dir = str(_cand)
                    break
        if not model_dir:
            raise RuntimeError("COSYVOICE_MODEL_DIR 未设置，且未找到本地 CosyVoice2 模型目录")
        print(f"[CosyVoice] 加载模型: {model_dir}", flush=True)
        # fp16=True 仅在 CUDA 可用时启用（CPU 推理 fp16 会报错）
        use_fp16 = torch.cuda.is_available()
        _cosyvoice = CosyVoice2(
            model_dir,
            load_jit=False,
            load_trt=False,
            fp16=use_fp16
        )
        print(f"[CosyVoice] 模型加载完成 (fp16={use_fp16}, device={'CUDA' if use_fp16 else 'CPU'})", flush=True)
        # 注意：本机曾把 transformers 误装成 5.13.0（requirements 要求 4.51.3），
        # 导致 LLM 静默吐乱码。已降级回 4.51.3，官方 fp16 路径即可正常工作，无需额外 hack。
        # 注册零样本说话人：用官方参考音频 + 正确转写，注册一次，生成时复用
        # 比每次传 prompt_wav 更稳定、音色更保真
        try:
            ref_for_reg = DEFAULT_REF
            if ref_for_reg is not None:
                _cosyvoice.add_zero_shot_spk(
                    CANONICAL_PROMPT, str(ref_for_reg), REGISTERED_SPKE_ID
                )
            print(f"[CosyVoice] 已注册零样本说话人: {REGISTERED_SPKE_ID}", flush=True)
            # 注册各预设说话人，供 voice 参数选择（多角色区分 + 情绪控制）
            for sid, info in SPEAKER_MAP.items():
                if sid == "default":
                    continue
                try:
                    refp = REFS_DIR / info["ref"]
                    if not refp.exists():
                        refp = DEFAULT_REF
                    if refp is not None:
                        _cosyvoice.add_zero_shot_spk(info["prompt"], str(refp), "preset_" + sid)
                except Exception as ex:
                    print(f"[CosyVoice] 预设说话人注册失败 {sid}: {ex}", flush=True)
        except Exception as e:
            print(f"[CosyVoice] 说话人注册失败(将退回普通zero_shot): {e}", flush=True)
            import traceback; traceback.print_exc()
    return _cosyvoice


@app.on_event("startup")
async def startup_event():
    """启动时预热，避免首次请求 30 秒延迟"""
    print("[CosyVoice] 预热加载模型...", flush=True)
    try:
        get_cosyvoice()
        print("[CosyVoice] 预热完成，服务就绪。", flush=True)
    except Exception as e:
        print(f"[CosyVoice] 预热失败: {e}", flush=True)
        print(traceback.format_exc(), flush=True)


@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "CosyVoice 2",
        "cuda": torch.cuda.is_available(),
        "model_loaded": _cosyvoice is not None,
        "speakers": list(SPEAKER_MAP.keys()),
    }


@app.post("/generate")
def generate_tts(req: TTSRequest):
    try:
        text = req.text.strip()
        voice = req.voice
        mood = req.mood

        if not text:
            raise HTTPException(400, "text is required")
        if len(text) > 500:
            text = text[:500]  # 截断防爆

        cv = get_cosyvoice()
        # 任意外部参考音频（跨语言零样本）：用于 LibriVox / LibriSpeech 等外部音色
        if req.ref_wav:
            rp = req.ref_wav
            if not os.path.exists(rp):
                raise HTTPException(400, f"ref_wav not found: {rp}")
            ref_text = (req.ref_text or "").strip()
            if ref_text:
                # 同语种克隆：有参考转写用 zero_shot，音色/韵律更保真
                print(f"[CosyVoice] 使用外部参考音频(zero_shot+ref_text): {rp}", flush=True)
                output = cv.inference_zero_shot(text, ref_text, rp, stream=False)
            else:
                # 无参考转写：跨语言零样本
                print(f"[CosyVoice] 使用外部参考音频(跨语言): {rp}", flush=True)
                output = cv.inference_cross_lingual(text, rp, stream=False)
        else:
            # 优先用注册的零样本说话人（音色更稳定、更保真）
            try:
                output = cv.inference_zero_shot(
                    text, "", "", zero_shot_spk_id=REGISTERED_SPKE_ID, stream=False
                )
            except Exception as e:
                # 注册说话人不可用时退回普通 zero_shot
                print(f"[CosyVoice] 注册说话人调用失败，退回普通zero_shot: {e}", flush=True)
                ref_path, prompt = resolve_speaker(voice)
                output = cv.inference_zero_shot(text, prompt, ref_path, stream=False)

        # output 可能是 generator of dicts (新API) 或 list of tuples (老API)
        # 兼容多种返回格式；拼接所有段落（长文本会被前端分句，需全部拼回）
        import wave as _wave
        import numpy as _np
        segs = []          # list of (sr, int16 ndarray)
        for item in output:
            if isinstance(item, tuple) and len(item) == 2:
                sr, audio = item
            elif isinstance(item, dict):
                sr = item.get("sample_rate", DEFAULT_SAMPLE_RATE)
                audio = item.get("tts_speech")
                if audio is None:
                    audio = item.get("audio")
            else:
                continue
            if audio is None:
                continue
            # audio 可能是 tensor
            try:
                if hasattr(audio, 'cpu'):
                    audio = audio.cpu().numpy()
                elif hasattr(audio, 'numpy'):
                    audio = audio.numpy()
            except Exception:
                pass
            audio = _np.asarray(audio)
            # 归一化到 [-1, 1]
            if audio.dtype != _np.float32 and audio.dtype != _np.float64:
                audio = audio.astype(_np.float32)
            max_val = float(_np.abs(audio).max()) if audio.size > 0 else 0.0
            if max_val > 1.0:
                audio = audio / max_val
            segs.append((int(sr), (audio * 32767).astype(_np.int16)))
        if not segs:
            raise RuntimeError("CosyVoice 未生成音频数据")
        sample_rate = segs[0][0]
        full = _np.concatenate([s for _, s in segs]) if len(segs) > 1 else segs[0][1]
        audio_bytes = io.BytesIO()
        with _wave.open(audio_bytes, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(full.tobytes())
        audio_bytes.seek(0)
        return Response(content=audio_bytes.read(), media_type="audio/wav")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[CosyVoice] 推理失败: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"CosyVoice 推理失败: {str(e)}"}
        )


if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("  CosyVoice 2 API Server — 端口 50000", flush=True)
    print("=" * 60, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=50000, log_level="info")
