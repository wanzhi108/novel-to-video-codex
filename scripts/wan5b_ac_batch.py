"""用 A+C 关键帧(lkL_sX_kf.png) + 加固 Wan5B 重渲全部 6 镜。产物 output/wan5b_ac/。"""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engines.wan5b import Wan5BEngine
from engines.base import GenerateRequest
from opening_shots import SHOTS, KF_DIR

OUT = Path(r"D:\novel-to-video-codex\output\wan5b_ac")
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    eng = Wan5BEngine()
    print("可用:", eng.is_available(), flush=True)
    t0 = time.time()
    for shot in SHOTS:
        kf = KF_DIR / f"lkL_s{shot['id']}_kf.png"
        if not kf.exists():
            print(f"✗ shot{shot['id']} 缺 {kf}", flush=True); continue
        req = GenerateRequest(
            prompt=shot["video_prompt"], first_frame=kf,
            width=704, height=1280, duration_seconds=2.0, fps=24, seed=None,
            negative_prompt="blurry, low quality, watermark, flicker, deformed, extra limbs, bad hands",
            output_dir=OUT, output_name=f"ac_shot{shot['id']}", timeout_seconds=2400,
        )
        ts = time.time()
        try:
            clip = await eng.generate(req)
            print(f"✓ shot{shot['id']} seed={clip.seed} {clip.video_path.name} "
                  f"{round(clip.video_path.stat().st_size/1e6,1)}MB {round((time.time()-ts)/60,1)}min", flush=True)
        except Exception as exc:
            print(f"✗ shot{shot['id']} 失败: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
    print(f"batch done el={round((time.time()-t0)/60,1)}min", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
