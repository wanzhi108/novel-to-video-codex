"""基于官方 Wan2.2 I2V 模板，改成 GGUF + 你的 umt5 + 低分辨率，输出适配工作流。"""
import json
from pathlib import Path

src = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper\example_workflows\wanvideo2_2_I2V_A14B_example_WIP.json")
w = json.loads(src.read_text(encoding="utf-8"))

GGUF = "Wan2.2-Animate-14B-Q4_K_M.gguf"
UMT5 = "umt5-xxl-enc-bf16.safetensors"

for n in w["nodes"]:
    t = n["type"]
    if t == "WanVideoModelLoader":
        wv = n["widgets_values"]
        if isinstance(wv, list) and len(wv) > 1:
            wv[0] = GGUF           # 模型名 → GGUF
        print(f"  node {n['id']} WanVideoModelLoader → {n['widgets_values'] if n.get('widgets_values') else wv}")
    elif t == "CLIPLoader":
        wv = n["widgets_values"]
        if isinstance(wv, list) and len(wv) > 0:
            wv[0] = UMT5
        print(f"  node {n['id']} CLIPLoader → {n['widgets_values']}")
    elif t == "WanVideoImageToVideoEncode":
        wv = n.get("widgets_values")
        if isinstance(wv, list) and len(wv) >= 2:
            wv[0], wv[1] = 672, 480   # 低分辨率
        print(f"  node {n['id']} I2V encode → {n['widgets_values']}")

out = Path(r"D:\novel-to-video-codex\comfyui\wan22_gguf_lowvram.json")
w["workflow_name"] = "wan22_gguf_lowvram"
out.write_text(json.dumps(w, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n✅ 适配工作流已保存: {out}")
