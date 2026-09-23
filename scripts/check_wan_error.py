"""查 Wan 2.2 执行 error 的具体信息。"""
import json
import urllib.request

d = json.load(urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=10))
for k, v in d.items():
    if k.startswith("55527ef7"):
        st = v.get("status", {})
        print("status:", st.get("status_str"))
        if "messages" in st:
            for m in st["messages"]:
                print("  msg:", str(m)[:300])
        if "error" in st:
            print("error:", json.dumps(st.get("error"), ensure_ascii=False)[:400])
        break
