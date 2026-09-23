"""实测官方 Gemma 编码器下载可用性 + 检查 HF 登录状态。"""
import httpx
import os

PROXY = "http://127.0.0.1:7897"

# 官方 README 提到的两个候选
URLS = {
    "gemma3_12b_qat_official": "https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized",
    "gemma3_12b_it": "https://huggingface.co/google/gemma-3-12b-it",
}

with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    for name, url in URLS.items():
        try:
            r = client.get(url + "/resolve/main/config.json")
            print(f"{name:28s} HTTP {r.status_code}  {r.text[:80] if r.status_code==200 else r.text[:120]}")
        except Exception as e:
            print(f"{name:28s} ERR {type(e).__name__} {str(e)[:80]}")

# 检查是否已登录 HF（token 文件或环境变量）
print("\n=== HF 登录状态 ===")
print("HF_TOKEN env:", "已设置" if os.environ.get("HF_TOKEN") else "未设置")
hf_dir = os.path.expanduser("~/.huggingface")
print("~/.huggingface 存在:", os.path.isdir(hf_dir))
if os.path.isdir(hf_dir):
    print("  token:", os.path.isfile(os.path.join(hf_dir, "token")))
