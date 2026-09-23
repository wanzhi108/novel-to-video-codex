"""解析官方模板关键节点，输出可改的定位信息（模型名/分辨率）。"""
import json
from pathlib import Path

p = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json")
w = json.loads(p.read_text(encoding="utf-8"))

for n in w["nodes"]:
    t = n["type"]
    if t in ("WanVideoModelLoader", "CLIPLoader", "WanVideoVAELoader", "WanVideoImageToVideoEncode",
             "CreateCFGScheduleFloatList", "WanVideoSampler", "WanVideoTextEncode", "ImageResizeKJv2",
             "WanVideoDecode", "VHS_VideoCombine", "LoadImage", "WanVideoSetBlockSwap", "WanVideoBlockSwap"):
        wv = n.get("widgets_values")
        print(f"id={n['id']} {t}: {wv}")
