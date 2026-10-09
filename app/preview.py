"""快速预览档（preview profile）——"改一版先看节奏"用的降档参数。

设计原则：
- **只提供覆盖字典**，绝不改写全局默认常量（正式出片参数不受影响）；
- **必须显式开启**（`EngineLocal.preview = true` 或调用方传 `enabled=True`）；
- 参数只降不升：分辨率、帧数、采样步数都不超过正式档，并关闭超分/补帧。

近似依据（8GB 显存实测）：Wan 2.2 TI2V-5B 单镜 ~8min，耗时≈像素×帧数×步数，
超分与补帧（RIFE）是额外的大头；故预览档把三者同时降档。
"""
from __future__ import annotations

PREVIEW_PROFILE: dict = {
    "width": 480,        # 正式 960
    "height": 864,       # 正式 1728
    "frames": 33,        # 正式 96（~4s@24fps → 预览 ~1.4s，够看节奏）
    "steps": 4,          # 正式 8（蒸馏模型，步数越低越快）
    "upscale": False,    # 关闭 4x/2x 超分（显存与时间大头）
    "interpolate": False,  # 关闭 RIFE 补帧
}

_NUMERIC_KEYS = ("width", "height", "frames", "steps")
_BOOL_KEYS = ("upscale", "interpolate")


def build_overrides(base: dict, enabled: bool = True) -> dict:
    """按 base 中实际存在的键生成预览覆盖项；只降不升。"""
    if not enabled:
        return {}
    out: dict = {}
    for key in _NUMERIC_KEYS:
        if key not in base:
            continue
        target = PREVIEW_PROFILE.get(key)
        if target is None:
            continue
        cur = base[key]
        try:
            value = type(cur)(target)
        except Exception:
            value = target
        if value >= cur:  # 不升档；若目标不小于当前值则取一半，保证严格下降
            value = max(1, int(cur) // 2) if isinstance(cur, int) else cur / 2
        out[key] = value
    for key in _BOOL_KEYS:
        if key in base:
            out[key] = False
    return out


def estimate_gain(base: dict) -> dict:
    """估算预览档相对正式档的像素/帧数/步数/时间/显存比例（<1 表示更快更省）。"""
    ov = build_overrides(base, enabled=True)

    def ratio(key: str, default):
        cur = base.get(key, default) or default
        prev = ov.get(key, cur)
        try:
            return float(prev) / float(cur)
        except Exception:
            return 1.0

    px = ratio("width", 960) * ratio("height", 1728)
    frames = ratio("frames", 96)
    steps = ratio("steps", 8)

    # 采样耗时近似：像素 × 帧数 × 步数；超分/补帧关闭再各打一折
    time_ratio = px * frames * steps
    if base.get("upscale") and not ov.get("upscale", True):
        time_ratio *= 0.7
    if base.get("interpolate") and not ov.get("interpolate", True):
        time_ratio *= 0.8

    vram_ratio = px * min(frames, 1.0)
    summary = (
        f"预览档 ≈ 正式档 {max(time_ratio, 0.01) * 100:.0f}% 时间 / "
        f"{max(vram_ratio, 0.01) * 100:.0f}% 显存（{ov.get('width', '?')}×{ov.get('height', '?')}、"
        f"{ov.get('frames', '?')} 帧、{ov.get('steps', '?')} 步、超分与补帧关闭）"
    )
    return {
        "pixels_ratio": px,
        "frames_ratio": frames,
        "steps_ratio": steps,
        "est_time_ratio": time_ratio,
        "est_vram_ratio": vram_ratio,
        "overrides": ov,
        "summary": summary,
    }


def summarize(base: dict) -> str:
    """人类可读的一行摘要（可打印到日志/前端）。"""
    return estimate_gain(base)["summary"]
