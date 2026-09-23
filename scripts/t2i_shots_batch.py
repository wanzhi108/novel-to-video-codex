"""批量生成 shot2-6 的 T2I 关键帧（RealVisXL，竖屏 832x1216）。"""
import json, time, urllib.request, shutil, os, sys

sys.path.insert(0, r"D:\novel-to-video-codex\scripts")
from opening_shots import SHOTS, KF_DIR

BASE = "http://127.0.0.1:8188"
WIDTH, HEIGHT = 832, 1216
SEED = 2024
STEPS, CFG = 30, 6.0
CKPT = "RealVisXL_V4.0.safetensors"
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")

def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def queue_running():
    try:
        with urllib.request.urlopen(BASE + "/queue", timeout=30) as r:
            return len(json.loads(r.read().decode())["queue_running"])
    except Exception:
        return -1

def gen_kf(shot):
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": shot["kf_prompt"]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": NEG}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": SEED, "steps": STEPS, "cfg": CFG,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "t2i_kf_batch"}},
    }
    res = post("/prompt", {"prompt": wf, "client_id": "t2ibatch"})
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
                print(f"  ✗ shot{shot['id']} EXEC ERROR: {json.dumps(msgs)[:300]}", flush=True)
                return False
            if st.get("completed"):
                outs = hist[pid].get("outputs", {})
                img = None
                for k, v in outs.items():
                    if "images" in v:
                        img = v["images"][0]; break
                if img:
                    src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                    dest = KF_DIR / shot["kf_file"]
                    shutil.copyfile(src, dest)
                    print(f"  ✓ shot{shot['id']} 关键帧 {shot['kf_file']} ({round((time.time()-t0),1)}s, {os.path.getsize(dest)}B)", flush=True)
                    return True
        if time.time() - t0 > 300:
            print(f"  ✗ shot{shot['id']} TIMEOUT", flush=True)
            return False

def main():
    # shot1 已完成，跳过；生成 2-6
    for shot in SHOTS:
        if shot["id"] == 1:
            continue
        gen_kf(shot)

if __name__ == "__main__":
    main()
