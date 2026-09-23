import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\insightface"


def face_emb(path):
    import insightface
    fa = insightface.app.FaceAnalysis(
        name="antelopev2", root=ROOT, providers=["CPUExecutionProvider"])
    fa.prepare(ctx_id=0, det_size=(640, 640))
    img = cv2.imread(str(path))
    faces = fa.get(img)
    if not faces:
        return None, img
    return faces[0].normed_embedding, img


def main():
    src = Path(sys.argv[1])
    frames = [Path(p) for p in sys.argv[2:]]
    e0, img0 = face_emb(src)
    prev = None
    for i, fp in enumerate(frames):
        e, img = face_emb(fp)
        sim_src = float(np.dot(e0, e)) if e0 is not None and e is not None else float("nan")
        sim_prev = float(np.dot(prev, e)) if prev is not None and e is not None else float("nan")
        g0 = cv2.resize(img0, (480, 864))
        g1 = cv2.resize(img, (480, 864))
        mae = float(np.abs(g0.astype(np.float32) - g1.astype(np.float32)).mean())
        print("%s: face_vs_src=%.3f face_vs_prev=%.3f pixel_mae_vs_src=%.2f" % (
            fp.name, sim_src, sim_prev, mae))
        prev = e


if __name__ == "__main__":
    main()
