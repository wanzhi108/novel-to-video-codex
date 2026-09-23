"""抓 awesome-ltx2 的 GGUF 量化模型清单 + 官方 ComfyUI-LTXVideo workflows，确定最优下载目标。"""
import httpx
import re

PROXY = "http://127.0.0.1:7897"
URL = "https://raw.githubusercontent.com/suryatmodulus/awesome-ltx2/main/README.md"

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    r = client.get(URL)
    t = r.text

# 抓 GGUF 段
print("=== GGUF Quantized Models 段 ===")
m = re.search(r'id="gguf"(.{0,4000})', t, re.DOTALL)
if m:
    seg = m.group(1)
    # 提取表格行：模型名 | 精度 | 大小 | 链接
    for row in re.findall(r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|', seg):
        name, prec, size, link = [x.strip() for x in row]
        if size and any(u in size for u in ["GB", "MB"]):
            print(f"  {name[:30]:32s} {prec[:14]:14s} {size:10s} {link[:90]}")
else:
    print("未找到 GGUF 段，直接搜 Q2/Q3/Q4 行")
    for row in re.findall(r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|', t):
        name, prec, size, link = [x.strip() for x in row]
        if any(q in name + prec for q in ["Q2", "Q3", "Q4", "Q5", "Q6", "Q8"]) and size:
            print(f"  {name[:30]:32s} {prec[:14]:14s} {size:10s}")
