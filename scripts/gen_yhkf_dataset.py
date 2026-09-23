"""C: 自主生成药铺场景训练图数据集（~20张），用于 SDXL LoRA 训练。
用 asset_scene_qiantang 场景参考 + 变化构图/光线/角度生成，保持"同一个药铺"但构图多样。
"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
WIDTH, HEIGHT = 832, 1216
STEPS, CFG = 26, 6.0
SCENE_REF = "asset_scene_qiantang.png"
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime, people, person")
OUT_DIR = r"D:\novel-to-video-codex\dataset\yhkf"
os.makedirs(OUT_DIR, exist_ok=True)

BASE_PROMPT = ("interior of an old Chinese herbal medicine shop, dark wooden apothecary cabinets with many "
               "glass jars of dried herbs, a long dark wooden counter, brass scales and brass bowls, bundles "
               "of dried herbs, warm lantern light, {variation}, cinematic, photorealistic, 8k")

# 20 种构图/视角/光线变化
VARIATIONS = [
    "wide view down the center aisle of cabinets",
    "view from the back of the shop looking toward the counter",
    "the long wooden counter from a low angle, brass scale prominent",
    "close on a shelf of labeled herb jars",
    "a corner of the shop with stacked herb bundles",
    "the empty wooden counter with a single brass scale",
    "view toward a lattice window with soft light",
    "the apothecary cabinet wall, many drawers below the jars",
    "warm lantern glow over the wooden counter and jars",
    "a brass mortar and pestle on the counter",
    "the shop in warm dim light, deep shadows",
    "cool blue dusk light through the lattice window",
    "close-up of a wooden drawer with cut herbs",
    "the scale pans and brass bowls in the foreground",
    "rows of brown glass bottles on a shelf",
    "the shop front area with hanging bundles of herbs",
    "a stack of wooden boxes labeled with herbs",
    "the counter top with scattered dried peppermint leaves",
    "angled view up at the cabinet shelves lined with jars",
    "the whole shop in a single moody shot, no people",
]


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def gen(idx, variation, seed):
    prompt = BASE_PROMPT.format(variation=variation)
    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "ref": {"class_type": "LoadImage", "inputs": {"image": SCENE_REF}},
        "ul": {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["ckpt", 0], "preset": "PLUS (high strength)"}},
        "ipa": {"class_type": "IPAdapter", "inputs": {
            "model": ["ul", 0], "ipadapter": ["ul", 1], "image": ["ref", 0],
            "weight": 0.35, "start_at": 0.0, "end_at": 1.0, "weight_type": "standard"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": NEG}},
        "lat": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
        "ks": {"class_type": "KSampler", "inputs": {
            "model": ["ipa", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
            "seed": seed, "steps": STEPS, "cfg": CFG, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "ykf_ds"}},
    }
    res = post("/prompt", {"prompt": wf, "client_id": "ykfds"})
    pid = res["prompt_id"]
    t0 = time.time()
    while True:
        time.sleep(3)
        hist = None
        try:
            with urllib.request.urlopen(BASE + "/history/" + pid, timeout=40) as r:
                hist = json.loads(r.read().decode())
        except Exception:
            hist = None
        if hist and pid in hist:
            st = hist[pid]["status"]
            if any(m[0] == "execution_error" for m in st.get("messages", [])):
                print(f"  ✗ {idx} ERR {json.dumps(st.get('messages', []))[:300]}", flush=True)
                return False
            if st.get("completed"):
                outs = hist[pid].get("outputs", {})
                img = None
                for k, v in outs.items():
                    if "images" in v:
                        img = v["images"][0]; break
                if img:
                    src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                    dest = os.path.join(OUT_DIR, f"ykf_{idx:02d}.png")
                    shutil.copyfile(src, dest)
                    print(f"  ✓ {idx:02d} {variation[:28]}... ({round(time.time()-t0,1)}s)", flush=True)
                    return True
        if time.time() - t0 > 300:
            print(f"  ✗ {idx} TIMEOUT", flush=True)
            return False


def main():
    for i, v in enumerate(VARIATIONS, 1):
        gen(i, v, seed=20252000 + i)


if __name__ == "__main__":
    main()
