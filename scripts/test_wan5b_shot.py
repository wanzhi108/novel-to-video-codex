"""验证加固后的 Wan5BEngine：单镜两段式（采样+超分）生成，避免超分 OOM。"""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engines.wan5b import Wan5BEngine
from engines.base import GenerateRequest
from opening_shots import SHOTS, KF_DIR

OUT = Path(r"D:\novel-to-video-codex\output\wan5b_opening")


async def run_shot(shot):
    eng = Wan5BEngine()
    kf = KF_DIR / shot["kf_file"]
    req = GenerateRequest(
        prompt=shot["video_prompt"], first_frame=kf,
        width=704, height=1280, duration_seconds=2.0, fps=24, seed=None,
        negative_prompt="blurry, low quality, watermark, flicker, deformed, extra limbs, bad hands",
        output_dir=OUT, output_name=f"wan5b_shot{shot['id']}", timeout_seconds=2400,
    )
    t0 = time.time()
    clip = await eng.generate(req)
    print(f"✓ shot{shot['id']} OK seed={clip.seed} {clip.video_path.name} "
          f"{round(clip.video_path.stat().st_size/1e6,1)}MB {round((time.time()-t0)/60,1)}min", flush=True)
    return clip


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    shot = next(s for s in SHOTS if s["id"] == target)
    asyncio.run(run_shot(shot))
