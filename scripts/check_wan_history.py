"""查 Wan 2.2 prompt 55527ef7 的执行结果。"""
import json
import urllib.request

d = json.load(urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=10))
found = False
for k, v in d.items():
    if k.startswith("55527ef7"):
        st = v.get("status", {})
        print(f"prompt {k[:20]}: status={st.get('status_str')} completed={st.get('completed')}")
        if st.get("status_str") in ("success", "completed"):
            for nid, node_out in v.get("outputs", {}).items():
                for key in ("images", "gifs", "videos"):
                    for item in node_out.get(key, []):
                        print(f"  输出: {item.get('filename')} ({item.get('type')})")
        found = True
        break
if not found:
    print("未找到 55527ef7。最近 history:")
    for k in list(d.keys())[:3]:
        st = d[k].get("status", {})
        print(f"  {k[:20]}: {st.get('status_str')}")
