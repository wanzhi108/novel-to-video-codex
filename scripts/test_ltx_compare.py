"""LTX 2.3 同帧 I2V 测试（与 Wan 5B 对比）。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.local import ComfyUIEngine
from engines.base import GenerateRequest


async def main():
    eng = ComfyUIEngine()
    kf = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png")
    req = GenerateRequest(
        prompt="a young man in a rain-soaked cyberpunk street at night, cinematic neon lighting, close-up, sharp details",
        first_frame=kf,
        width=672, height=1152, duration_seconds=2.0, fps=24, seed=2024,
        negative_prompt="low quality, blurry, watermark, flicker, jitter",
        output_dir=Path(r"D:\novel-to-video-codex\output\ltx_compare"),
        output_name="ltx_shot",
    )
    print("是否可用:", eng.is_available(), flush=True)
    clip = await eng.generate(req)
    print("OK engine=%s seed=%s" % (clip.engine, clip.seed), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
