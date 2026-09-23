"""查 WanVideoModelLoader / WanVideoVAELoader / WanVideoSampler 真实必填字段。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8188"

for node in ["WanVideoModelLoader", "WanVideoVAELoader", "WanVideoSampler", "WanVideoTextEncode", "WanVideoImageToVideoEncode", "WanVideoDecode"]:
    try:
        d = json.load(urllib.request.urlopen(f"{BASE}/object_info/{node}", timeout=15))
        info = d.get(node, {})
        req = info.get("input", {}).get("required", {})
        opt = info.get("input", {}).get("optional", {})
        print(f"\n=== {node} ===")
        print("  required:", list(req.keys()))
        print("  optional:", list(opt.keys())[:6])
    except Exception as e:
        print(f"{node}: ERR {str(e)[:60]}")
