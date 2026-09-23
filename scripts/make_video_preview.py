"""生成分镜视频展示页（嵌入 video 播放前 5 个已完成场景成片）。"""
import os
import json
import urllib.request
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
SHOW = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\storyboard_video_preview.html"))

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
scenes = s["scenes"]

def esc(t):
    if not t:
        return ""
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("\n", "<br>"))

def file_url(p):
    return f"file:///{str(p).replace(chr(92), '/')}"

cards = []
for x in scenes[:5]:
    sid = x["id"]
    d = OUT / f"scene_{sid:03d}"
    # 找成片视频：优先 final，其次 with_bgm，再 sfx，再 industrial
    vid = None
    for name in [f"scene_{sid:03d}_final.mp4", f"scene_{sid:03d}_with_bgm.mp4",
                 f"scene_{sid:03d}_sfx.mp4", f"industrial_{sid}.mp4"]:
        if (d / name).exists():
            vid = d / name
            break
    if not vid:
        continue
    # 找关键帧作 poster
    poster = ""
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in pngs:
        if "ipadapter" in p.name or "shot" in p.name:
            poster = file_url(p)
            break
    status = x.get("status", "")
    badge = {"done": "✅ 已完成", "generating_vid": "🔵 生成中", "pending": "⏳ 等待中",
             "error": "❌ 错误"}.get(status, status)
    card = f"""
    <div class="card">
      <div class="head">
        <h2>场景 {sid} · {esc(x.get("title"))}</h2>
        <span class="badge">{badge}</span>
      </div>
      <video controls preload="metadata" poster="{poster}">
        <source src="{file_url(vid)}" type="video/mp4">
        您的浏览器不支持视频播放
      </video>
      <p class="sub">{esc(x.get("subtitle_text"))}</p>
      <div class="meta">
        <span>🎬 {esc(x.get("camera"))}</span>
        <span>🎭 {esc(x.get("mood"))}</span>
        <span>⏱ {x.get("duration")}s</span>
      </div>
    </div>"""
    cards.append(card)

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>分镜视频预览 · 《深夜赶工》</title>
<style>
  body {{ font-family:"Microsoft YaHei UI",sans-serif; background:#0d0d14; color:#e8e4da; margin:0; padding:24px; }}
  h1 {{ text-align:center; color:#c8a45c; letter-spacing:2px; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  .card {{ background:#16161f; border:1px solid #262633; border-radius:12px; padding:16px; margin-bottom:22px; }}
  .head {{ display:flex; justify-content:space-between; align-items:center; }}
  h2 {{ margin:0; font-size:18px; color:#f0ead8; }}
  .badge {{ font-size:12px; white-space:nowrap; }}
  video {{ width:100%; border-radius:8px; margin:12px 0; background:#000; }}>
  .sub {{ color:#c8a45c; font-size:14px; margin:6px 0; font-weight:600; }}
  .meta {{ display:flex; gap:14px; font-size:12px; color:#6f6a5e; margin-top:6px; flex-wrap:wrap; }}
</style></head><body>
<div class="wrap">
  <h1>🎬 《深夜赶工》 分镜成片预览（前 5 镜）</h1>
  {''.join(cards)}
  <p style="text-align:center; color:#555; font-size:12px;">视频来自 output/cfb52fe4/scene_00X/*_final.mp4 · 点播放可看</p>
</div></body></html>"""

SHOW.write_text(html, encoding="utf-8")
print(f"视频展示页已生成: {SHOW}")
