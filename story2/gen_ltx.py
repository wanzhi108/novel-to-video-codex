# -*- coding: utf-8 -*-
"""Plan B (LTX 22B): 每镜生成多段 LTX 片段，拼接后接近正常节奏(消除 2-3x 慢放)。

Wan 14B 已确认在本机不具实用可行性(采样期 ram_free 锁死 0.5GB 换页, 17f/4steps>400s)。
故用 LTX 22B 每镜生成 2-3 段(2.7s/段)，逐镜拼接对齐旁白 → 不再慢放。

Segments per shot (按旁白时长 / 2.7s 估算):
  shot1 -> 3 段 (~8.1s, 旁白 7.8s)
  shot2 -> 4 段 (~10.8s, 旁白 10.64s)
  shot3 -> 2 段 (~5.4s, 与 shot4 同属 scene3)
  shot4 -> 3 段 (~8.1s)
  scene3 合计 ~13.5s, 旁白 12.64s

Phases:
  V  - LTX 视频生成 (960x1728, 65帧@24fps=2.7s/段)
断点续传：dest 存在且 >10KB 则跳过。
"""
import json, os, sys, time, gc, re, urllib.request, urllib.parse, subprocess, shutil, random, glob
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLANB = Path(__file__).resolve().parent
WF_DIR = PROJECT_ROOT / "comfyui"
OUT = PLANB
OUT_VID = OUT / "videos"
LOG = OUT / "genB_ltx.log"

# LTX 视频参数（沿用 planC 验证值）
VID_W, VID_H = 960, 1728
LENGTH = 65            # ~2.7s @24fps
FRAME_RATE = 24
LTX_CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"
LTX_TEXT_ENCODER = "gemma_3_12B_it_fpmixed.safetensors"
NEG = ("low quality, blurry, deformed hands, extra fingers, bad anatomy, watermark, "
       "text, letters, signs, chinese characters, oversaturated, harsh lighting, ugly, "
       "distorted face, mutated, disfigured, double face, two heads, duplicated face, "
           "clone, multiple faces, extra head, jitter, flicker, sudden camera cut")

# 每镜多段轮换的运镜（不连续重复，制造景别/运动变化）
CAMERA_MOVES = [
    "slow cinematic push-in, camera gradually moves closer to the subject",
    "slow cinematic pull-out, revealing more of the surroundings",
    "slow lateral tracking shot, camera drifts sideways following the subject",
    "gentle orbiting camera, slight arc around the subject",
    "subtle handheld sway with soft vertical drift",
    "slow tilt-up revealing the environment above",
]

# 每镜片段数（按配音时长 / 2.7s 估算：scene1 8.94s->4, scene2 11.78s->5, scene3 11.75s->5, scene4 8.02s->3）
SEGMENTS = {1: 4, 2: 5, 3: 5, 4: 3}

FF = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
FFP = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"
plan = json.load(open(os.path.join(PLANB, "shots.json"), encoding="utf-8"))


def log(*a):
    s = " ".join(str(x) for x in a)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + s + "\n")
    print(s, flush=True)


def post(url, data=None, raw=None, ctype="application/json"):
    if raw is not None:
        req = urllib.request.Request(url, data=raw, headers={"Content-Type": ctype})
    else:
        d = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=d, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def load_wf(name):
    txt = open(os.path.join(WF_DIR, name), encoding="utf-8").read()
    for a, b in (("True", "true"), ("False", "false"), ("None", "null")):
        txt = txt.replace(a, b)
    return json.loads(txt)


def fill(wf, kv):
    s = json.dumps(wf)
    for k, v in kv.items():
        s = s.replace('"{{%s}}"' % k, json.dumps(v))
    return json.loads(s)


def upload_image(path):
    with open(path, "rb") as f:
        data = f.read()
    boundary = "----ffboundary"
    body = (b"--" + boundary.encode() + b"\r\n"
            + b'Content-Disposition: form-data; name="image"; filename="%s"\r\n' % os.path.basename(path).encode()
            + b"Content-Type: image/png\r\n\r\n" + data + b"\r\n"
            + b"--" + boundary.encode() + b"--\r\n")
    return json.loads(post(COMFY + "/upload/image", raw=body,
                           ctype="multipart/form-data; boundary=%s" % boundary))["name"]


def submit(wf):
    raw = post(COMFY + "/prompt", {"prompt": wf, "client_id": "planB_ltx"})
    return json.loads(raw)["prompt_id"]


def poll(pid, timeout=3600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d = json.loads(urllib.request.urlopen(COMFY + "/history/" + pid, timeout=60).read())
            if pid in d:
                return d[pid]
        except Exception:
            pass
        time.sleep(6)
    raise TimeoutError("poll timeout " + pid)


def wait_comfy_ready(max_wait=None):
    """等待 ComfyUI 可达 (重启后自动继续). max_wait=None 表示无限等待, 绝不放弃."""
    t0 = time.time()
    while True:
        try:
            with urllib.request.urlopen(COMFY + "/", timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if max_wait is not None and time.time() - t0 >= max_wait:
            return False
        time.sleep(15)


def upload_image_retry(path):
    """upload_image 无限重试: ComfyUI 崩了就等它重启再试, 绝不放弃."""
    while True:
        try:
            return upload_image(path)
        except Exception as e:
            log("  upload_image 失败 (%s), 等 ComfyUI 恢复..." % repr(e)[:80])
            wait_comfy_ready(None)


def fetch_outputs(rec):
    outs = rec.get("outputs", {})
    for n, o in outs.items():
        for key in ("gifs", "videos"):
            if key in o and o[key]:
                it = o[key][0]
                fn = it.get("filename", "").replace("-audio", "")
                return ("video", fn, it.get("subfolder", ""), it.get("type", "output"))
    return None


def download(out, dest):
    kind, fn, sub, typ = out
    qs = urllib.parse.urlencode({"filename": fn, "subfolder": sub, "type": typ})
    raw = post(COMFY + "/view?" + qs)
    with open(dest, "wb") as f:
        f.write(raw)
    return len(raw)


def get_video_duration(mp4):
    try:
        r = subprocess.run([FFP, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", mp4],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0


def recover_orphans():
    """WorkBuddy 偶发回收后台 driver -> ComfyUI 服务端渲染完但无人下载(孤儿).
    启动时扫 history, 把已完成且本地缺失的本故事片段捡回来, 绝不丢进度."""
    try:
        d = json.loads(urllib.request.urlopen(COMFY + "/history?max_items=40", timeout=30).read())
    except Exception as e:
        log("  recover_orphans: history 读取失败 %s" % repr(e)[:80])
        return
    for pid, rec in d.items():
        outs = rec.get("outputs", {})
        for n, o in outs.items():
            for key in ("gifs", "videos"):
                if key not in o or not o[key]:
                    continue
                it = o[key][0]
                fn = it.get("filename", "")
                sub = it.get("subfolder", "")
                # 仅本故事(story2)的渲染, 排除 planB 等其他前缀
                if "story2" not in (sub + "/" + fn):
                    continue
                base = os.path.basename(fn)
                m = re.match(r"shot_(\d\d)_(\d\d)\.mp4$", base)
                if not m:
                    continue
                sid, seg = int(m.group(1)), int(m.group(2))
                dest = os.path.join(OUT_VID, "shot_%02d_%02d.mp4" % (sid, seg))
                if os.path.exists(dest) and os.path.getsize(dest) > 10000:
                    continue
                typ = it.get("type", "output")
                qs = urllib.parse.urlencode({"filename": fn, "subfolder": sub, "type": typ})
                try:
                    raw = post(COMFY + "/view?" + qs)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    log("  RECOVER orphan shot_%02d_%02d <- %d bytes (pid %s)" % (
                        sid, seg, len(raw), pid[:8]))
                except Exception as e:
                    log("  recover 失败 shot_%02d_%02d: %s" % (sid, seg, repr(e)[:80]))


def run_vids():
    log("=== PHASE V (LTX multi-seg): %dx%d, %dframes@%dfps=%.1fs/段 ===" % (
        VID_W, VID_H, LENGTH, FRAME_RATE, LENGTH / FRAME_RATE))
    os.makedirs(OUT_VID, exist_ok=True)
    log("--- 孤儿回收: 扫描 ComfyUI history 捡回已完成但未下载的片段 ---")
    recover_orphans()
    wf = load_wf("img2vid.json")

    total_segs = sum(len(sh["segments"]) if sh.get("segments") else SEGMENTS.get(sh["id"], 3)
                     for sh in plan["shots"])
    done = 0
    for sh in plan["shots"]:
        sid = sh["id"]
        # 按段独立关键帧 + 运镜（彻底去重，每镜多构图）；老 shots.json 无 segments 时回退
        if sh.get("segments"):
            seg_defs = sh["segments"]
        else:
            base_kf = sh.get("base_kf", "shot_%02d_kf.png" % sid)
            base_emo = sh.get("emotion", "natural calm expression, subtle micro-expressions")
            n_fb = SEGMENTS.get(sid, 3)
            seg_defs = [{"kf": base_kf, "camera": CAMERA_MOVES[i % len(CAMERA_MOVES)],
                         "emotion": base_emo} for i in range(n_fb)]
        for seg, segdef in enumerate(seg_defs):
            seg = segdef.get("seg_index", seg)
            kf_path = os.path.join(OUT, segdef["kf"])
            if not os.path.exists(kf_path):
                log("  ERROR vid shot%02d-%02d: keyframe missing %s, skip" % (sid, seg, kf_path))
                continue
            dest = os.path.join(OUT_VID, "shot_%02d_%02d.mp4" % (sid, seg))
            if os.path.exists(dest) and os.path.getsize(dest) > 10000:
                done += 1
                log("  seg shot%02d-%02d exists (%d bytes), skip" % (sid, seg, os.path.getsize(dest)))
                continue
            seed = 3000 + sid * 100 + seg * 7
            emotion = segdef.get("emotion", sh.get("emotion",
                                "natural calm expression, subtle micro-expressions"))
            cam = segdef["camera"]
            prompt = (emotion + ", " + cam +
                      ", cinematic, realistic, smooth natural motion, stable facial features, "
                      "consistent character appearance, high detail, film grain")
            # 本段无限重试: ComfyUI 崩了就等用户重启后原地重跑, 绝不跳过/退出
            while True:
                up = upload_image_retry(kf_path)  # 重启后重传首帧
                body = fill(wf, {
                    "CHECKPOINT": LTX_CHECKPOINT,
                    "TEXT_ENCODER": LTX_TEXT_ENCODER,
                    "INPUT_IMAGE": up,
                    "POSITIVE_PROMPT": prompt,
                    "NEGATIVE_PROMPT": NEG,
                    "FILENAME_PREFIX": "story2/shot_%02d_%02d" % (sid, seg),
                    "FRAME_RATE": FRAME_RATE,
                    "LENGTH": LENGTH,
                    "SEED": seed,
                    "WIDTH_BASE": VID_W,
                    "HEIGHT_BASE": VID_H,
                })
                log("  seg shot%02d-%02d: submitting (seed=%d, %d/%d segs)" % (sid, seg, seed, done+1, total_segs))
                t0 = time.time()
                try:
                    pid = submit(body)
                except Exception as e:
                    log("  submit 失败(%s), 等 ComfyUI 恢复..." % repr(e)[:120])
                    wait_comfy_ready(None)
                    continue
                try:
                    rec = poll(pid, timeout=3600)
                except Exception as e:
                    log("  poll 失败(%s), ComfyUI 可能 OOM, 等恢复后重跑本段" % repr(e)[:120])
                    wait_comfy_ready(None)
                    continue
                out = fetch_outputs(rec)
                if not out:
                    log("  no output, 等 ComfyUI 恢复后重跑本段")
                    wait_comfy_ready(None)
                    continue
                try:
                    download(out, dest)
                except Exception as e:
                    log("  download 失败(%s), 重试" % repr(e)[:120])
                    continue
                sz = os.path.getsize(dest)
                dur = get_video_duration(dest)
                done += 1
                log("  seg shot%02d-%02d -> %d bytes, %.1fs, elapsed=%ds (%d/%d)" % (
                    sid, seg, sz, dur, time.time()-t0, done, total_segs))
                if dur < 1.0:
                    log("  WARN seg shot%02d-%02d: 时长过短" % (sid, seg))
                if sz < 50000:
                    log("  WARN seg shot%02d-%02d: 文件过小" % (sid, seg))
                break  # 本段成功
            # 段间冷却: 降低连续跑 LTX 22B 的内存抖动, 防 OOM 崩
            gc.collect()
            time.sleep(90)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    log("=" * 50)
    log("START planB_ltx multi-seg phase=%s" % phase)
    segs = sum(SEGMENTS.get(sh["id"], 3) for sh in plan["shots"])
    log("  %d shots, %d LTX segments total, %dx%d, %dframes" % (
        len(plan["shots"]), segs, VID_W, VID_H, LENGTH))
    log("=" * 50)
    if phase in ("all", "V"):
        run_vids()
    log("")
    log("DONE planB_ltx phase=%s" % phase)
