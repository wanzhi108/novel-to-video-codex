import json, os, sys, time, urllib.request
from pathlib import Path

import gen_ltx as G


def vram_free_mb():
    try:
        d = json.loads(urllib.request.urlopen(G.COMFY + "/system_stats", timeout=10).read())
        for dev in d.get("devices", []):
            return dev["vram_free"] / 1048576
    except Exception:
        pass
    return -1


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 33
    image = sys.argv[2] if len(sys.argv) > 2 else "shot_03_kf_yang.png"
    prefix = sys.argv[3] if len(sys.argv) > 3 else "novel2vid/ltx_smoke_%df" % frames
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 424242

    prompt = ("Starting from a close-up of a calm young man with black-framed glasses "
              "in a meeting room, confident subtle smile, dramatic cinematic lighting. "
              "The scene comes to life as a single continuous tracking shot slowly pushes in. "
              "He takes a slow confident breath, then speaks softly while the camera holds steady. "
              "Cinematic, realistic, smooth natural motion, stable facial features, "
              "consistent character appearance, high detail, film grain")

    wf = G.load_wf("img2vid.json")
    up = G.upload_image_retry(os.path.join(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input", image))
    body = G.fill(wf, {
        "CHECKPOINT": G.LTX_CHECKPOINT,
        "TEXT_ENCODER": G.LTX_TEXT_ENCODER,
        "INPUT_IMAGE": up,
        "POSITIVE_PROMPT": prompt,
        "NEGATIVE_PROMPT": G.NEG,
        "FILENAME_PREFIX": prefix,
        "FRAME_RATE": G.FRAME_RATE,
        "LENGTH": frames,
        "SEED": seed,
        "WIDTH_BASE": G.VID_W,
        "HEIGHT_BASE": G.VID_H,
    })

    print("VRAM free before: %.0f MB" % vram_free_mb(), flush=True)
    print("submitting %d frames %dx%d seed=%d image=%s" % (
        frames, G.VID_W, G.VID_H, seed, image), flush=True)
    t0 = time.time()
    pid = G.submit(body)
    rec = G.poll(pid, timeout=7200)
    out = G.fetch_outputs(rec)
    if not out:
        print("NO OUTPUT", flush=True)
        sys.exit(1)

    dest = Path(r"D:\novel-to-video-codex\story2\smoke") / ("smoke_%df_%s.mp4" % (frames, seed))
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = G.download(out, str(dest))
    dur = G.get_video_duration(str(dest))
    print("OK %s %d bytes %.2fs elapsed=%.0fs VRAM free after: %.0f MB" % (
        dest, n, dur, time.time() - t0, vram_free_mb()), flush=True)


if __name__ == "__main__":
    main()
