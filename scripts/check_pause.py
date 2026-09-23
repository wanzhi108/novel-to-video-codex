"""检查暂停后的场景状态与 job 状态。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
print("=== 场景 1-8 状态 ===")
for x in s["scenes"][:8]:
    print(f"  #{x['id']} {str(x['title'])[:12]:14s} {x['status']:16s} "
          f"img={'Y' if x['image_path'] else 'N'} vid={'Y' if x['video_path'] else 'N'}")

d = json.load(urllib.request.urlopen("http://localhost:8190/api/jobs", timeout=8))
for x in d["jobs"]:
    if x["id"] == "cfb52fe4":
        print("\njob status:", x["status"], "done:", x["completed_scenes"], "/", x["scene_count"])
