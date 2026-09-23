"""单独查 Gemma QAT gated 状态 + 是否有非 gated 的同尺寸编码器替代。"""
import httpx

PROXY = "http://127.0.0.1:7897"
BASE = "https://huggingface.co/api/models"

names = [
    "google/gemma-3-12b-it-qat-q4_0-unquantized",
    "google/gemma-3-12b-it",
]

with httpx.Client(proxy=PROXY, timeout=25) as client:
    for n in names:
        try:
            r = client.get(f"{BASE}/{n}")
            d = r.json()
            print(f"{n:50s} gated={d.get('gated')}  downloads={d.get('downloads')}  id={d.get('id')}")
        except Exception as e:
            print(f"{n:50s} ERR {str(e)[:60]}")
