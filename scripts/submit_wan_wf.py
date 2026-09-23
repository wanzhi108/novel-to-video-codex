"""UI workflow → API prompt 转换 + 提交（用官方 Wan2.2 模板改模型名）。"""
import json
import urllib.request
from pathlib import Path


def convert_workflow_to_prompt(wf):
    """ComfyUI UI 工作流 → API prompt（处理 links）。"""
    # links: [id, from_node, from_slot, to_node, to_slot, type]  (6元组) 或带 desc
    links = {}
    for l in wf.get("links", []):
        # 兼容链接格式：[link_id, from_node, from_slot, to_node, to_slot, type]
        if isinstance(l, list) and len(l) >= 4:
            links[l[0]] = (l[1], l[2])  # link_id -> (from_node, from_slot)

    prompt = {}
    for n in wf["nodes"]:
        node_type = n["type"]
        if node_type == "Note":
            continue  # Note 是纯说明文本，不参与执行
        nid = str(n["id"])
        inputs = {}
        # 1) 从 inputs 字段的 link 提取
        for inp in n.get("inputs", []):
            if "link" in inp and inp["link"] is not None and inp["link"] in links:
                fn, fs = links[inp["link"]]
                inputs[inp["name"]] = [str(fn), fs]
        # 2) widgets_values 按顺序填入（对无 link 的输入）
        if "widgets_values" in n:
            widgets = n["widgets_values"]
            # 简单：把 widgets 作为额外 inputs（需知道顺序，这里保守跳过，用节点默认）
        prompt[nid] = {"class_type": node_type, "inputs": inputs}
    return prompt


def submit(prompt):
    payload = {"prompt": prompt}
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read())
    except Exception as e:
        body = e.read().decode() if hasattr(e, "read") else str(e)
        return {"error": body[:500]}


# 用官方模板
wf = json.loads(Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json").read_text(encoding="utf-8"))
prompt = convert_workflow_to_prompt(wf)
res = submit(prompt)
print("结果:", json.dumps(res, ensure_ascii=False)[:300])
