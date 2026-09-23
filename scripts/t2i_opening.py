"""生成漫剧开场镜头的关键帧（黎明前黑暗药铺 / 叶玄机摸黑），RealVisXL 竖屏。
产物: ComfyUI input/t2i_opening_kf.png + output/t2i_opening_kf.png
"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
WIDTH, HEIGHT = 832, 1216
SEED = 2024
STEPS, CFG = 30, 6.0
CKPT = "RealVisXL_V4.0.safetensors"
PROMPT = ("interior of an old Chinese herbal medicine shop before dawn, dim moody lighting, "
          "a young dark-haired man in a worn dark cotton jacket moving quietly through the darkness, "
          "rows of dark wooden apothecary cabinets, a brass scale on the long counter, bundled dried herbs, "
          "cool blue shadowy tones with a faint warm candle glow, cinematic film still, photorealistic, 8k")
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")

wf = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": PROMPT}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": NEG}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
    "5": {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
        "latent_image": ["4", 0], "seed": SEED, "steps": STEPS, "cfg": CFG,
        "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "t2i_opening_kf"}},
}

def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

res = post("/prompt", {"prompt": wf, "client_id": "t2iopening"})
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
        if st.get("completed"):
            outs = hist[pid].get("outputs", {})
            img = None
            for k, v in outs.items():
                if "images" in v:
                    img = v["images"][0]; break
            if img:
                src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                dest = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\t2i_opening_kf.png"
                shutil.copyfile(src, dest)
                proj = r"D:\novel-to-video-codex\output\t2i_opening_kf.png"
                os.makedirs(os.path.dirname(proj), exist_ok=True)
                shutil.copyfile(src, proj)
                print("SAVED input/t2i_opening_kf.png size=", os.path.getsize(dest))
                print("elapsed_min =", round((time.time() - t0) / 60, 1))
                sys.exit(0)
    if time.time() - t0 > 300:
        print("TIMEOUT 5min"); sys.exit(1)
