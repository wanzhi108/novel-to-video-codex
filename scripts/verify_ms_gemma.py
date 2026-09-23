"""验证 modelscope 的 gemma config 隐藏维度是否匹配 LTX-2 (3840)。"""
import httpx

url = "https://modelscope.cn/models/unsloth/gemma-3-12b-it/resolve/master/config.json"
with httpx.Client(timeout=25, follow_redirects=True) as c:
    r = c.get(url)
    if r.status_code == 200:
        import json
        d = r.json()
        print("architectures:", d.get("architectures"))
        print("hidden_size:", d.get("hidden_size"))
        print("num_hidden_layers:", d.get("num_hidden_layers"))
        print("model_type:", d.get("model_type"))
        # 是否 Gemma3ForConditionalGeneration + hidden 3840
        ok = d.get("architectures") == ["Gemma3ForConditionalGeneration"] and d.get("hidden_size") == 3840
        print("→ 匹配 LTX-2 (Gemma3 12B, hidden 3840)?", "YES" if ok else "NO")
    else:
        print("HTTP", r.status_code)
