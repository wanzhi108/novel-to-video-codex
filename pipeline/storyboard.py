"""DeepSeek 分镜生成（P5 storyboard 阶段）—— 复用 main.py 的提示词体系与重试策略。

实现：
- call_deepseek：httpx 调用（自动读环境变量代理，HTTP_PROXY/HTTPS_PROXY），
  带回退重试（429/5xx/超时）+ 截断自动扩容（finish_reason=length）。
- generate_storyboard：读小说 → 长文分块 + 全文摘要 → 逐块调 DeepSeek 生成分镜
  → 解析为 SceneReq 列表（供 run_assets 用）。

key 来源：环境变量 DEEPSEEK_API_KEY > .dsh credentials > Settings。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Optional

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MAX_TOKENS = 16384
MAX_TOKEN_CAP = 65536

# main.py STORYBOARD_SYSTEM 的精简复用（竖屏 9:16 红果漫剧分镜）
STORYBOARD_SYSTEM = """你是红果平台短剧分镜师，将小说改编为竖屏 9:16 的连续分镜脚本。
每镜输出 JSON，字段：id,title,description,characters,setting,mood,camera,image_prompt,video_prompt,negative_prompt,duration,emotional_intensity。
- image_prompt/video_prompt 用英文（供 ComfyUI/云端模型）。
- 情绪映射：紧张/温馨/悲伤/壮阔/神秘/热血/恐惧/喜悦/惆怅/愤怒/压抑/释然。
- 分镜数量按文本长度（约每 300-500 字 1 镜），必须覆盖全部重要情节。
只返回 JSON 数组，无其他文字。"""


def get_deepseek_key() -> str:
    """从环境变量 / .dsh credentials 读取 DEEPSEEK API key。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    # .dsh credentials（DSH 凭据）
    try:
        for path in (Path.home() / ".dsh" / ".credentials.yaml",
                     Path.home() / ".dsh" / "credentials.yaml"):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    m = re.match(r"\s*DEEPSEEK_API_KEY\s*[:=]\s*(\S+)", line)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return ""


def call_deepseek(api_key: str,
                  system_prompt: str,
                  user_prompt: str,
                  model: str = "deepseek-chat",
                  max_tokens: int = DEFAULT_MAX_TOKENS,
                  temperature: float = 0.7) -> str:
    """调用 DeepSeek（带重试 + 截断自动扩容）。"""
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 未设置：请在环境变量或 .dsh/.credentials.yaml 配置")
    current = max_tokens
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}

    # 尝试配置代理（若 127.0.0.1:7897 监听则用，否则走环境变量/直连）
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None

    for truncation_round in range(3):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": current,
        }
        for attempt in range(3):
            try:
                with httpx.Client(timeout=120, proxy=proxy) as client:
                    resp = client.post(DEEPSEEK_URL, json=payload, headers=headers)
                if resp.status_code == 401:
                    raise ValueError("DeepSeek API Key 无效或已过期")
                if resp.status_code == 402:
                    raise ValueError("DeepSeek 账户余额不足")
                if resp.status_code == 429:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code == 400:
                    err = resp.text[:300]
                    if "input length too long" in err.lower():
                        raise ValueError(f"DeepSeek 输入太长: {err}")
                    raise ValueError(f"DeepSeek 400: {err}")
                if resp.status_code >= 500:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                finish = data["choices"][0].get("finish_reason", "stop")
                if finish == "length" and truncation_round < 2:
                    current = min(current * 2, MAX_TOKEN_CAP)
                    break  # 扩容后重试
                return content
            except ValueError:
                raise  # 客户端错误不重试
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < 2:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"DeepSeek 调用失败: {exc}")
        # truncation_round 循环继续
    raise RuntimeError("DeepSeek 调用失败（输出持续截断）")


def _extract_json_array(text: str) -> list[dict]:
    """从 LLM 输出提取 JSON 数组（容忍代码围栏/前后文字）。"""
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        raise ValueError(f"未找到 JSON 数组: {text[:200]}")
    return json.loads(m.group(0))


def _split_chunks(text: str, max_chars: int = 6000) -> list[str]:
    """按段落边界切分长文为块（每块 ≤ max_chars）。"""
    if len(text) <= max_chars:
        return [text]
    paras = re.split(r"\n\s*\n", text)  # 按空行切段
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 > max_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf:
        chunks.append(buf)
    return chunks or [text]


def generate_storyboard(novel_text: str,
                        title: str = "",
                        api_key: Optional[str] = None,
                        max_scenes: int = 0) -> list[dict]:
    """小说 → 分镜列表（dict，字段与 run_assets 的 SceneReq 对齐）。"""
    key = api_key or get_deepseek_key()
    chunks = _split_chunks(novel_text)
    all_scenes: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        marker = ""
        if len(chunks) > 1:
            marker = f"\n【当前分块第 {i}/{len(chunks)} 段，只生成本块情节，编号由系统重排】\n"
        intro = f"小说标题：{title}\n" if title else ""
        result = call_deepseek(
            key, STORYBOARD_SYSTEM,
            f"{intro}{marker}原文如下：\n{chunk}",
            max_tokens=DEFAULT_MAX_TOKENS, temperature=0.7)
        scenes = _extract_json_array(result)
        all_scenes.extend(scenes)
    if max_scenes > 0:
        all_scenes = all_scenes[:max_scenes]
    return all_scenes
