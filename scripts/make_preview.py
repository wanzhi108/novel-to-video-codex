"""生成前 6 个分镜的图文展示页（HTML，嵌入关键帧图）。"""
import os
import json
import urllib.request
from pathlib import Path

OUT = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
SHOW = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\storyboard_preview.html"))

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
scenes = s["scenes"]

def esc(t):
    if not t:
        return ""
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("\n", "<br>"))

cards = []
for x in scenes[:6]:
    sid = x["id"]
    d = OUT / f"scene_{sid:03d}"
    # 找关键帧图（优先 ipadapter 最新的 / shot）
    img_rel = ""
    img_file = ""
    if d.exists():
        pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in pngs:
            if "ipadapter" in p.name or "shot" in p.name:
                img_file = str(p)
                # 相对 output 目录的 URL，浏览器 file:// 可显示
                img_rel = f"file:///{str(p).replace(chr(92), '/')}"
                break
        if not img_file:
            for p in pngs[:1]:
                img_file = str(p)
                img_rel = f"file:///{str(p).replace(chr(92), '/')}"
    status = x.get("status", "")
    badge = {"done": "✅ 已完成", "generating_vid": "🔵 生成中", "pending": "⏳ 等待中",
             "error": "❌ 错误"}.get(status, status)
    card = f"""
    <div class="card">
      <div class="thumb">
        {f'<img src="{img_rel}" alt="场景{sid}关键帧"/>' if img_rel else '<div class="noimg">暂无图</div>'}
      </div>
      <div class="info">
        <div class="head">
          <h2>场景 {sid} · {esc(x.get("title"))}</h2>
          <span class="badge">{badge}</span>
        </div>
        <p class="sub">{esc(x.get("subtitle_text"))}</p>
        <p class="desc">{esc((x.get("description") or "")[:300])}</p>
        <div class="meta">
          <span>🎬 {esc(x.get("camera"))}</span>
          <span>🎭 {esc(x.get("mood"))}</span>
          <span>⏱ {x.get("duration")}s</span>
          <span>👤 {esc((x.get("characters") or "")[:40])}</span>
        </div>
      </div>
    </div>"""
    cards.append(card)

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>分镜预览 · 《深夜赶工》</title>
<style>
  body {{ font-family: "Microsoft YaHei UI", sans-serif; background:#0d0d14; color:#e8e4da; margin:0; padding:24px; }}
  h1 {{ text-align:center; color:#c8a45c; letter-spacing:2px; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  .card {{ display:flex; gap:16px; background:#16161f; border:1px solid #262633; border-radius:10px;
           padding:14px; margin-bottom:18px; }}
  .thumb {{ flex-shrink:0; width:220px; }}
  .thumb img {{ width:100%; border-radius:6px; display:block; }}
  .noimg {{ width:220px; height:390px; background:#1d1d2a; border-radius:6px; display:flex;
            align-items:center; justify-content:center; color:#555; }}
  .info {{ flex:1; min-width:0; }}
  .head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
  h2 {{ margin:0 0 6px; font-size:18px; color:#f0ead8; }}
  .badge {{ font-size:12px; white-space:nowrap; }}
  .sub {{ color:#c8a45c; font-size:14px; margin:6px 0; font-weight:600; }}
  .desc {{ color:#a09a8c; font-size:13px; line-height:1.6; margin:6px 0; }}
  .meta {{ display:flex; gap:12px; flex-wrap:wrap; font-size:12px; color:#6f6a5e; margin-top:8px; }}
</style></head><body>
<div class="wrap">
  <h1>🎬 《深夜赶工》 分镜预览（前 6 镜）</h1>
  {''.join(cards)}
  <p style="text-align:center; color:#555; font-size:12px; margin-top:20px;">
    关键帧图引用自 output/cfb52fe4/scene_0XX/ · 视频见 *_final.mp4</p>
</div></body></html>"""

SHOW.write_text(html, encoding="utf-8")
print(f"展示页已生成: {SHOW}")
