"""查官方模板 WanVideoSampler 的输入接线（哪个节点供 text/image embeds）。"""
import json
from pathlib import Path

p = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json")
wf = json.loads(p.read_text(encoding="utf-8"))

# 建 node_id -> type 映射
id2type = {n["id"]: n["type"] for n in wf["nodes"]}

# WanVideoSampler 节点（id 27/90）
for n in wf["nodes"]:
    if n["type"] == "WanVideoSampler":
        print(f"\n=== WanVideoSampler id={n['id']} ===")
        for inp in n.get("inputs", []):
            print(f"  input {inp['name']}: link={inp.get('link')}")
        # 从 links 找这些 input 的来源
        for l in wf.get("links", []):
            if isinstance(l, list) and len(l) >= 6 and l[3] == n["id"]:
                print(f"    link{l[0]}: node{l[1]}({id2type.get(l[1])}) slot{l[2]} -> in {l[4]}")

# WanVideoTextEncode / TextEmbedBridge 输出
print("\n=== 文本相关节点 ===")
for n in wf["nodes"]:
    if n["type"] in ("WanVideoTextEncode", "WanVideoTextEmbedBridge", "WanVideoImageToVideoEncode"):
        print(f"id={n['id']} {n['type']} inputs={[i['name'] for i in n.get('inputs',[])]} out_types={[o['type'] for o in n.get('outputs',[])]}")
