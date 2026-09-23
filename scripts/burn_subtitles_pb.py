"""方案B：给已完成场景1-5成片烧上字幕（用已有的 subtitle_timings + burn_subtitles）。

红果漫剧硬性要求字幕。这些成片有配音时间轴(subtitle_timings)但没烧字幕。
用 post/compose.burn_subtitles 给每个场景成片加 ASS 字幕，产出 _subbed.mp4。
"""
import os
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"D:\novel-to-video-codex")

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))

# 场景的 subtitle_timings 是 [{start,end,text,speaker}] → 转成 Timing + texts
def load_timings(scene):
    tim = scene.get("subtitle_timings") or []
    t_list = [{"start": t["start"], "end": t["end"]} for t in tim if t.get("start") is not None]
    texts = [t.get("text", "") for t in tim]
    return t_list, texts


scenes = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))["scenes"]

from post.subtitles import Timing  # noqa: E402
from post.compose import burn_subtitles  # noqa: E402


async def main():
    results = []
    for sc in scenes[:5]:
        sid = sc["id"]
        d = OUT / f"scene_{sid:03d}"
        # 找成片（final 优先）
        src = None
        for name in [f"scene_{sid:03d}_final.mp4", f"scene_{sid:03d}_with_bgm.mp4"]:
            if (d / name).exists():
                src = d / name
                break
        if not src:
            results.append((sid, "no-src", ""))
            continue
        t_list, texts = load_timings(sc)
        if not t_list or not texts:
            results.append((sid, "no-timings", src.name))
            continue
        # 转 Timing
        timings = [Timing(start=t["start"], end=t["end"]) for t in t_list]
        out = d / f"scene_{sid:03d}_subbed.mp4"
        try:
            await burn_subtitles(src, out, texts, timings)
            results.append((sid, "OK", out.name))
        except Exception as e:
            results.append((sid, "FAIL", str(e)[:80]))

    for sid, st, info in results:
        print(f"  场景{sid}: {st}  {info}")

import asyncio  # noqa: E402
asyncio.run(main())
print("SUBTITLE BURN DONE")
