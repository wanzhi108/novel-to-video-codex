"""检查运行中任务 6b947ab9 的类型与 ComfyUI 状态。"""
import json
import urllib.request


def get(url):
    try:
        return json.load(urllib.request.urlopen(url, timeout=8))
    except Exception as e:
        return {"_err": str(e)[:80]}


# 1. queue 里运行中的完整条目（含 workflow 类型）
q = get("http://127.0.0.1:8188/queue")
for run in q.get("queue_running", []):
    pid, workflow = run[1], run[2]
    print(f"运行中 prompt: {pid}")
    # workflow 是 {node_id: {class_type, inputs}}
    classes = [v.get("class_type", "?") for v in workflow.values() if isinstance(v, dict)]
    from collections import Counter
    print("  节点类型分布:", dict(Counter(classes)))
    # 找 checkpoint / 采样参数
    for nid, node in workflow.items():
        ct = node.get("class_type", "")
        if ct in ("CheckpointLoaderSimple", "LoraLoader"):
            print(f"    {ct}: {node.get('inputs', {})}")

# 2. system_stats 看设备状态
st = get("http://127.0.0.1:8188/system_stats")
if "_err" not in st:
    d = st.get("devices", [{}])[0]
    print("\nsystem_stats:", d.get("name"), "vram_free:", d.get("vram_free"), "vram_total:", d.get("vram_total"))
