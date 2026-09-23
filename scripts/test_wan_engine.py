"""用 WanEngine 直接生成一段稳定片（engine 层验证）。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo 根
from engines.wan import WanEngine
from engines.base import GenerateRequest


async def main():
    eng = WanEngine()
    kf = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png")
    req = GenerateRequest(
        prompt="a young man in a rain-soaked cyberpunk street at night, cinematic neon lighting, close-up, sharp details",
        first_frame=kf,
        width=384, height=672, duration_seconds=1.5, fps=24, seed=777,
        negative_prompt="blurry, low quality, watermark, flicker",
        output_dir=Path(r"D:\novel-to-video-codex\output\wan_engine_test"),
        output_name="shot_test",
    )
    print("是否可用:", eng.is_available(), flush=True)
    clip = await eng.generate(req)
    print("OK engine=%s seed=%s dur=%s" % (clip.engine, clip.seed, clip.duration_seconds), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
