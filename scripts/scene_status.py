"""查场景视频/成片状态。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
for x in s["scenes"]:
    print(f"#{x['id']:2d} {x['status'][:14]:14s} "
          f"vid={'Y' if x.get('video_path') else '-'} final={'Y' if x.get('final_video_path') else '-'}")
