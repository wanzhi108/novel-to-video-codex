"""直接验证 torch 2.9.1+cu128 win_amd64 whl URL 可达性。"""
import httpx

PROXY = "http://127.0.0.1:7897"
# 标准 pytorch 命名: torch-2.9.1+cu128-cp312-cp312-win_amd64.whl
url = "https://download.pytorch.org/whl/cu128/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl"
with httpx.Client(proxy=PROXY, timeout=30, follow_redirects=True) as client:
    r = client.head(url, headers={"Accept-Encoding": "identity"})
    sz = r.headers.get("content-length", "?")
    print(f"torch cu128 whl: HTTP {r.status_code}  size={sz}  ({int(sz)/1e9:.2f} GB)" if sz.isdigit() else f"HTTP {r.status_code} size={sz}")
    # torchvision cu128
    u2 = "https://download.pytorch.org/whl/cu128/torchvision-0.24.1%2Bcu128-cp312-cp312-win_amd64.whl"
    r2 = client.head(u2, headers={"Accept-Encoding": "identity"})
    s2 = r2.headers.get("content-length", "?")
    print(f"torchvision cu128 whl: HTTP {r2.status_code}  size={s2}")
