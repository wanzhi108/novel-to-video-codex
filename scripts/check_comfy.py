"""检查 ComfyUI history 真实结构（怀疑异常堆积）+ 队列。"""
import json
import urllib.request

for ep in ["/queue", "/history"]:
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8188" + ep, timeout=8))
        if ep == "/queue":
            print("queue keys:", list(d.keys()))
            print("  queue_running:", len(d.get("queue_running", [])), "queue_pending:", len(d.get("queue_pending", [])))
        else:
            print("history type:", type(d).__name__, "len:", len(d))
            if isinstance(d, dict):
                keys = list(d.keys())[:5]
                print("  first keys:", keys)
                for k in keys:
                    e = d[k]
                    st = e.get("status", {}) if isinstance(e, dict) else {}
                    print(f"  {k[:12]} status_str={st.get('status_str')} completed={st.get('completed')}")
    except Exception as e:
        print(ep, "ERR:", type(e).__name__, str(e)[:100])
