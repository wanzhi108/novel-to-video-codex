"""资产锁定 A 全量：用 叶玄机脸+掌柜脸 + 药铺场景参考，生成 6 镜关键帧。
有脸的镜(s1/s2/s5)走 IPAdapterFaceID+IPAdapter(场景)；无脸的细节镜(s3/s4/s6)只走 IPAdapter(场景)。
产物: input/lk_s1_kf.png ... lk_s6_kf.png
"""
import json, time, urllib.request, shutil, os, sys

BASE = "http://127.0.0.1:8188"
CKPT = "RealVisXL_V4.0.safetensors"
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
    dict(id=1, face=CH, scene=Q, out="lk_s1_kf",
         prompt="a young Chinese man with short dark hair, calm gaze, in a dark teal cotton jacket, standing at "
                "the counter of an old Chinese herbal medicine shop, inspecting dried herbs with a brass scale, "
                "rows of dark wooden apothecary cabinets with jars, dim warm lantern light, cinematic, 8k"),
    dict(id=2, face=CH, scene=W, out="lk_s2_kf",
         prompt="a young Chinese man with short dark hair in a dark teal cotton jacket, sitting up on a simple "
                "wooden bed in a dim old Chinese bedroom, cold blue moonlight through a lattice window, "
                "moody, cinematic, 8k"),
    dict(id=3, face=None, scene=H, out="lk_s3_kf",
         prompt="a rustic dark courtyard before dawn, an old clay medicine pot on a low clay stove with a small "
                "fire glowing beneath and wisps of steam rising, stacked firewood, cool blue predawn light, "
                "cinematic, 8k"),
    dict(id=4, face=None, scene=Q, out="lk_s4_kf",
         prompt="close-up of a young man's hands crushing dried green mint leaves on a worn wooden counter, brass "
                "bowls and a brass scale nearby, dim warm lantern light in an old herbal medicine shop, cinematic, 8k"),
    dict(id=5, face=ZG, scene=Q, out="lk_s5_kf",
         prompt="an old bald Chinese shop owner with permanently half-closed sleepy eyes, wearing a faded light "
                "blue cotton jacket, holding an unlit pipe, standing at the counter of an old herbal medicine shop, "
                "dim warm lantern light, cinematic, 8k"),
    dict(id=6, face=None, scene=Q, out="lk_s6_kf",
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
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": shot["prompt"]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": NEG}},
        "lat": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
    }
    # 场景参考
    wf["sceneimg"] = {"class_type": "LoadImage", "inputs": {"image": shot["scene"]}}
    wf["ul_scene"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["ckpt", 0], "preset": "PLUS (high strength)"}}
    wf["scene"] = {"class_type": "IPAdapter", "inputs": {
        "model": ["ul_scene", 0], "ipadapter": ["ul_scene", 1], "image": ["sceneimg", 0],
        "weight": 0.7, "start_at": 0.0, "end_at": 1.0, "weight_type": "style transfer"}}
    model_ref = ["scene", 0]
    # 有脸则叠加 FaceID
    if shot["face"]:
        wf["faceimg"] = {"class_type": "LoadImage", "inputs": {"image": shot["face"]}}
        wf["ul_face"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["scene", 0], "preset": "PLUS FACE (portraits)"}}
        wf["face"] = {"class_type": "IPAdapterFaceID", "inputs": {
            "model": ["ul_face", 0], "ipadapter": ["ul_face", 1], "image": ["faceimg", 0],
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
    res = post("/prompt", {"prompt": wf, "client_id": "lk"})
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
                print(f"  ✗ shot{shot['id']} ERR: {json.dumps(st.get('messages', []))[:500]}", flush=True)
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
                    print(f"  ✓ shot{shot['id']} {shot['out']}.png ({round(os.path.getsize(dest)/1e6,1)}MB, {round(time.time()-t0,1)}s)", flush=True)
                    return True
        if time.time() - t0 > 300:
            print(f"  ✗ shot{shot['id']} TIMEOUT", flush=True)
            return False


def main():
    for i, shot in enumerate(SHOTS):
        gen(shot, seed=20241234 + i)


if __name__ == "__main__":
    main()
