"""触发场景6-15生成 + 检查状态。"""
import json
import urllib.request

req = urllib.request.Request("http://localhost:8190/api/regenerate-images?job_id=cfb52fe4", method="POST")
try:
    r = urllib.request.urlopen(req, timeout=10)
    print("regenerate-images:", r.status, r.read().decode()[:150])
except Exception as e:
    body = e.read().decode() if hasattr(e, "read") else str(e)
    print("ERR:", body[:250])

import time
time.sleep(8)

# ComfyUI 队列
try:
    q = json.load(urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=8))
    print("queue running:", len(q.get("queue_running", [])), "pending:", len(q.get("queue_pending", [])))
except Exception as e:
    print("comfy off", str(e)[:60])

# 场景状态
try:
    s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
    for x in s["scenes"]:
        print(f"  #{x['id']:2d} {x['status']:16s} {'img' if x['image_path'] else '--'} {'vid' if x['video_path'] else '--'}")
except Exception as e:
    print("scenes err", str(e)[:60])
