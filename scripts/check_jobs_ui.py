"""检查 /api/jobs 返回的 job 字段是否完整（TaskManager 渲染依赖）。"""
import json
import urllib.request

data = json.load(urllib.request.urlopen("http://localhost:8190/api/jobs", timeout=8))
jobs = data.get("jobs", [])
print(f"jobs 数: {len(jobs)}")
if jobs:
    j0 = jobs[0]
    print("job[0] keys:", list(j0.keys()))
    # TaskManager 渲染可能用到的字段
    for k in ["job_id", "novel_title", "current_step", "scenes_count", "done_count", "status", "modified", "error"]:
        print(f"  {k}: {repr(j0.get(k))[:50]}")
