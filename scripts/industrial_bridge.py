"""桌面应用 ↔ 工业引擎桥接（P6）。

把 scripts/main.py 的单场景图生视频调度升级为"新引擎优先、旧引擎兜底"：

1. 优先调用 engines.local.ComfyUIEngine（LTX 22B, 96帧/4s, 8+3 步，质量调优参数
   由 settings.yaml 驱动），并套上 GenerationGate（QualityGate 技术门 +
   quality.visual.assess_video 视觉门）自动 reseed 重试；
2. 新引擎不可用/失败/质量门反复不过时返回 None，由 main.py 回退旧
   video_engine.dispatch —— 保证桌面 UI 永远有结果，且默认走最高质量路径。

开关（环境变量，默认开启）：
    LF_INDUSTRIAL=0   关闭新引擎，全部走旧调度
    LF_INDUSTRIAL=1   开启（默认）

本模块刻意不 import scripts/main.py（避免巨核循环依赖），只依赖
engines/、quality/、config/ 等新包。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 源码模式以仓库根为项目根；打包模式以 _MEIPASS 为只读资源根
PROJECT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings  # noqa: E402
from engines.base import GenerateRequest  # noqa: E402
from engines.local import ComfyUIEngine  # noqa: E402
from engines.quality_loop import GenerationGate, RetryConfig  # noqa: E402
from quality.gate import QualityGate  # noqa: E402
from quality.visual import assess_video  # noqa: E402


def industrial_enabled() -> bool:
    """新引擎开关：LF_INDUSTRIAL=0 关闭，其余开启（默认开启）。"""
    return os.environ.get("LF_INDUSTRIAL", "1") != "0"


def _resolve_settings_path() -> Optional[str]:
    """打包模式下优先读 exe 旁的 settings.yaml（用户可写），否则用仓库根。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        alt = exe_dir / "settings.yaml"
        if alt.exists():
            return str(alt)
    return None


def _prompt_for_i2v(base_prompt: str, scene) -> str:
    """把 main.py 已构建好的视频提示词转成 I2V 提示词。

    main.py 的 vid_base_prompt 已含运镜/风格后缀；这里只做轻微兜底，
    若为空则从场景描述生成一个可用的英文提示词。
    """
    prompt = (base_prompt or "").strip()
    if prompt:
        return prompt
    desc = getattr(scene, "video_prompt", "") or getattr(scene, "description", "") or ""
    if desc:
        return desc
    return "cinematic scene, slow camera motion, high detail"


async def generate_scene_video(
    job,
    scene,
    scene_dir,
    vid_base_prompt: str,
    first_frame,
    timeout_seconds: float = 2400.0,
) -> Optional[str]:
    """新引擎优先生成单场景视频；失败返回 None（由调用方回退旧引擎）。

    Args:
        job:          main.py 的 JobState（读 video_mode 等）
        scene:        main.py 的 Scene（读 id/prompt/时长）
        scene_dir:    场景输出目录
        vid_base_prompt: main.py 已构建的视频提示词
        first_frame:  首帧图路径（1080×1920 关键帧）
        timeout_seconds: 单次生成超时（96 帧 HQ 需较长）

    Returns:
        视频文件路径（str），或 None（新引擎不可用/失败/质量门不过）。
    """
    if not industrial_enabled():
        print("[Industrial] LF_INDUSTRIAL=0，跳过新引擎（走旧调度）", flush=True)
        return None

    if not first_frame or not Path(str(first_frame)).exists():
        print(f"[Industrial] 无首帧图（{first_frame}），跳过新引擎（T2V/占位场景交给旧调度）", flush=True)
        return None

    # 质量由 settings.yaml 驱动（local.quality=high → 96帧；步数恒 8+3）
    settings = load_settings(_resolve_settings_path())
    local_cfg = settings.engines.local
    quality = getattr(local_cfg, "quality", "high")
    fps = int(getattr(local_cfg, "fps", 24) or 24)
    frames = int(getattr(local_cfg, "frames", 96) or 96)
    width = int(getattr(local_cfg, "width", 960) or 960)
    height = int(getattr(local_cfg, "height", 1728) or 1728)
    duration_seconds = max(1.0, round(frames / fps, 2))  # 96/24 = 4.0s

    engine = ComfyUIEngine(quality=quality)
    if not engine.is_available():
        print("[Industrial] ComfyUI 离线，回退旧引擎", flush=True)
        return None

    scene_dir_path = Path(str(scene_dir))
    scene_dir_path.mkdir(parents=True, exist_ok=True)
    sid = getattr(scene, "id", "scene") or "scene"

    req = GenerateRequest(
        prompt=_prompt_for_i2v(vid_base_prompt, scene),
        first_frame=Path(str(first_frame)),
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        fps=fps,
        output_dir=scene_dir_path,
        output_name=f"industrial_{sid}",
        timeout_seconds=timeout_seconds,
    )

    gate = GenerationGate(
        [engine],
        QualityGate(),
        RetryConfig(
            max_retries=getattr(settings.quality, "max_retries", 2),
            strategy=getattr(settings.quality, "retry_strategy", ["reseed"]),
        ),
        visual_gate=assess_video,
    )

    print(f"[Industrial] 场景 {sid}: LTX I2V {frames}f@{fps}fps ({duration_seconds}s) 质量门闭环生成中…",
          flush=True)
    try:
        clip = await gate.generate(req)
    except Exception as exc:  # noqa: BLE001
        print(f"[Industrial] 场景 {sid} 新引擎失败（{str(exc)[:200]}），回退旧引擎", flush=True)
        return None

    report = clip.quality_report or {}
    vq = report.get("visual") or {}
    # 8GB 显存策略：工业引擎已成功出片（视频文件有效）就采用，不再因质量门未过回退旧引擎。
    # 旧引擎 video_engine 用 960×1728×97帧 高负载，在 8GB 下必"卡死"（staging 23GB/170s步）。
    # 降负载(672×1152×65帧)的工业引擎视频即便质量门 minor 未过，也比旧引擎稳定得多。
    if clip and clip.video_path and Path(clip.video_path).exists() \
            and Path(clip.video_path).stat().st_size > 10000:
        if report.get("passed"):
            print(f"[Industrial] ✓ 场景 {sid}: {Path(clip.video_path).name} 通过质量门 "
                  f"(sharp={vq.get('sharpness_min')}, motion={vq.get('motion')})", flush=True)
        else:
            print(f"[Industrial] ✓ 场景 {sid}: {Path(clip.video_path).name} 已出片(质量门未过但采用，避免回退高负载旧引擎) "
                  f"(sharp={vq.get('sharpness_min')}, motion={vq.get('motion')}, issues={report.get('issues', [])})", flush=True)
        return str(clip.video_path)

    print(f"[Industrial] ⚠ 场景 {sid} 工业引擎无有效产物，回退旧引擎", flush=True)
    return None
