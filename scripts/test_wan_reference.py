"""端到端测试：WanEngine + 参考图强化（角色一致性）。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan import WanEngine
from engines.base import GenerateRequest


async def main():
    eng = WanEngine()
    start = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png")
    ref = Path(r"D:\novel-to-video-codex\story2\shot_01_kf_wang.png")  # Wang 角色参考图
    req = GenerateRequest(
        prompt="a young man in a rain-soaked cyberpunk street at night, cinematic neon lighting, close-up",
        first_frame=start,
        reference_images=[ref],
        width=384, height=672, duration_seconds=1.5, fps=24, seed=888,
        output_dir=Path(r"D:\novel-to-video-codex\output\wan_reference_test"),
        output_name="ref_test",
    )
    print("是否可用:", eng.is_available(), flush=True)
    clip = await eng.generate(req)
    print("OK engine=%s seed=%s" % (clip.engine, clip.seed), flush=True)
    print("VIDEO:", clip.video_path, flush=True)
    print("size MB:", round(clip.video_path.stat().st_size / 1e6, 1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
