"""查模板 WanVideoImageToVideoEncode(id89) 的输入来源。"""
import json
from pathlib import Path

p = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json")
wf = json.loads(p.read_text(encoding="utf-8"))
id2type = {n["id"]: n["type"] for n in wf["nodes"]}

for n in wf["nodes"]:
    if n["id"] == 89:
        print("=== ImageToVideoEncode(id89) 输入 ===")
        for inp in n.get("inputs", []):
            print(f"  {inp['name']}: link={inp.get('link')}")
        for l in wf.get("links", []):
            if isinstance(l, list) and len(l) >= 6 and l[3] == 89:
                print(f"    link{l[0]}: node{l[1]}({id2type.get(l[1])}) slot{l[2]} -> {l[4]}")
    # 查 TextEncode(id16) 输出到哪
    if n["id"] == 16:
        print("\n=== TextEncode(id16) 输出 ===")
        for o in n.get("outputs", []):
            print(f"  输出 {o['name']} links={o.get('links')}")
