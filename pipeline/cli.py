"""工业化流水线统一 CLI。

用法：
    python -m pipeline.cli status                 # 引擎/质量门可用性
    python -m pipeline.cli render --frame kf.png  # 本地生成一段（需 ComfyUI）
    python -m pipeline.cli compose-story2          # story2 素材合成成片
    python -m pipeline.cli compose --clips a.mp4,b.mp4 --out final.mp4 [--bgm x.mp3]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cmd_status(args) -> int:
    from engines.cli import cmd_status as _s
    return _s(args)


def cmd_render(args) -> int:
    from engines.base import GenerateRequest

    async def run():
        from engines.local import ComfyUIEngine
        engine = ComfyUIEngine()
        if not engine.is_available():
            print("ComfyUI 不可达（8188）。请先启动 restart_comfyui.bat")
            return 1
        frame = Path(args.frame) if args.frame else None
        req = GenerateRequest(
            prompt=args.prompt,
            first_frame=frame,
            duration_seconds=args.duration,
            output_dir=ROOT / "output" / "local_clips",
            output_name=args.name or "cli_render",
            timeout_seconds=1200.0,
        )
        clip = await engine.generate(req)
        print(f"✅ {clip.video_path}")
        return 0

    return asyncio.run(run())


def cmd_compose(args) -> int:
    from post.compose import compose_video

    async def run():
        clips = [Path(c) for c in args.clips.split(",")]
        out = (ROOT / args.out).resolve()
        bgm = Path(args.bgm) if args.bgm else None
        await compose_video(clips, out, bgm=bgm, bgm_volume=args.bgm_volume)
        print(f"✅ {out}")
        return 0

    return asyncio.run(run())


def cmd_compose_story2(args) -> int:
    from scripts import compose_story2  # type: ignore
    import runpy
    sys.argv = ["compose_story2"]
    if args.bgm:
        sys.argv += ["--bgm", args.bgm]
    if args.no_subtitles:
        sys.argv += ["--no-subtitles"]
    return runpy.run_module("scripts.compose_story2", run_name="__main__").get("__result__", 0) or 0


def main() -> int:
    parser = argparse.ArgumentParser(description="工业化流水线 CLI")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("status", help="引擎/质量门可用性")
    p.add_argument("--prefer", default=None)

    p = sub.add_parser("render", help="本地生成一段视频（需 ComfyUI）")
    p.add_argument("--frame", default=None, help="I2V 首帧图")
    p.add_argument("--prompt", default="slow cinematic push-in, subtle motion, cinematic lighting")
    p.add_argument("--duration", type=float, default=1.4)
    p.add_argument("--name", default=None)

    p = sub.add_parser("compose", help="多段合成成片")
    p.add_argument("--clips", required=True, help="逗号分隔的视频路径")
    p.add_argument("--out", default="output/cli_compose.mp4")
    p.add_argument("--bgm", default=None)
    p.add_argument("--bgm-volume", type=float, default=0.2)

    p = sub.add_parser("compose-story2", help="story2 素材合成成片")
    p.add_argument("--bgm", default=None)
    p.add_argument("--no-subtitles", action="store_true")

    args = parser.parse_args()
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "render":
        return cmd_render(args)
    if args.cmd == "compose":
        return cmd_compose(args)
    if args.cmd == "compose-story2":
        return cmd_compose_story2(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
