from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent

import json
p = str(_ROOT / "comfyui" / "obj_info_raw.json")
d = json.load(open(p, encoding="utf-8-sig"))
for n in ["WanVideoModelLoader", "LoadWanVideoT5TextEncoder"]:
    info = d[n]
    for section in ["required", "optional"]:
        for name, spec in info["input"].get(section, {}).items():
            if name in ("model", "model_name"):
                opts = spec[0] if isinstance(spec, list) else spec
                if isinstance(opts, list):
                    for o in opts:
                        if isinstance(o, str) and ("I2V" in o or "umt5" in o):
                            print(n, ".", name, ":", o)
