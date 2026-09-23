"""方案B：把 5 个带字幕的场景拼接成预告片段（xfade 转场）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

from post.compose import concat_xfade  # noqa: E402

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
clips = [OUT / f"scene_00{i}" / f"scene_00{i}_subbed.mp4" for i in range(1, 6)]
# 只保留存在的
clips = [c for c in clips if c.exists()]
print(f"待拼接场景: {len(clips)}")
final = OUT / "preview_1-5.mp4"


async def main():
    await concat_xfade(clips, final, "fade")
    if final.exists():
        print(f"预告片段已生成: {final} ({final.stat().st_size//1024}KB)")
    else:
        print("拼接失败")


import asyncio  # noqa: E402
asyncio.run(main())
