"""漫剧开场镜真实测试：Wan5BEngine 动画 t2i_opening_kf 关键帧。
产物: output/wan5b_opening/wan5b_opening.mp4
"""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan5b import Wan5BEngine
from engines.base import GenerateRequest

PROMPT = ("a young man in a teal jacket tending dried herbs at a dark wooden counter in a dim old "
          "Chinese herbal shop, slow subtle hand motion, weighing herbs in a brass scale, quiet "
          "deliberate movement, cinematic, cool low light with faint warm glow")

async def main():
    eng = Wan5BEngine()
    kf = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\t2i_opening_kf.png")
    req = GenerateRequest(
        prompt=PROMPT,
        first_frame=kf,
        width=704, height=1280, duration_seconds=2.0, fps=24, seed=2024,
        negative_prompt="blurry, low quality, watermark, flicker, deformed, extra limbs, bad hands",
        output_dir=Path(r"D:\novel-to-video-codex\output\wan5b_opening"),
        output_name="wan5b_opening",
        timeout_seconds=2400,
    )
    print("可用:", eng.is_available(), flush=True)
    t0 = time.time()
    clip = await eng.generate(req)
    el = time.time() - t0
    print("OK engine=%s seed=%s" % (clip.engine, clip.seed), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)
    print("elapsed_min:", round(el / 60, 1), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
