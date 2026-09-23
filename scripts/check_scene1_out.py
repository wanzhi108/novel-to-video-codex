"""查场景 1 的实际产物文件 + 工业引擎提交的 3 个任务是否真成功出片。"""
import os
import json
import urllib.request
from pathlib import Path

out = Path(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4"))
# 场景 1 目录下所有 mp4/png
sc1 = out / "scene_001"
print("=== scene_001 产物 ===")
if sc1.exists():
    for f in sorted(sc1.glob("*")):
        print(f"  {f.name:45s} {f.stat().st_size/1024:.0f}KB {f.stat().st_mtime and __import__('datetime').datetime.fromtimestamp(f.stat().st_mtime).strftime('%H:%M:%S')}")

# 查 ComfyUI history 中 e06d22fd / 364b6b65 / fc3dba96 的输出文件
d = json.load(urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=8))
print("\n=== ComfyUI history 中工业引擎任务输出 ===")
for k in list(d.keys()):
    if k[:8] in ("e06d22fd", "364b6b65", "fc3dba96"):
        e = d[k]
        outs = e.get("outputs", {})
        files = []
        for nid, node_out in outs.items():
            for key in ("gifs", "videos", "images"):
                for item in node_out.get(key, []):
                    files.append(item.get("filename", ""))
        print(f"  {k[:12]} status={e.get('status',{}).get('status_str')} files={files[:3]}")
