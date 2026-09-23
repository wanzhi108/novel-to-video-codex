"""场景明细。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
for x in s["scenes"]:
    st = x["status"]
    print(f"  #{x['id']:2d} {str(x['title'])[:16]:18s} status={st:15s} "
          f"img={'Y' if x['image_path'] else 'N'} vid={'Y' if x['video_path'] else 'N'} "
          f"err={(x['error_msg'] or '')[:30]}")
