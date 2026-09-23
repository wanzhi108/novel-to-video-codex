"""Wan 稳定管线 · 逐镜头批量生成器。

读 story2/shots.json，对每个 segment 用 WanEngine 从关键帧自动生成稳定超分片。
用法：
  python generate_wan_shots.py --dry-run          # 只列出将生成的镜头
  python generate_wan_shots.py --shots 1-3        # 只生成 scene 1~3
  python generate_wan_shots.py                    # 全量生成
"""
import argparse, asyncio, sys, json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.wan import WanEngine
from engines.base import GenerateRequest
import json

STORY = Path(__file__).resolve().parent.parent / "story2"
SHOTS = STORY / "shots.json"
OUT = Path(__file__).resolve().parent.parent / "output" / "wan_shots"
# 关键帧根目录（story2 下）
KF_DIR = STORY
# 角色 LoRA（可选，加载到工作流；需先训练/准备）
LORA = []


def load_shots():
    d = json.loads(SHOTS.read_text(encoding="utf-8"))
    return d.get("shots", [])


def resolve_kf(kf: str) -> Path:
    p = KF_DIR / kf
    if not p.exists():
        print(f"  ⚠ 关键帧缺失: {p}", flush=True)
    return p


def char_ref_of(kf: str) -> Optional[Path]:
    """按角色返回参考图（人设锁定）。角色无关时返回 None（不附加参考）。"""
    low = (kf or "").lower()
    char_to_ref = {
        "wang": "shot_01_kf_wang.png",
        "yang": "shot_01_kf_yang.png",
    }
    key = None
    if "_wang" in low:
        key = "wang"
    elif any(x in low for x in ("_yang", "_face", "_hands", "_profile")):
        key = "yang"
    if key is None:
        return None
    p = KF_DIR / char_to_ref[key]
    return p if p.exists() else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--shots", default="", help="如 '1-3'（scene 范围，含端点）；空=全部")
    args = ap.parse_args()

    shots = load_shots()
    eng = WanEngine(lora=LORA)
    if not eng.is_available():
        print("ComfyUI 不可达，请先本地启动 ComfyUI（--lowvram）。", flush=True)
        return

    lo = hi = None
    if args.shots:
        lo, hi = (int(x) for x in args.shots.split("-"))
        shots = [s for s in shots if lo <= s["id"] <= hi]

    print(f"将生成 {len(shots)} 个 scene，每 scene {len(shots[0]['segments']) if shots else 0} 段。", flush=True)
    if args.dry_run:
        for s in shots:
            for i, seg in enumerate(s["segments"]):
                print(f"  scene{s['id']:02d} seg{i}: {seg['kf']}  ({seg['camera'][:30]})", flush=True)
        return

    # 收集所有镜头，按批提交（一次加载模型，多镜头共享 — 摊薄 24min 冷启动）
    batch = []
    for s in shots:
        for i, seg in enumerate(s["segments"]):
            kf = resolve_kf(seg["kf"])
            if not kf.exists():
                continue
            ref = char_ref_of(seg["kf"])
            batch.append({
                "first_frame": kf,
                "prompt": f"{seg['emotion']}. {seg['camera']}.",
                "reference_image": ref if ref else None,
                "output_name": f"scene{s['id']:02d}_seg{i}_{Path(seg['kf']).stem}",
            })
    print(f"共 {len(batch)} 段，按批生成（每批一次模型加载）。", flush=True)
    # 分批（8GB 下一批 3-4 段较稳，避免多路 latent 挤占显存）
    BATCH_SIZE = 4
    for bi in range(0, len(batch), BATCH_SIZE):
        chunk = batch[bi:bi + BATCH_SIZE]
        print(f"[batch {bi//BATCH_SIZE + 1}] 生成 {len(chunk)} 段（共享一次模型加载）…", flush=True)
        try:
            res = await eng.generate_batch(chunk, output_dir=OUT, base_seed=None)
            for r in res:
                print(f"   ✅ {r.video_path.name}", flush=True)
        except Exception as exc:
            print(f"   ❌ 批失败 {type(exc).__name__}: {str(exc)[:140]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
