"""列出 pytorch cu128 的 torch 2.9.1 win_amd64 whl 确切 URL。"""
import httpx

PROXY = "http://127.0.0.1:7897"
# pytorch cu128 index 的 torch wheel
url = "https://download.pytorch.org/whl/cu128/torch/"
with httpx.Client(proxy=PROXY, timeout=25, follow_redirects=True) as client:
    r = client.get(url)
    if r.status_code == 200:
        # 找 torch-2.9.1+cu128 cp312 win_amd64
        import re
        for m in re.finditer(r'href="([^"]*torch-2\.9\.1\+cu128[^"]*cp312[^"]*win[^"]*\.whl[^"]*)"', r.text):
            print("WHL:", m.group(1))
            break
        else:
            # 打印所有 torch 2.9.1 cu128 win 链接
            for m in re.finditer(r'href="([^"]*torch-2\.9\.1\+cu128[^"]*\.whl[^"]*)"', r.text):
                print("  ", m.group(1))
    else:
        print("HTTP", r.status_code, r.text[:200])
