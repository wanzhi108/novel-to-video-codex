import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
WEIGHT = 832
HEIGHT = 1216
SEED = 2024
STEPS = 30
CFG = 6.0
CKPT = "RealVisXL_V4.0.safetensors"
PROMPT = ("a young man in a rain-soaked cyberpunk street at night, neon signs, "
          "cinematic lighting, close-up portrait, sharp details, rain drops, "
          "film still, photorealistic, 8k")
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, "
       "bad anatomy, extra fingers, jpeg artifacts")

wf = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": PROMPT}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": NEG}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": WEIGHT, "height": HEIGHT, "batch_size": 1}},
    "5": {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
        "latent_image": ["4", 0], "seed": SEED, "steps": STEPS, "cfg": CFG,
        "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "t2i_kf"}},
}

def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

res = post("/prompt", {"prompt": wf, "client_id": "t2ikf"})
pid = res["prompt_id"]
print("prompt_id =", pid)

def queue_running():
    try:
        with urllib.request.urlopen(BASE + "/queue", timeout=30) as r:
            q = json.loads(r.read().decode())
        return len(q["queue_running"])
    except Exception:
        return -1

t0 = time.time()
while True:
    time.sleep(3)
    run = queue_running()
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
            print("EXEC ERROR:", json.dumps(msgs)[:1200]); sys.exit(1)
        if hist[pid]["status"].get("completed"):
            outs = hist[pid].get("outputs", {})
            img = None
            for k, v in outs.items():
                if "images" in v:
                    img = v["images"][0]
                    break
            if img:
                src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                dest = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\t2i_kf.png"
                shutil.copyfile(src, dest)
                proj = r"D:\novel-to-video-codex\output\t2i_kf.png"
                os.makedirs(os.path.dirname(proj), exist_ok=True)
                shutil.copyfile(src, proj)
                print("SAVED input/t2i_kf.png =", dest, "size=", os.path.getsize(dest))
                print("SAVED project =", proj)
                print("elapsed_min =", round((time.time() - t0) / 60, 1), "WxH =", img.get("width"), img.get("height"))
                sys.exit(0)
    if run == 0 and hist and pid not in hist:
        print("QUEUE_EMPTY but no history? waiting...")
    if time.time() - t0 > 900:
        print("TIMEOUT 15min"); sys.exit(1)
