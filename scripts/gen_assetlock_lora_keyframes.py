"""A+C: 药铺场景 LoRA(ykf_scene) + 角色 IPAdapterFaceID，生成 6 镜关键帧（最强一致性）。
s1/s2/s5 有脸(叶玄机/掌柜)；s3/s4/s6 细节镜只用 LoRA(场景)。
"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
LORA = "ykf_scene.safetensors"
WIDTH, HEIGHT = 832, 1216
STEPS, CFG = 28, 6.0
NEG = ("low quality, blurry, worst quality, watermark, text, logo, deformed, bad anatomy, "
       "extra fingers, jpeg artifacts, cartoon, anime")
CH = "asset_char_yexuanji.png"
ZG = "asset_char_zhanggui.png"
Q = "asset_scene_qiantang.png"
H = "asset_scene_houyuan.png"
W = "asset_scene_wofang.png"

SHOTS = [
    dict(id=1, face=CH, sc=Q, out="lkL_s1_kf",
         prompt="a photo of sks chinese herbal medicine shop, a young Chinese man with short dark hair, calm gaze, "
                "in a dark teal cotton jacket, standing at the counter inspecting dried herbs with a brass scale, "
                "rows of dark wooden apothecary cabinets with jars, dim warm lantern light, cinematic, 8k"),
    dict(id=2, face=CH, sc=W, out="lkL_s2_kf",
         prompt="a young Chinese man with short dark hair in a dark teal cotton jacket, sitting up on a simple "
                "wooden bed in a dim old Chinese bedroom, cold blue moonlight through a lattice window, moody, cinematic, 8k"),
    dict(id=3, face=None, sc=H, out="lkL_s3_kf",
         prompt="a photo of sks chinese herbal medicine shop, a rustic dark courtyard before dawn, an old clay "
                "medicine pot on a low clay stove with a small fire glowing beneath and wisps of steam rising, "
                "cool blue predawn light, cinematic, 8k"),
    dict(id=4, face=None, sc=Q, out="lkL_s4_kf",
         prompt="close-up of a young man's hands crushing dried green mint leaves on a worn wooden counter, brass "
                "bowls and a brass scale, dim warm lantern light in an old herbal medicine shop, cinematic, 8k"),
    dict(id=5, face=ZG, sc=Q, out="lkL_s5_kf",
         prompt="a photo of sks chinese herbal medicine shop, an old bald Chinese shop owner with permanently "
                "half-closed sleepy eyes, wearing a faded light blue cotton jacket, holding an unlit pipe, standing "
                "at the counter, dim warm lantern light, cinematic, 8k"),
    dict(id=6, face=None, sc=Q, out="lkL_s6_kf",
         prompt="extreme close-up of a dark wooden counter edge with a deep scratch mark and a small dark dried "
                "stain, dim shadows, shallow depth of field, mysterious tense atmosphere, cinematic, 8k"),
]


def post(route, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + route, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def build_wf(shot, seed):
    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ckpt", 0], "lora_name": LORA, "strength_model": 0.85}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": shot["prompt"]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": NEG}},
        "lat": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
    }
    model_ref = ["lora", 0]
    # 场景参考（锁特定药铺布局，低权重）
    wf["sceneimg"] = {"class_type": "LoadImage", "inputs": {"image": shot["sc"]}}
    wf["ul_scene"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": model_ref, "preset": "PLUS (high strength)"}}
    wf["scene"] = {"class_type": "IPAdapter", "inputs": {
        "model": wf["ul_scene"]["inputs"]["model"], "ipadapter": ["ul_scene", 1], "image": ["sceneimg", 0],
        "weight": 0.4, "start_at": 0.0, "end_at": 1.0, "weight_type": "standard"}}
    model_ref = ["scene", 0]
    if shot["face"]:
        wf["faceimg"] = {"class_type": "LoadImage", "inputs": {"image": shot["face"]}}
        wf["ul_face"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": model_ref, "preset": "PLUS FACE (portraits)"}}
        wf["face"] = {"class_type": "IPAdapterFaceID", "inputs": {
            "model": wf["ul_face"]["inputs"]["model"], "ipadapter": ["ul_face", 1], "image": ["faceimg", 0],
            "weight": 0.8, "weight_faceidv2": 0.8, "combine_embeds": "concat",
            "weight_type": "linear", "embeds_scaling": "V only", "start_at": 0.0, "end_at": 1.0}}
        model_ref = ["face", 0]
    wf["ks"] = {"class_type": "KSampler", "inputs": {
        "model": model_ref, "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
        "seed": seed, "steps": STEPS, "cfg": CFG, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}}
    wf["dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}}
    wf["save"] = {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": shot["out"]}}
    return wf


def gen(shot, seed):
    wf = build_wf(shot, seed)
    res = post("/prompt", {"prompt": wf, "client_id": "lkL"})
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
                print(f"  ✗ shot{shot['id']} ERR {json.dumps(st.get('messages', []))[:400]}", flush=True)
                return False
            if st.get("completed"):
                outs = hist[pid].get("outputs", {})
                img = None
                for k, v in outs.items():
                    if "images" in v:
                        img = v["images"][0]; break
                if img:
                    src = os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\output", img["subfolder"], img["filename"])
                    dest = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input" + "\\" + shot["out"] + ".png"
                    shutil.copyfile(src, dest)
                    print(f"  ✓ shot{shot['id']} {shot['out']}.png ({round(time.time()-t0,1)}s)", flush=True)
                    return True
        if time.time() - t0 > 300:
            print(f"  ✗ shot{shot['id']} TIMEOUT", flush=True)
            return False


def main():
    for i, shot in enumerate(SHOTS):
        gen(shot, seed=20251234 + i)


if __name__ == "__main__":
    main()
