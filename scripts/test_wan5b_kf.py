"""Wan 5B I2V 测试（匹配关键帧 t2i_kf.png，与 LTX 同帧对比）。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan5b import Wan5BEngine
from engines.base import GenerateRequest

PROMPT = "a young man in a rain-soaked cyberpunk street at night, cinematic neon lighting, close-up, sharp details"

async def main():
    eng = Wan5BEngine()
    kf = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\t2i_kf.png")
    req = GenerateRequest(
        prompt=PROMPT,
        first_frame=kf,
        width=704, height=1280, duration_seconds=2.0, fps=24, seed=2024,
        negative_prompt="blurry, low quality, watermark, flicker",
        output_dir=Path(r"D:\novel-to-video-codex\output\wan5b_kf_test"),
        output_name="wan5b_kf",
        timeout_seconds=3000,
    )
    print("是否可用:", eng.is_available(), flush=True)
    clip = await eng.generate(req)
    print("OK engine=%s seed=%s" % (clip.engine, clip.seed), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
