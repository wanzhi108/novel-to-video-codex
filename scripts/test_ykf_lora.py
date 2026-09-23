"""C: 验证训练好的药铺场景 LoRA。用 RealVisXL + ykf_scene LoRA + 触发词 'sks chinese herbal medicine shop' 生成。"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
LORA = "ykf_scene.safetensors"
WIDTH, HEIGHT = 832, 1216
SEED = 20261234
STEPS, CFG = 28, 6.0
PROMPT = ("a photo of sks chinese herbal medicine shop, a young man in a dark teal cotton jacket working at the "
          "counter, rows of dark wooden apothecary cabinets with jars, a brass scale, dim warm lantern light, "
          "cinematic film still, photorealistic, 8k")
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, cartoon, anime")

wf = {
    "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
    "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ckpt", 0], "lora_name": LORA, "strength_model": 1.0}},
    "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": PROMPT}},
    "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": NEG}},
    "lat": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
    "ks": {"class_type": "KSampler", "inputs": {
        "model": ["lora", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
        "seed": SEED, "steps": STEPS, "cfg": CFG, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
    "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
    "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "lora_test"}},
}


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


res = post("/prompt", {"prompt": wf, "client_id": "loratest"})
pid = res["prompt_id"]
print("prompt_id =", pid, flush=True)
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
            print("EXEC ERROR:", json.dumps(st.get("messages", []))[:1500], flush=True)
            sys.exit(1)
        if st.get("completed"):
            outs = hist[pid].get("outputs", {})
            img = None
            for k, v in outs.items():
                if "images" in v:
                    img = v["images"][0]; break
            if img:
                src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                dest = r"D:\novel-to-video-codex\output\lora_test.png"
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(src, dest)
                print("SAVED:", dest, round(time.time()-t0, 1), "s", flush=True)
                sys.exit(0)
    if time.time() - t0 > 400:
        print("TIMEOUT", flush=True)
        sys.exit(1)
