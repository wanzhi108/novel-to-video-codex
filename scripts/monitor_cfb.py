"""监督 cfb52fe4 项目生成进度。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
sc = s["scenes"]
done = [x for x in sc if x["status"] in ("done", "completed")]
gen = [x for x in sc if x["status"] in ("generating", "generating_img", "generating_vid")]
pending = [x for x in sc if x["status"] == "pending"]
print(f"总 {len(sc)} 镜 | done={len(done)} 生成中={len(gen)} pending={len(pending)}")
for x in sc:
    if x["status"] not in ("pending", "done", "completed"):
        print(f"  #{x['id']} {str(x['title'])[:18]:20s} status={x['status']} "
              f"img={'Y' if x['image_path'] else 'N'} vid={'Y' if x['video_path'] else 'N'} "
              f"err={(x['error_msg'] or '')[:40]}")
