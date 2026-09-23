"""查 ComfyUI 正在处理的任务 + 是否有死循环迹象。"""
import json
import urllib.request

# 队列
for ep in ["/queue", "/prompt"]:
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8188" + ep, timeout=8))
        if ep == "/queue":
            print(f"[queue] running={len(d.get('queue_running', []))} pending={len(d.get('queue_pending', []))}")
            for run in d.get("queue_running", [])[:2]:
                pid, wf = run[1], run[2]
                classes = [v.get("class_type", "?") for v in wf.values() if isinstance(v, dict)]
                from collections import Counter
                print(f"  running {pid[:20]} 节点: {dict(Counter(classes))}")
        else:
            ex = d.get("exec_info", {})
            print(f"[prompt] queue_remaining={ex.get('queue_remaining')}")
    except Exception as e:
        print(ep, "ERR:", e)

# 最近 history
try:
    h = json.load(urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=8))
    keys = list(h.keys())
    print(f"\n[history] {len(keys)} 任务")
    if keys:
        latest = h[keys[0]]
        print(f"  最新 {latest['prompt_id'][:20] if 'prompt_id' in latest else keys[0][:20]} "
              f"status={latest.get('status', {}).get('status_str')} completed={latest.get('status', {}).get('completed')}")
except Exception as e:
    print("history err:", e)
