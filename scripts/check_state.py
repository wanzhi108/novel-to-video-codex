"""检查项目状态。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
done = [x for x in s["scenes"] if x["status"] in ("done", "completed")]
print(f"完成 {len(done)}/{len(s['scenes'])}")
for x in s["scenes"]:
    if x["status"] in ("done", "completed"):
        print(f"  #{x['id']} {str(x['title'])[:12]:14s} final={'Y' if x.get('final_video_path') else 'N'}")
