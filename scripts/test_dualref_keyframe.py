"""资产锁定 A：双参考关键帧测试。IPAdapterFaceID(叶玄机脸) + IPAdapter(药铺场景) → SDXL 生成一镜。"""
import json, time, urllib.request, os, sys

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
WIDTH, HEIGHT = 832, 1216
SEED = 20241234
STEPS, CFG = 28, 6.0

PROMPT = ("a young Chinese man with short dark hair, calm gaze, in a dark teal cotton jacket, standing "
          "at the counter of an old Chinese herbal medicine shop, rows of dark wooden apothecary cabinets "
          "with jars, a brass scale, dim warm lantern light, cinematic film still, photorealistic, 8k")
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")
CHAR_IMG = "asset_char_yexuanji.png"
SCENE_IMG = "asset_scene_qiantang.png"

wf = {
    "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
    "charimg": {"class_type": "LoadImage", "inputs": {"image": CHAR_IMG}},
    "sceneimg": {"class_type": "LoadImage", "inputs": {"image": SCENE_IMG}},
    "ul_face": {"class_type": "IPAdapterUnifiedLoader", "inputs": {
        "model": ["ckpt", 0], "preset": "PLUS FACE (portraits)"}},
    "face": {"class_type": "IPAdapterFaceID", "inputs": {
        "model": ["ul_face", 0], "ipadapter": ["ul_face", 1], "image": ["charimg", 0],
        "weight": 0.8, "weight_faceidv2": 0.8, "combine_embeds": "concat",
        "weight_type": "linear", "embeds_scaling": "V only", "start_at": 0.0, "end_at": 1.0}},
    "ul_scene": {"class_type": "IPAdapterUnifiedLoader", "inputs": {
        "model": ["face", 0], "preset": "PLUS (high strength)"}},
    "scene": {"class_type": "IPAdapter", "inputs": {
        "model": ["ul_scene", 0], "ipadapter": ["ul_scene", 1], "image": ["sceneimg", 0],
        "weight": 0.7, "start_at": 0.0, "end_at": 1.0, "weight_type": "style transfer"}},
    "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": PROMPT}},
    "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": NEG}},
    "lat": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
    "ks": {"class_type": "KSampler", "inputs": {
        "model": ["scene", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
        "seed": SEED, "steps": STEPS, "cfg": CFG, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
    "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
    "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "dualref_test"}},
}


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


res = post("/prompt", {"prompt": wf, "client_id": "dualref"})
pid = res["prompt_id"]
print("prompt_id =", pid, flush=True)
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
            print("EXEC ERROR:", json.dumps(msgs)[:1800], flush=True)
            sys.exit(1)
        if st.get("completed"):
            outs = hist[pid].get("outputs", {})
            img = None
            for k, v in outs.items():
                if "images" in v:
                    img = v["images"][0]
                    break
            if img:
                src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                dest = r"D:\novel-to-video-codex\output\dualref_test.png"
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                import shutil
                shutil.copyfile(src, dest)
                print("SAVED:", dest, round(time.time() - t0, 1), "s", flush=True)
                sys.exit(0)
    if time.time() - t0 > 400:
        print("TIMEOUT", flush=True)
        sys.exit(1)
