"""方案B收尾：给5场景预告片段加BGM，产出完整交付成片。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

from post.compose import mix_bgm  # noqa: E402

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
src = OUT / "preview_1-5.mp4"
bgm = Path(r"D:\novel-to-video-codex\bgm\Horror_Scary.mp3")
final = OUT / "深夜赶工_预告成片.mp4"


async def main():
    if not src.exists():
        print(f"源预告片不存在: {src}")
        return
    print(f"源: {src} ({src.stat().st_size//1024}KB)")
    print(f"BGM: {bgm.name}")
    result = await mix_bgm(src, bgm, final, bgm_volume=0.22, ducking=True)
    if final.exists():
        print(f"✅ 完整成片已生成: {final} ({final.stat().st_size//1024}KB)")
    else:
        print("混音失败")


import asyncio  # noqa: E402
asyncio.run(main())
