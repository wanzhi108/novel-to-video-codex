"""生成掌柜标准脸参考（资产库补充）。"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
WIDTH, HEIGHT = 832, 1216
STEPS, CFG = 30, 6.0
CKPT = "RealVisXL_V4.0.safetensors"
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")
PROMPT = ("portrait of a Chinese man around fifty years old, bald head, permanently half-closed sleepy "
          "eyes, a faint tired expression, wearing a faded light blue cotton jacket, head and shoulders, "
          "even soft daylight, cinematic film still, photorealistic, 8k")
SEED = 20241235

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
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "asset_char_zhanggui"}},
}

def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

res = post("/prompt", {"prompt": wf, "client_id": "zgui"})
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
        if any(m[0] == "execution_error" for m in st.get("messages", [])):
            print("EXEC ERROR:", json.dumps(st.get("messages", []))[:800]); sys.exit(1)
        if st.get("completed"):
            outs = hist[pid].get("outputs", {})
            img = None
            for k, v in outs.items():
                if "images" in v:
                    img = v["images"][0]; break
            if img:
                src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                dest = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\asset_char_zhanggui.png"
                shutil.copyfile(src, dest)
                print("SAVED:", dest, round(os.path.getsize(dest)/1e6,1), "MB", round(time.time()-t0,1), "s", flush=True)
                sys.exit(0)
    if time.time() - t0 > 300:
        print("TIMEOUT"); sys.exit(1)
