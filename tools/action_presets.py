# -*- coding: utf-8 -*-
"""动作预设：给视频模型的提示词 + 参数。

每条动作都写成"给模型看的分镜说明"，重点强调：
  · 严格保持角色长相/服装/配色不变
  · 镜头别动（不要推拉摇移、不要变焦）
  · 背景保持纯色幕布
  · 动作幅度小而清楚，首尾能接上（循环动作）
"""

from __future__ import annotations

#: 公共约束，会拼在每条 prompt 前面
BASE = (
    "Keep the exact same character as the reference image: same face, same blue gradient "
    "twin-tail hair with cyan tips, same crescent-moon hair ornament, same white ruffled "
    "maid headdress and navy maid dress with a white whale-print apron, same whale tail. "
    "Do not change her design, colors or proportions. Flat solid-color green screen "
    "background only, no props, no text, no watermark. Fixed locked-off camera, no zoom, "
    "no pan, no dolly, no camera shake. Full body in frame, feet stay near the same "
    "position. Anime chibi 2D style, clean lines, soft cel shading. "
)

PRESETS: dict[str, dict] = {
    "bob": {
        "title": "轻轻浮动",
        "desc": "原地上下漂浮，像水母/呼吸，最常用的待机动作",
        "prompt": BASE + (
            "She floats gently up and down about 3% of her height, hair and whale tail lag "
            "behind with a soft sway, apron frills flutter slightly. The motion is smooth, "
            "slow and perfectly loops: first and last frame are identical."),
        "duration": 4.0,
        "fps": 24.0,
        "loop": True,
        "trigger": "click_idle",
        "weight": 3,
    },
    "squat": {
        "title": "蹲下弹起",
        "desc": "蹲一下再弹回来，裙摆抖一下，像被点到名字的反应",
        "prompt": BASE + (
            "She quickly squats down (body compresses vertically, about 10% shorter) then "
            "springs back up to her original height with a tiny overshoot bounce. Skirt and "
            "hair bounce outward on the way down and settle on the way up. Starts and ends "
            "in the same standing pose."),
        "duration": 3.0,
        "fps": 24.0,
        "loop": True,
        "trigger": "click_idle",
        "weight": 3,
    },
    "sway": {
        "title": "左右摇摆",
        "desc": "左右轻摆，头发和尾巴跟着晃",
        "prompt": BASE + (
            "She sways gently side to side, shifting her weight from one foot to the other, "
            "hair and whale tail swing with a soft delay, one full left-right cycle, "
            "seamless loop with identical first and last frame."),
        "duration": 4.0,
        "fps": 24.0,
        "loop": True,
        "trigger": "click_idle",
        "weight": 2,
    },
    "wave": {
        "title": "挥手打招呼",
        "desc": "一只手举起来挥两下，适合第一次点击时用",
        "prompt": BASE + (
            "She raises one hand up next to her head and waves it twice cheerfully, smiling, "
            "then lowers her hand back to the starting pose. Body stays in place, only the "
            "arm and a slight torso lean move."),
        "duration": 3.0,
        "fps": 24.0,
        "loop": False,
        "trigger": "click_balance",
        "weight": 1,
    },
    "nod": {
        "title": "点头说话",
        "desc": "点头两下、嘴巴一张一合，像在说话",
        "prompt": BASE + (
            "She nods her head twice while talking, mouth opening and closing as if "
            "speaking, small hand gesture near her chest. Everything else stays still."),
        "duration": 3.0,
        "fps": 24.0,
        "loop": False,
        "trigger": "speak",
        "weight": 2,
    },
    "spin": {
        "title": "开心转个圈",
        "desc": "原地转身一圈，裙摆和头发飞起来",
        "prompt": BASE + (
            "She spins around her vertical axis one full 360 degree turn in place, skirt and "
            "hair flaring outward during the spin, whale tail trailing, then stops facing the "
            "camera in her original pose."),
        "duration": 4.0,
        "fps": 24.0,
        "loop": False,
        "trigger": "click_idle",
        "weight": 1,
    },
    "jump": {
        "title": "蹦一下",
        "desc": "小跳一下，落地的裙摆回弹",
        "prompt": BASE + (
            "She bends her knees, jumps up a small hop (about 15% of her height off the "
            "ground), then lands with a soft squash and recovers to standing. Hair, tail and "
            "skirt follow through the jump."),
        "duration": 2.5,
        "fps": 24.0,
        "loop": False,
        "trigger": "click_idle",
        "weight": 2,
    },
    "sleep": {
        "title": "打瞌睡",
        "desc": "低头打盹再惊醒，长时间没人点的时候用",
        "prompt": BASE + (
            "She slowly lowers her head and dozes off, body relaxing, then suddenly wakes up "
            "with a small startle and returns to an alert standing pose."),
        "duration": 5.0,
        "fps": 24.0,
        "loop": False,
        "trigger": "idle_long",
        "weight": 1,
    },
}

#: 生成时按这个顺序（便宜/常用的先做）
DEFAULT_ORDER = ["bob", "squat", "wave", "nod", "sway", "jump", "spin", "sleep"]


def get(name: str) -> dict:
    if name not in PRESETS:
        raise KeyError(f"没有这个动作：{name}（可选：{', '.join(PRESETS)}）")
    preset = dict(PRESETS[name])
    preset["name"] = name
    return preset


def by_trigger(trigger: str) -> list[str]:
    return [name for name, item in PRESETS.items() if item.get("trigger") == trigger]
