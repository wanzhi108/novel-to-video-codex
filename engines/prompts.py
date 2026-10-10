"""生成侧提示词与命名的纯构建逻辑（自 scripts/main.py 迁出）。

迁移背景：main.py 长期独自膨胀（>12000 行）且**完全不 import engines/**，
同一套生成逻辑在两代系统里各写一遍。本模块是"架构收敛第二阶段"的第一批迁移对象：
只搬**纯构建、无 I/O**的部分，行为按黄金快照逐字对齐（tests/test_prompts_migration.py）。

main.py 侧通过 `from engines.prompts import ... as _旧名` 别名导入，
因此 15 处 `_CAMERA_PRESETS` 调用点无需改动即可收敛到单一来源。
"""
from __future__ import annotations


CAMERA_PRESETS = {
    # ── 推拉类（Dolly Push/Pull）──
    "轨道慢推": {
        "type": "dolly_push", "speed": "0.8m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "slow dolly push in, camera moving steadily forward at 0.8m/s, 50mm focal length, background gradually blurring, subject coming into sharp focus",
    },
    "低机位前推": {
        "type": "dolly_push", "speed": "0.8m/s", "focal": "35mm",
        "height": "0.3m", "angle": "0°",
        "desc": "low angle dolly push in, camera at 0.3m height moving forward at 0.8m/s, 35mm focal length, imposing upward perspective, dramatic tension",
    },
    "高机位后拉": {
        "type": "dolly_pull", "speed": "1.0m/s", "focal": "20mm",
        "height": "3.0m", "angle": "0°",
        "desc": "high angle dolly pull back, camera at 3m height pulling back at 1.0m/s, 20mm wide focal length, revealing entire scene from above",
    },
    "急速推镜": {
        "type": "dolly_push", "speed": "3.5m/s", "focal": "85mm",
        "height": "1.2m", "angle": "0°",
        "desc": "rapid dolly push in, camera accelerating to 3.5m/s, 85mm telephoto, focus snapping to subject core, intense visual pressure",
    },
    "特写切远景快拉": {
        "type": "dolly_pull", "speed": "4.5m/s", "focal": "16mm",
        "height": "1.5m", "angle": "0°",
        "desc": "extreme pull from close-up to wide shot, camera pulling back at 4.5m/s, 16mm ultra wide, dramatic spatial contrast reveal",
    },

    # ── 变焦类（Zoom）──
    "变焦推镜": {
        "type": "zoom_in", "speed": "1.5x/s", "focal": "24mm→85mm",
        "height": "1.5m", "angle": "0°",
        "desc": "zoom in from 24mm to 85mm, fixed camera position, focal length smoothly increasing, subject magnified without camera movement",
    },
    "变焦拉镜": {
        "type": "zoom_out", "speed": "1.5x/s", "focal": "85mm→24mm",
        "height": "1.5m", "angle": "0°",
        "desc": "zoom out from 85mm to 24mm, fixed camera position, focal length smoothly decreasing, background expanding to reveal context",
    },

    # ── 摇镜类（Pan）──
    "左摇镜": {
        "type": "pan_left", "speed": "10°/s", "focal": "35mm",
        "height": "1.5m", "angle": "90°",
        "desc": "horizontal pan left at 10°/s, sweeping 90°, 35mm focal length, smooth horizontal tracking, environment revealing frame by frame",
    },
    "右摇镜": {
        "type": "pan_right", "speed": "10°/s", "focal": "35mm",
        "height": "1.5m", "angle": "90°",
        "desc": "horizontal pan right at 10°/s, sweeping 90°, 35mm focal length, smooth horizontal tracking",
    },

    # ── 俯仰类（Tilt）──
    "仰拍旋摇": {
        "type": "tilt_up", "speed": "20°/s", "focal": "50mm",
        "height": "0.3m", "angle": "-75°→0°",
        "desc": "low angle tilt up from -75°, rotating at 20°/s, 50mm focal length, dramatic upward reveal, subject appearing towering and powerful",
    },
    "俯拍旋摇": {
        "type": "tilt_down", "speed": "20°/s", "focal": "24mm",
        "height": "3.0m", "angle": "75°→0°",
        "desc": "high angle tilt down from 75°, rotating at 20°/s, 24mm wide focal length, full environmental coverage from above",
    },

    # ── 环绕类（Orbit）──
    "左环摇": {
        "type": "orbit_left", "speed": "15°/s", "focal": "50mm",
        "height": "1.2m", "angle": "360°",
        "desc": "left orbit around subject at 15°/s, 360° rotation, 50mm focal length, camera at 1.2m height, subject remaining centered throughout",
    },
    "右环摇": {
        "type": "orbit_right", "speed": "15°/s", "focal": "50mm",
        "height": "1.2m", "angle": "360°",
        "desc": "right orbit around subject at 15°/s, 360° rotation, 50mm focal length, smooth circular tracking",
    },
    "旋转前推": {
        "type": "orbit_push", "speed": "20°/s+0.8m/s", "focal": "50mm",
        "height": "1.5m", "angle": "360°",
        "desc": "360° rotation at 20°/s combined with forward dolly at 0.8m/s, spiral approach, electronic stabilization",
    },

    # ── 跟拍与升降类（Tracking/Elevation）──
    "跟焦跟拍": {
        "type": "tracking", "speed": "1.0m/s", "focal": "85mm",
        "height": "1.5m", "angle": "0°",
        "desc": "smooth tracking follow shot, camera locked on subject at 1.0m/s, 85mm focal length, continuous autofocus, no jitter",
    },
    "高速跟拍": {
        "type": "tracking", "speed": "5.0m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "high speed tracking shot at 5.0m/s, electronic stabilization, slight motion blur, dynamic action following",
    },
    "垂直升镜": {
        "type": "elevation_up", "speed": "0.6m/s", "focal": "35mm→24mm",
        "height": "1.5m→5.0m", "angle": "0°",
        "desc": "vertical elevation from close-up to full view, camera rising at 0.6m/s from 1.5m to 5m, focal length widening from 35mm to 24mm",
    },

    # ── 分段式（Segmented）──
    "阶梯推镜": {
        "type": "segmented_push", "speed": "0.7m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "segmented dolly push in 3 stages at 0.7m/s each, 0.5s pause between stages, focal length subtly adjusting, rhythmic tension building",
    },
    "阶梯拉镜": {
        "type": "segmented_pull", "speed": "0.9m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "segmented dolly pull back in 3 stages at 0.9m/s each, 0.5s pause between stages, environment revealing in layers",
    },

    # ── 斜角动感类（Dutch Angle）──
    "斜角拉镜": {
        "type": "dutch_pull", "speed": "1.2m/s", "focal": "28mm",
        "height": "1.5m", "angle": "15° tilt",
        "desc": "dutch angle pull back at 1.2m/s, camera tilted 15°, 28mm wide focal length, dynamic unease, enhanced motion feel",
    },
    "斜角推镜": {
        "type": "dutch_push", "speed": "1.0m/s", "focal": "40mm",
        "height": "1.5m", "angle": "15° tilt",
        "desc": "dutch angle push in at 1.0m/s, camera tilted 15°, 40mm focal length, visual tension, dramatic approach",
    },
}

CAMERA_MAP_SIMPLE = {
    "固定镜头": "static shot, locked camera, no movement",
    "缓慢推镜": "slow push in, dolly zoom, gradually approaching subject",
    "缓慢拉镜": "slow pull back, dolly out, revealing wider context",
    "横摇": "smooth panning shot, horizontal tracking movement",
    "竖摇": "tilt shot, vertical camera movement",
    "特写": "extreme close-up shot, detail focus, shallow depth of field",
    "近景": "medium close-up, intimate framing",
    "中景": "medium shot, balanced composition",
    "全景": "wide establishing shot, full environmental context",
    "跟拍": "tracking shot, smooth camera follow, motion parallax",
    "俯拍": "high angle shot, bird's eye perspective",
    "仰拍": "low angle hero shot, dramatic upward perspective",
}


def build_series_filename(title: str, genre: str = "", episode: int = 1,
                          *, date_str: str | None = None) -> str:
    """P1-⑧: 系列化命名：题材_系列名_第N集_日期

    `date_str` 仅用于测试注入（默认取当天 MMDD）——
    否则黄金快照会**每天失效**（2026-10-11 跨午夜实测：1010 → 1011 直接失败）。
    """
    from datetime import datetime
    today = date_str or datetime.now().strftime("%m%d")
    # 题材归类
    genre_tag = ""
    if genre:
        genre_map = {
            "甜宠": "甜", "霸总": "霸", "穿越": "穿", "古风": "古",
            "言情": "言", "都市": "都", "职场": "职", "校园": "校",
            "悬疑": "悬", "复仇": "仇", "重生": "重", "逆袭": "逆",
            "亲情": "亲", "玄幻": "玄", "仙侠": "仙",
        }
        genre_tag = genre_map.get(genre, "")

    # 清理标题中的非法字符
    clean_title = "".join(c for c in (title or "未命名") if c not in r'\/:*?"<>|')
    clean_title = clean_title.strip()[:20]

    parts = []
    if genre_tag:
        parts.append(genre_tag)
    parts.append(clean_title)
    parts.append(f"第{episode}集")
    parts.append(today)
    return "_".join(parts)

def build_camera_prompt(camera_cn: str) -> str:
    """v9.10: 参数化运镜prompt生成（即梦蒸馏）

    升级为参数化描述：速度/焦段/机位/角度等工程参数
    """
    if not camera_cn:
        return "slow push in, camera dolly 0.8m/s, 50mm focal length, 1.5m height, cinematic camera movement"

    # 尝试精确匹配预设
    if camera_cn in CAMERA_PRESETS:
        return CAMERA_PRESETS[camera_cn]["desc"]

    # 复合镜头：拆分匹配
    for part in camera_cn.replace("·", ".").split("."):
        part = part.strip()
        if part in CAMERA_PRESETS:
            return CAMERA_PRESETS[part]["desc"]

    # 向后兼容：简单映射
    for cn, en in CAMERA_MAP_SIMPLE.items():
        if cn in camera_cn:
            return en

    return "slow push in, camera dolly 0.8m/s, 50mm focal length, cinematic camera movement"
