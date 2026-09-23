"""Wan 5B I2V 测试（单模型，用于与 LTX 对比）。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan5b import Wan5BEngine
from engines.base import GenerateRequest


async def main():
    eng = Wan5BEngine()
    kf = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png")
    req = GenerateRequest(
        prompt="a young person in a rain-soaked cyberpunk street at night, cinematic neon lighting, close-up, sharp details",
        first_frame=kf,
        width=704, height=1280, duration_seconds=2.0, fps=24, seed=2024,
        negative_prompt="blurry, low quality, watermark, flicker",
        output_dir=Path(r"D:\novel-to-video-codex\output\wan5b_test"),
        output_name="wan5b_shot",
    )
    print("是否可用:", eng.is_available(), flush=True)
    clip = await eng.generate(req)
    print("OK engine=%s seed=%s" % (clip.engine, clip.seed), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
