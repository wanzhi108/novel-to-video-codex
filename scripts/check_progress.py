"""检查场景生成进度。"""
import json
import urllib.request

s = json.load(urllib.request.urlopen("http://localhost:8190/api/scenes/cfb52fe4", timeout=8))
done = [x for x in s["scenes"] if x["status"] in ("done", "completed")]
gen = [x for x in s["scenes"] if x["status"] not in ("done", "completed", "pending")]
print(f"完成 {len(done)}/15, 生成中 {len(gen)}")
for x in s["scenes"]:
    mark = "done" if x["status"] in ("done", "completed") else ("gen" if x["status"] != "pending" else "..")
    print(f"  #{x['id']:2d} {x['status'][:16]:16s} {mark}")
