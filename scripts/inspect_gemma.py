"""分析现有 gemma_3_12B_it_fpmixed.safetensors 的结构，判断能否转成 HF 目录格式。"""
import json
from pathlib import Path

f = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\text_encoders\gemma_3_12B_it_fpmixed.safetensors")
print("文件:", f.name, f"{f.stat().st_size/1e9:.2f} GB")

# 读 safetensors header（前几 KB 是 header JSON）
try:
    import struct
    with open(f, "rb") as fh:
        # header 前 8 字节是 little-endian u64 长度
        header_len = struct.unpack("<Q", fh.read(8))[0]
        header = json.loads(fh.read(header_len).decode("utf-8"))
    keys = list(header.keys())
    print(f"\nsafetensors header keys 数: {len(keys)}")
    for k in keys[:20]:
        shape = header[k].get("shape", "?")
        dtype = header[k].get("dtype", "?")
        print(f"  {k:60s} {dtype:10s} {shape}")
    # 判断是否 Gemma3ForConditionalGeneration 结构
    has_model = any("model." in k for k in keys)
    has_lm_head = any("lm_head" in k for k in keys)
    has_embed = any("embed_tokens" in k or "model.embed" in k for k in keys)
    print(f"\n含 model.* 权重: {has_model}, lm_head: {has_lm_head}, embed_tokens: {has_embed}")
    print("→ 这是 Gemma3ForConditionalGeneration 模型?", has_model and has_lm_head and has_embed)
except Exception as e:
    print("ERR:", type(e).__name__, str(e)[:200])
