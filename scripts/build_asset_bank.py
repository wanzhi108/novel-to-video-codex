"""生成资产库：叶玄机标准脸 + 药铺场景主参考（前堂/后院/卧房）。RealVisXL 竖屏。"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
WIDTH, HEIGHT = 832, 1216
STEPS, CFG = 30, 6.0
CKPT = "RealVisXL_V4.0.safetensors"
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")

# 资产清单: 名称 -> prompt
ASSETS = {
    "asset_char_yexuanji": (
        "portrait of a young Chinese man with short dark hair and a calm steady gaze, clean "
        "front-facing head and shoulders, wearing a dark teal cotton jacket, even soft daylight, "
        "cinematic film still, photorealistic, 8k"),
    "asset_scene_qiantang": (
        "wide interior of an old Chinese herbal medicine shop, no people, rows of dark wooden "
        "apothecary cabinets with glass jars, a long dark wooden counter with a brass scale and brass "
        "bowls, bundles of dried herbs, dim warm lantern light, cinematic film still, photorealistic, 8k"),
    "asset_scene_houyuan": (
        "a quiet rustic courtyard of an old Chinese house in the dark before dawn, no people, an old "
        "clay medicine pot on a low stove, a stone well, stacked firewood, cool blue predawn light, "
        "cinematic film still, photorealistic, 8k"),
    "asset_scene_wofang": (
        "a dim dark bedroom of an old Chinese house, no people, a simple wooden bed with a thin quilt, "
        "a small lattice window with cold blue moonlight, worn wooden walls, cinematic film still, "
        "photorealistic, 8k"),
}

OUT_DIR = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input"


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def gen(name, prompt, seed):
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": NEG}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": seed, "steps": STEPS, "cfg": CFG,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": name}},
    }
    res = post("/prompt", {"prompt": wf, "client_id": "assetbank"})
    pid = res["prompt_id"]
    t0 = time.time()
    while True:
        time.sleep(3)
        hist = None
        try:
            with urllib.request.urlopen(BASE + "/history/" + pid, timeout=30) as r:
                hist = json.loads(r.read().decode())
        except Exception:
            hist = None
        if hist and pid in hist:
            st = hist[pid]["status"]
            msgs = st.get("messages", [])
            if any(m[0] == "execution_error" for m in msgs):
                print(f"  ✗ {name} EXEC ERROR: {json.dumps(msgs)[:300]}", flush=True)
                return False
            if st.get("completed"):
                outs = hist[pid].get("outputs", {})
                img = None
                for k, v in outs.items():
                    if "images" in v:
                        img = v["images"][0]; break
                if img:
                    src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                    dest = os.path.join(OUT_DIR, f"{name}.png")
                    shutil.copyfile(src, dest)
                    print(f"  ✓ {name} -> {dest} ({round(os.path.getsize(dest)/1e6,1)}MB, {round(time.time()-t0,1)}s)", flush=True)
                    return True
        if time.time() - t0 > 300:
            print(f"  ✗ {name} TIMEOUT", flush=True)
            return False


def main():
    for i, (name, prompt) in enumerate(ASSETS.items()):
        gen(name, prompt, seed=202400 + i)


if __name__ == "__main__":
    main()
