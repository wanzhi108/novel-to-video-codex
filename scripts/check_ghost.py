"""查 ComfyUI 队列 running=1 的详情 + 是否真有活动执行。"""
import json
import urllib.request

q = json.load(urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=8))
run = q.get("queue_running", [])
print("queue_running count:", len(run))
if run:
    pid, wf = run[0][1], run[0][2]
    print("prompt_id:", pid)
    classes = [v.get("class_type", "?") for v in wf.values() if isinstance(v, dict)]
    from collections import Counter
    c = dict(Counter(classes))
    print("节点类型:", c)
    has_sampler = any("Sampler" in s or "KSampler" in s for s in classes)
    print("含采样节点:", has_sampler)

# 也查 /prompt 看当前队列
try:
    p = json.load(urllib.request.urlopen("http://127.0.0.1:8188/prompt", timeout=8))
    print("\n/prompt:", list(p.keys()))
    ex = p.get("exec_info", {})
    print("exec_info:", {k: ex.get(k) for k in ("queue_remaining", "queue_running", "queue_pending") if k in ex})
except Exception as e:
    print("prompt err:", e)
