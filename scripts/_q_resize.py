import json
d = json.load(open(r"D:\novel-to-video-codex\comfyui\obj_info_raw.json", encoding="utf-8-sig"))
for n in ["ImageResizeKJv2", "ImageScale", "ImageScaleBy"]:
    if n in d:
        print("==", n, "==")
        for sect, v in d[n]["input"].items():
            for name, spec in v.items():
                t = spec.get("type") if isinstance(spec, dict) else spec
                df = spec.get("default", "") if isinstance(spec, dict) else ""
                print("  %s.%s: %s def=%s" % (sect, name, t, df))
