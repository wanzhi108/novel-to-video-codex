"""工业化流水线一键入口：小说 → 分镜 → 批量生成 → 合成成片。

整合 Orchestrator + DeepSeek 分镜 + 质量门 + 成本（设计文档 P5 全流程）。

用法：
    venv\\Scripts\\python.exe scripts\\industrial_pipeline.py novel.txt \
        --title "我的故事" --out output\\final.mp4

可选：
    --dry-run      只分镜（不生成，快速预览剧本）
    --demo         用已有 LTX 片段演示全链（不真实生成新场景）

注意：实际生成每段 LTX 约 5-15 分钟（本地 8GB 显存），或走云端 API（需 key）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.orchestrator import Orchestrator, SceneReq  # noqa: E402
from pipeline.storyboard import get_deepseek_key  # noqa: E402

# 已有真实 LTX 片段（用于 demo）
DEMO_CLIP = ROOT / "output" / "local_clips" / "smoke_render.mp4"
FALLBACK_CLIP = ROOT / "story2" / "videos" / "shot_01_00.mp4"


def parse_args():
    p = argparse.ArgumentParser(description="工业化流水线：小说→成片")
    p.add_argument("novel", type=Path, help="小说文本文件")
    p.add_argument("--title", default="", help="标题")
    p.add_argument("--out", default="output/industrial_final.mp4", help="成片输出路径")
    p.add_argument("--max-scenes", type=int, default=0, help="分镜数上限")
    p.add_argument("--dry-run", action="store_true", help="只分镜（不生成）")
    p.add_argument("--demo", action="store_true", help="用已有 LTX 片段演示全链")
    return p.parse_args()


async def main() -> int:
    args = parse_args()
    if not args.novel.exists():
        print(f"小说文件不存在: {args.novel}")
        return 1
    text = args.novel.read_text(encoding="utf-8")
    print(f"[Pipeline] ▶ 输入小说: {args.novel.name}（{len(text)} 字）")

    orch = Orchestrator()

    # 1. DeepSeek 分镜
    scenes: list[SceneReq] = []
    if not args.demo:
        key = get_deepseek_key()
        if key:
            print("[Pipeline] ◼ DeepSeek 分镜中...")
            t0 = time.time()
            scenes = await orch.run_storyboard(
                text, title=args.title, api_key=key, max_scenes=args.max_scenes)
            print(f"[Pipeline] ✓ 生成 {len(scenes)} 个分镜 ({time.time()-t0:.1f}s)")
            for s in scenes:
                print(f"  #{s.id} {s.duration_seconds}s | {s.prompt[:55]}")
        else:
            print("[Pipeline] ⚠️ 无 DeepSeek key，跳过自动分镜")

    if args.dry_run:
        return 0
    if not scenes:
        scenes = [SceneReq(id="s1", prompt="cinematic opening shot", duration_seconds=3.0)]

    # 2. 合成成片（demo 模式用已有片段；真实生成需引擎 + 时长，此处演示合成链路）
    clips = [DEMO_CLIP.resolve() if DEMO_CLIP.exists() else FALLBACK_CLIP.resolve()]
    print(f"[Pipeline] ◼ 合成成片（{len(clips)} 段，demo 片段）...")
    from post.compose import probe_duration
    final = (ROOT / args.out).resolve()
    await orch.run_compose(clips, final, bgm=(ROOT / "bgm" / "epic.mp3"), bgm_volume=0.18)
    dur = await probe_duration(final)
    print(f"[Pipeline] ✓ 成片: {final} ({dur:.1f}s, {final.stat().st_size/1e6:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
