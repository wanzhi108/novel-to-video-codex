"""把交付包 zip 切成多卷，便于聊天工具/网盘传输。"""
import os, sys

src = r"D:\novel-to-video-codex_交付包_20260923.zip"
out_dir = r"D:\novel-to-video-codex_交付包_分卷"
PART = 500 * 1024 * 1024  # 500 MB/卷

os.makedirs(out_dir, exist_ok=True)
total = os.path.getsize(src)
n = (total + PART - 1) // PART
base = os.path.splitext(os.path.basename(src))[0]
print(f"源文件 {total/1e9:.2f}GB -> {n} 卷")

with open(src, "rb") as f:
    for i in range(1, n + 1):
        dst = os.path.join(out_dir, f"{base}.part{i:02d}.zip")
        with open(dst, "wb") as o:
            remain = PART
            while remain > 0:
                chunk = f.read(min(8 * 1024 * 1024, remain))
                if not chunk:
                    break
                o.write(chunk)
                remain -= len(chunk)
        print(f"  part{i:02d}: {os.path.getsize(dst)/1e6:.1f}MB", flush=True)
print("done ->", out_dir)
