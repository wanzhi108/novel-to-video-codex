"""读 ltx-core pyproject 依赖 + uv.lock torch 版本。"""
import re
from pathlib import Path

d = Path(r"D:\novel-to-video-codex\LTX-2-OPTIMIZED")

# ltx-core deps
c = (d / "packages" / "ltx-core" / "pyproject.toml").read_text(encoding="utf-8")
m = re.search(r"dependencies\s*=\s*\[(.*?)\]", c, re.DOTALL)
print("=== ltx-core dependencies ===")
if m:
    deps = re.findall(r'"([^"]+)"', m.group(1))
    for dep in deps:
        print(" ", dep)

# uv.lock torch
print("\n=== uv.lock torch / pytorch index ===")
lock = (d / "uv.lock").read_text(encoding="utf-8") if (d / "uv.lock").exists() else ""
# 查 [package] name = torch 的版本与 source
for m2 in re.finditer(r'\[\[package\]\]\s*name = "torch".*?version = "([^"]+)".*?(?:source = \{.*?url = "([^"]+)"|\n)', lock, re.DOTALL):
    print(f"  torch version={m2.group(1)} source_url={m2.group(2) if m2.lastindex>=2 else '?'}")
    break
# 找 pytorch index 配置
if "cu128" in lock:
    print("  含 cu128 引用:", re.findall(r'[^\n]*cu128[^\n]*', lock)[:3])
else:
    print("  uv.lock 中无 cu128（torch source 未锁定 cu128）")
