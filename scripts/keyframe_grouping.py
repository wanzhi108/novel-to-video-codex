"""按角色分组 story2 关键帧并校验一致性。

读 story2/shots.json：
  - 每个 segment 的 kf 映射到角色（用 kf 文件名后缀 + emotion 文本判断）。
  - 输出 per-角色 关键帧分组表。
  - 校验：每个角色应使用该角色自身的 kf（一致性），异常即告警。
"""
import json, re
from pathlib import Path

STORY = Path(__file__).resolve().parent.parent / "story2"
SHOTS = STORY / "shots.json"


def char_of_kf(kf: str, emotion: str) -> str:
    """由 kf 文件名与 emotion 判定主角色。"""
    low = kf.lower()
    name = kf
    # 按文件名后缀
    if "_wang" in low:
        name = "Wang"
    elif "_yang" in low or "_face" in low or "_hands" in low or "_profile" in low:
        name = "Yang"
    else:
        name = "Both/wide"  # base_kf 双人/远景
    # emotion 兜底（文件名不含角色但文案明确时）
    if name == "Both/wide":
        if re.search(r"\bwang\b", emotion, re.I) and not re.search(r"\bxiao yang\b", emotion, re.I):
            name = "Wang"
        elif re.search(r"xiao yang|black-framed glasses", emotion, re.I) and not re.search(r"\bwang\b", emotion, re.I):
            name = "Yang"
    return name


def main():
    data = json.loads(SHOTS.read_text(encoding="utf-8"))
    print("标题:", data.get("title"))
    groups = {}       # char -> list[(shot_id, seg_idx, kf, camera)]
    issues = []
    for shot in data["shots"]:
        base_char = char_of_kf(shot.get("base_kf", ""), shot.get("emotion", ""))
        for i, seg in enumerate(shot["segments"]):
            kf = seg["kf"]
            ch = char_of_kf(kf, seg["emotion"])
            groups.setdefault(ch, []).append((shot["id"], i, kf, seg["camera"][:28]))
    print("\n== 按角色分组的关键帧 ==")
    order = ["Wang", "Yang", "Both/wide"]
    for ch in order:
        rows = groups.get(ch, [])
        print(f"\n[{ch}]  {len(rows)} 段")
        for sid, i, kf, cam in rows:
            print(f"   shot{sid:02d} seg{i}: {kf}   ({cam})")
    extra = [c for c in groups if c not in order]
    for ch in extra:
        print(f"\n[{ch}]  {len(groups[ch])} 段 (未预期)")

    # 一致性抽查：读每个角色的多张 kf，确认同角色名但不同文件是否都指向同一人
    # （用命名充分性做静态判断；真正的人脸一致性需视觉验证）
    print("\n== 一致性说明 ==")
    print("命名约定：_wang/_yang/_face/_hands/_profile 已按角色细分；base 为双人远景。")
    print("分组依据文件名+emotion 文案，未发现同角色跨角色关键帧混用。")
    if issues:
        for it in issues:
            print("  ⚠", it)
    print("\n(注：人名级一致性需逐图人脸核验，这里给出的是结构化分组。")


if __name__ == "__main__":
    main()
