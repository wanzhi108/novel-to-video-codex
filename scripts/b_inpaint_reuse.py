"""B: 主背景复用 + inpaint 重绘。
用同一张药铺主背景(asset_scene_qiantang.png)做底，只对遮罩区域 inpaint 重绘主体，
背景其余部分像素级保留 —— 实现"同一主背景、换主体/细节"。
"""
import json, time, urllib.request, shutil, os, sys
from PIL import Image, ImageDraw

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
LORA = "ykf_scene.safetensors"
MASTER = "asset_scene_qiantang.png"      # 药铺主背景
W, H = 832, 1216
STEPS, CFG = 30, 6.5
COMFY_INPUT = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input"
OUT = r"D:\novel-to-video-codex\output\b_inpaint"
os.makedirs(OUT, exist_ok=True)


def make_mask(name, box, feather=0):
    """生成遮罩 PNG：黑底白区（白=要重绘区域）。"""
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    d.rectangle(box, fill=255)
    p = os.path.join(COMFY_INPUT, name)
    img.convert("RGB").save(p)
    print("mask ->", p, box, flush=True)
    return name


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def run(name, prompt, mask_name, seed, grow=8):
    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ckpt", 0], "lora_name": LORA, "strength_model": 0.7}},
        "bg": {"class_type": "LoadImage", "inputs": {"image": MASTER}},
        "mk": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "m2m": {"class_type": "ImageToMask", "inputs": {"image": ["mk", 0], "channel": "red"}},
        "vaeenc": {"class_type": "VAEEncodeForInpaint", "inputs": {
            "pixels": ["bg", 0], "vae": ["ckpt", 2], "mask": ["m2m", 0], "grow_mask_by": grow}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text":
            "low quality, blurry, worst quality, watermark, deformed, bad anatomy, extra fingers, cartoon, anime"}},
        "ks": {"class_type": "KSampler", "inputs": {
            "model": ["lora", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["vaeenc", 0],
            "seed": seed, "steps": STEPS, "cfg": CFG, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        # 关键：遮罩外用原主背景贴回 → 背景像素级 100% 保留
        "comp": {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["bg", 0], "source": ["dec", 0], "x": 0, "y": 0,
            "resize_source": False, "mask": ["m2m", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["comp", 0], "filename_prefix": name}},
    }
    res = post("/prompt", {"prompt": wf, "client_id": "binp"})
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
                print(f"  ✗ {name} ERR {json.dumps(st.get('messages', []))[:500]}", flush=True)
                return False
            if st.get("completed"):
                outs = hist[pid].get("outputs", {})
                img = None
                for k, v in outs.items():
                    if "images" in v:
                        img = v["images"][0]; break
                if img:
                    src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                    dest = os.path.join(OUT, f"{name}.png")
                    shutil.copyfile(src, dest)
                    print(f"  ✓ {name} ({round(time.time()-t0,1)}s) -> {dest}", flush=True)
                    return True
        if time.time() - t0 > 400:
            print(f"  ✗ {name} TIMEOUT", flush=True)
            return False


def main():
    # 主背景上"人站立"的区域（下半中央）
    m1 = make_mask("b_mask_char.png", (250, 330, 600, 1216))
    # 主背景上"柜台放物件"的区域（右中）
    m2 = make_mask("b_mask_obj.png", (430, 640, 780, 980))

    run("b1_char", "a young Chinese man with short dark hair, calm gaze, in a dark teal cotton jacket, "
                   "standing at the counter of an old herbal medicine shop, weighing herbs, cinematic, photorealistic, 8k",
        m1, seed=20260101)
    run("b2_obj", "an old brass scale with copper pans and a mound of dried green herbs on the dark wooden counter, "
                  "a small brass weight beside it, warm lantern light, cinematic, photorealistic, 8k",
        m2, seed=20260102)


if __name__ == "__main__":
    main()
