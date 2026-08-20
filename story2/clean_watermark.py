# -*- coding: utf-8 -*-
"""去除 ImageGen 首帧右下角 'AI生成 WORKBUDDY' 水印。
策略: 取水印区域正上方 ~3 行像素作为背景色, 向下逐行覆盖水印区域,
比纯黑块更自然(延续桌面/地面/门厅的暗色)。
"""
import os, glob
from PIL import Image

REF = "D:/CosyVoice2/jb_work/story2/refs"


def clean_one(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # 水印 "AI生成 WORKBUDDY" 在右下角 (实测 1024x1536 图约宽 230, 高 55)
    box_w = min(240, int(w * 0.24))
    box_h = min(60, int(h * 0.045))
    src_y = h - box_h - 4  # 水印上方 4 像素作为参考色
    if src_y < 0:
        src_y = 0
    for dy in range(box_h):
        for dx in range(box_w):
            x = w - box_w + dx
            y = h - box_h + dy
            try:
                px = im.getpixel((min(x, w - 1), src_y))
                im.putpixel((x, y), px)
            except Exception:
                pass
    out = os.path.join(os.path.dirname(path), "clean_" + os.path.basename(path))
    im.save(out)
    return out


def main():
    paths = []
    for sub in ("", "kf2", "kf3"):
        d = os.path.join(REF, sub) if sub else REF
        paths.extend(glob.glob(os.path.join(d, "*.png")))
        paths.extend(glob.glob(os.path.join(d, "*.jpg")))
    paths = [p for p in paths if "clean_" not in os.path.basename(p)]
    print(f"Found {len(paths)} raw images")
    for p in paths:
        out = clean_one(p)
        print(f"  clean -> {out}")


if __name__ == "__main__":
    main()