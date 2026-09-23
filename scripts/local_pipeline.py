"""全本地流程：小说 → DeepSeek 分镜 → SDXL 关键帧 → LTX 视频 → 合成成片。

零云端依赖（视频/图像走本地 ComfyUI；分镜用 DeepSeek，可用 --no-llm 跳过）。

用法：
    venv\\Scripts\\python.exe scripts\\local_pipeline.py novel.txt --title X \
        --limit-scenes 2 --out output\\local_final.mp4

参数：
    --limit-scenes N     只生成前 N 场景（控制时长，LTX 每段约 5-15 分钟）
    --kf-checkpoint      关键帧模型（默认写实 RealVisXL_V4.0）
    --no-llm             跳过 DeepSeek 分镜（用占位场景）
    --no-compose         只生成不合成
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.local import ComfyUIEngine  # noqa: E402
from engines.base import GenerateRequest  # noqa: E402
from engines.quality_loop import GenerationGate  # noqa: E402
from pipeline.orchestrator import Orchestrator  # noqa: E402
from pipeline.storyboard import get_deepseek_key  # noqa: E402
from quality.gate import QualityGate, GateConfig  # noqa: E402
from quality.visual import assess_video, sharpness, DEFAULT_SHARPNESS_MIN  # noqa: E402
from config.settings import load_settings  # noqa: E402

DEFAULT_KF_CKPT = "RealVisXL_V4.0.safetensors"   # 写实
DEFAULT_KF_NEG = "low quality, worst quality, blurry, watermark, text, deformed, extra fingers, mutated"


def parse_args():
    p = argparse.ArgumentParser(description="全本地流程：小说→成片")
    p.add_argument("novel", type=Path, help="小说文本")
    p.add_argument("--title", default="")
    p.add_argument("--limit-scenes", type=int, default=2)
    p.add_argument("--kf-checkpoint", default=DEFAULT_KF_CKPT)
    p.add_argument("--video-timeout", type=int, default=2400)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--no-compose", action="store_true")
    p.add_argument("--out", default="output/local_final.mp4")
    return p.parse_args()


def load_novel(path: Path) -> str:
    return path.read_text(encoding="utf-8")


async def main() -> int:
    args = parse_args()
    if not args.novel.exists():
        print(f"小说不存在: {args.novel}")
        return 1
    text = load_novel(args.novel)
    print(f"[Local] ▶ 新故事: {args.novel.name}（{len(text)} 字）")

    orch = Orchestrator()
    engine = ComfyUIEngine(quality=load_settings().engines.local.quality)  # 质量由 settings.yaml 驱动
    if not engine.is_available():
        print("[Local] ❌ ComfyUI 离线，请先启动 restart_comfyui.bat")
        return 1
    print(f"[Local] ✓ ComfyUI 在线")

    # 1. 分镜（DeepSeek）或占位
    scenes = []
    if not args.no_llm:
        key = get_deepseek_key()
        if key:
            print("[Local] ◼ DeepSeek 分镜中...")
            t0 = time.time()
            scenes = await orch.run_storyboard(text, title=args.title, api_key=key)
            print(f"[Local] ✓ {len(scenes)} 个分镜 ({time.time()-t0:.1f}s)")
        else:
            print("[Local] ⚠️ 无 DeepSeek key，用占位场景")
    if not scenes:
        from pipeline.orchestrator import SceneReq
        scenes = [
            SceneReq(id="s1", prompt="a rainy convenience store at night, cinematic", duration_seconds=3),
            SceneReq(id="s2", prompt="a wet orange cat enters through the door, slow motion", duration_seconds=3),
        ]
    scenes = scenes[:args.limit_scenes]

    workdir = ROOT / "output" / "local_pipeline"
    workdir.mkdir(exist_ok=True)
    clips: list[Path] = []
    # 视觉门闭环：每段生成后若模糊/静态，自动换 seed 重试（最多 2 次）
    gate = GenerationGate([engine], QualityGate(), visual_gate=assess_video)

    # 2. 逐场景：SDXL 关键帧(sharp 把关) → LTX I2V(视觉门把关)
    for scene in scenes:
        sid = scene.id
        print(f"\n[Local] === 场景 {sid} ===")
        # 关键帧（SDXL 文生图）+ 清晰度把关
        kf = None
        for kf_attempt in range(2):
            print(f"[Local]   ◼ 生成关键帧（SDXL，第 {kf_attempt+1} 次）...")
            kf = await engine.generate_image(
                prompt=scene.prompt or "cinematic scene, 9:16",
                width=1080, height=1920,
                checkpoint=args.kf_checkpoint,
                negative_prompt=DEFAULT_KF_NEG,
                output_dir=workdir, output_name=f"kf_{sid}",
                seed=(None if kf_attempt == 0 else (2025 + int(sid) * 100 + kf_attempt)),
            )
            k_sharp = sharpness(kf)
            print(f"[Local]     关键帧 sharpness={k_sharp:.0f}")
            if k_sharp >= DEFAULT_SHARPNESS_MIN:
                break
            print(f"[Local]     ⚠️ 关键帧模糊({k_sharp:.0f}<{DEFAULT_SHARPNESS_MIN})，换 seed 重生成")

        # LTX I2V（视觉门自动重试）
        print(f"[Local]   ◼ LTX 图生视频（视觉门把关，约 5-15 分钟/次）...")
        t0 = time.time()
        req = GenerateRequest(
            prompt=scene.prompt or "slow cinematic push-in, realistic motion",
            first_frame=kf, width=960, height=1728,
            duration_seconds=min(scene.duration_seconds, 4.0),  # 97 帧 @24fps（HQ 更长动作）
            output_dir=workdir, output_name=f"clip_{sid}",
            timeout_seconds=args.video_timeout,
        )
        res = await gate.generate(req)
        clip = res
        elapsed = time.time() - t0
        hist = (clip.quality_report or {}).get("retry_history", [])
        retries = len(hist) - 1 if hist else 0
        vq = (clip.quality_report or {}).get("visual") or {}
        sharp_v = vq.get("sharpness_min")
        if clip.quality_report and clip.quality_report.get("passed"):
            clips.append(clip.video_path)
            print(f"[Local]   ✓ 视频段 {clip.video_path.name} ({elapsed/60:.1f} 分钟, 重试 {retries} 次, "
                  f"sharp={sharp_v})")
        else:
            print(f"[Local]   ⚠️ 场景 {sid} 反复模糊(sharp={sharp_v})，跳过该镜（避免混入糊片）")

    # 3. 合成
    if not args.no_compose and clips:
        print("\n[Local] ◼ 合成成片...")
        from post.compose import compose_video, probe_duration
        final = (ROOT / args.out).resolve()
        await compose_video(clips, final, bgm=(ROOT / "bgm" / "epic.mp3"), bgm_volume=0.18)
        dur = await probe_duration(final)
        print(f"[Local] ✓ 成片: {final} ({dur:.1f}s, {final.stat().st_size/1e6:.1f}MB)")
        gr = await QualityGate().check_video(final, expect_duration=dur, config=GateConfig(require_audio=True))
        vq = assess_video(str(final))
        print(f"[Local] 质量门: 技术={gr.get('passed')}, 视觉={vq.get('passed')} "
              f"(sharp={vq.get('sharpness_min')}, motion={vq.get('motion')})")
    else:
        print("[Local] 跳过合成（--no-compose）")

    print("LOCAL PIPELINE OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
