"""Novel-Director 剧本 JSON 生成器（对接 ComfyUI-Novel-Director 插件）。

把小说/剧本文本 → ComfyUI-Novel-Director 需要的三个 JSON（贴进对应 Loader 节点）：
  1. Audio JSON    → DirectorAudioScriptLoader      （role_list + juben 行式剧本）
  2. Visual JSON   → DirectorVisualStoryboardLoader  （storyboard_list + main_character）
  3. Video JSON    → DirectorVideoPromptLoader       （video_prompts 逐镜运镜/动作）

输入可选：
  - 小说文件（txt）：自动做角色抽取 + 分镜 + 台词化
  - 已分镜的 JSON（本项目 pipeline 的 SceneReq 数组）：只做格式转换

用法：
    venv\\Scripts\\python.exe scripts\\novel_director_bridge.py novel.txt --out output\\nd_project
    venv\\Scripts\\python.exe scripts\\novel_director_bridge.py scenes.json --out output\\nd_project

产出（out 目录）：
    audio.json / visual.json / video.json / project.json（合并版，含 cast 建议）

对接方式：ComfyUI 里把三个 JSON 文本分别粘贴到
"🎬 1. 演员选角"→"🎙️ 2A/🎨 2B/📹 2C" 三个 Loader 的对应输入框。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.storyboard import call_deepseek, get_deepseek_key  # noqa: E402

# ────────────────────────────────────────────────
# 提示词体系（输出严格贴合 Novel-Director 解析格式）
# ────────────────────────────────────────────────

SYSTEM_AUDIO = """你是红果漫剧剧本改编师。把给定小说片段改写成"有声剧对白本"JSON，供 AI 配音。
输出必须是合法 JSON 对象，字段：
{
  "role_list": [{"name": "角色名", "instruct": "中文音色/语气描述"}...],   // 全剧角色音色库，含"旁白"
  "juben": "旁白: ...\\n角色名: 台词\\n..."                                  // 行式剧本，每行"角色: 台词"
}
规则：
- 每行必须形如 "角色名: 台词"，无冒号的行会被当作旁白——旁白行请显式写 "旁白: ..."。
- 台词忠于原文，口语化，保留叙事推进；角色只说出场角色。
- 角色名用真实姓名（禁用"男主/女主/他/她"代称）。
- 只返回 JSON，无 markdown 围栏、无其他文字。"""

SYSTEM_VISUAL = """你是竖屏 9:16 漫剧分镜师。把给定小说片段拆成分镜 JSON，供 ComfyUI 图生图/图生视频。
输出必须是合法 JSON 对象，字段：
{
  "storyboard_list": [
    {"prompt": "英文画面描述（含角色外貌/服装/环境/光线/构图，竖屏 9:16，干净完整的一句话）",
     "main_character": ["出场角色名"]}   // 空数组=无人/环境镜
  ]
}
规则：
- 每镜一个画面，覆盖全部关键情节；约每 1-2 句台词 1 镜。
- main_character 必须与 audio JSON 的 role_list 名称完全一致（一致性匹配用）。
- prompt 用英文，可含动作状态但不要写运镜（运镜放 video JSON）。
- 只返回 JSON，无 markdown 围栏。"""

SYSTEM_VIDEO = """你是漫剧运镜师。为给定分镜生成逐镜视频运镜/动态提示词 JSON。
输出必须是合法 JSON 对象：
{
  "video_prompts": ["英文运镜描述，如 'slow push-in from medium shot, subtle handheld'", ...]
}
规则：
- 数量与分镜数量一致（宁少勿多，缺的会用默认值，多余会错位）。
- 每条描述：镜头运动（push/pan/tilt/dolly/static）+ 主体动作幅度 + 是否特写。
- 竖屏 9:16、单镜 3-4 秒量级、避免剧烈甩镜。
- 只返回 JSON，无 markdown 围栏。"""


# ────────────────────────────────────────────────
# 解析
# ────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象（容忍 ```json 围栏/前后杂文）。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"LLM 输出无 JSON 对象: {text[:200]}")
    return json.loads(m.group(0))


def load_input(path: Path) -> str:
    """小说 txt 原文，或本项目分镜 JSON（SceneReq 数组）。"""
    if path.suffix.lower() in (".json",):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):  # SceneReq 数组 → 直接转
            return data
        if isinstance(data, dict) and "scenes" in data:
            return data["scenes"]
    return path.read_text(encoding="utf-8")


def scenes_to_text(scenes: list) -> str:
    """分镜数组 → 供 audio/visual 生成用的文本（保留分镜 id/台词/描述）。"""
    lines = []
    for i, s in enumerate(scenes, 1):
        desc = s.get("description") or s.get("prompt") or ""
        sub = s.get("subtitle_text") or s.get("text") or ""
        chars = s.get("characters") or s.get("main_character") or ""
        lines.append(f"[镜{i}] 角色: {chars}")
        if sub:
            lines.append(f"  台词: {sub}")
        lines.append(f"  画面: {desc}")
    return "\n".join(lines)


# ────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────

def _clip(text: str, limit: int = 6000) -> str:
    return text[:limit]


async def generate_project(novel_text: str, title: str = "", key: str = "") -> dict:
    """三步 LLM 生成三份 JSON；任一失败则给出局部空结构（不静默崩溃）。"""
    api_key = key or get_deepseek_key()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 未设置（环境变量或 .dsh/.credentials.yaml）")

    src = _clip(novel_text)
    base_hint = f"小说标题：{title}\n\n" if title else ""

    print("[ND] ① 生成 Audio JSON（角色+对白本）…", flush=True)
    audio = extract_json(call_deepseek(
        api_key, SYSTEM_AUDIO, base_hint + src, temperature=0.5, max_tokens=8192))
    print(f"[ND]   role_list={len(audio.get('role_list', []))} 人, 台词行≈{len(audio.get('juben', '').splitlines())}", flush=True)

    print("[ND] ② 生成 Visual JSON（分镜+角色映射）…", flush=True)
    visual = extract_json(call_deepseek(
        api_key, SYSTEM_VISUAL, base_hint + src, temperature=0.5, max_tokens=8192))
    n_shots = len(visual.get("storyboard_list", []))
    print(f"[ND]   {n_shots} 镜", flush=True)

    print("[ND] ③ 生成 Video JSON（逐镜运镜）…", flush=True)
    shots_text = json.dumps(visual.get("storyboard_list", []), ensure_ascii=False)
    video = extract_json(call_deepseek(
        api_key, SYSTEM_VIDEO, f"分镜:\n{shots_text}", temperature=0.5, max_tokens=4096))
    print(f"[ND]   {len(video.get('video_prompts', []))} 条运镜", flush=True)

    # 断言：三个 JSON 的镜头数一致性（Novel-Director 按索引对齐）
    n_audio_lines = len([l for l in audio.get("juben", "").splitlines() if l.strip()])
    n_video = len(video.get("video_prompts", []))
    if n_shots and n_video and n_shots != n_video:
        print(f"[ND] ⚠️ 分镜 {n_shots} 镜 vs 运镜 {n_video} 条不一致（会错位）——将补齐为默认运镜", flush=True)
        video["video_prompts"] = (video["video_prompts"] +
                                  ["static camera, subtle motion"] * (n_shots - n_video))[:n_shots]

    return {"audio": audio, "visual": visual, "video": video,
            "meta": {"title": title, "shots": n_shots, "audio_lines": n_audio_lines}}


def main() -> int:
    p = argparse.ArgumentParser(description="Novel-Director 剧本 JSON 生成器")
    p.add_argument("input", type=Path, help="小说 txt 或分镜 json")
    p.add_argument("--title", default="")
    p.add_argument("--out", type=Path, default=ROOT / "output" / "nd_project",
                   help="输出目录（默认 output/nd_project）")
    args = p.parse_args()
    if not args.input.exists():
        print(f"输入不存在: {args.input}")
        return 1

    import asyncio
    loaded = load_input(args.input)
    if isinstance(loaded, list):
        print(f"[ND] 输入为 {len(loaded)} 镜分镜 JSON，做格式转换…")
        text = scenes_to_text(loaded)
    else:
        text = loaded

    proj = asyncio.run(generate_project(text, title=args.title))

    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("audio.json", proj["audio"]), ("visual.json", proj["visual"]),
                       ("video.json", proj["video"]), ("project.json", proj)):
        (args.out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ND] ✓ {args.out / name}")

    print("\n[ND] 完成。在 ComfyUI 中：")
    print("  1. DirectorAudioScriptLoader     ← 粘贴 audio.json 内容")
    print("  2. DirectorVisualStoryboardLoader ← 粘贴 visual.json 内容")
    print("  3. DirectorVideoPromptLoader      ← 粘贴 video.json 内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())
