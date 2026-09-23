"""Wan 批处理测试：2 镜头共享一次模型加载。"""
import os
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan import WanEngine


async def main():
    eng = WanEngine()
    shots = [
        {"first_frame": r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png",
         "reference_image": r"D:\novel-to-video-codex\story2\shot_01_kf_yang.png",
         "prompt": "a young man in a rain-soaked cyberpunk street at night, cinematic, close-up",
         "output_name": "batchs0"},
        {"first_frame": r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_002_shot1.png",
         "reference_image": r"D:\novel-to-video-codex\story2\shot_01_kf_wang.png",
         "prompt": "a stern boss in a harsh-lit office, medium shot, moody",
         "output_name": "batchs1"},
    ]
    # 用存在的场景图兜底
    import glob
    if not Path(shots[1]["first_frame"]).exists():
        g = glob.glob(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\*\scene_002_shot1.png"))
        shots[1]["first_frame"] = (g[0] if g else shots[0]["first_frame"])
    print("是否可用:", eng.is_available(), flush=True)
    res = await eng.generate_batch(shots, width=384, height=672, duration_seconds=2.0, base_seed=12345)
    print("batch 产出:", len(res), flush=True)
    for r in res:
        print("  ", r.video_path, round(r.video_path.stat().st_size / 1e6, 1), "MB", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
