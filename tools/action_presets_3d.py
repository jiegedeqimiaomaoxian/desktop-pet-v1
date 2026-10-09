# -*- coding: utf-8 -*-
"""给「minimax h3（New）」ComfyUI 版 MiniMax-H3 用的 **3D 手办风** 动作预设。

和 action_presets_mmx.py（Gradio 版、2D 赛璐璐风）的区别：

  · 这一套走 **ref2v 参考图生视频**，参考图 = 角色三视图，所以形象锚定更准
  · 风格是 **实体 3D 手办 / CGI 渲染**（Octane/Cycles 那套语义），不是 2D 动画
  · 用英文结构化提示词（subject_definitions / summary / retention_analysis /
    detailed_description / overall_soundscape），这是 MiniMax-H3 ref2v 的吃法
  · 参考图生视频下**不需要**首帧青幕（模型自己重绘场景），背景直接要求纯绿幕

踩过的坑（沿用上一轮结论，这里全部写死）：
  1. 【绝对不能写台词】提示词里只要出现「她说：…」，模型会把台词当字幕烧进画面。
     台词请放 dialogue.txt 的 `[动作名]` 段落，桌宠负责说。
  2. 【不要写带符号的拟声词】（哎！嘿！）→ 模型会画感叹号/星星特效。
  3. 【不要写"参考图只是设计稿"以外的风格歧义】→ 2D 语义一多就退回动画风。

公共约束（每条都会拼上）：镜头锁死、角色居中不移动、纯绿幕、无任何文字、
无任何特效符号、首尾同姿势可循环。
"""

from __future__ import annotations

#: 角色锚定：英文，把三视图里所有设计细节写清楚（ref2v 认细节不认"保持一致"）
CHARACTER = (
    "<Subject 1> is the chibi whale-girl maid character from the model sheet in <Picture 1>: "
    "a small chibi girl with a big head and short body, huge glossy deep-blue eyes with bright "
    "specular highlights, long wavy hair that is deep navy blue at the roots and fades to light "
    "ice-blue at the tips, a navy crescent-moon hair ornament on top of her head, a white ruffled "
    "maid headband, small blue bow ornaments at both sides of her hair, and fin-like ears. "
    "She wears a navy-blue maid dress with a white frilled apron carrying a small whale emblem, "
    "a white high collar with a navy ribbon bow and a tiny blue gem, white ruffled trim, gold star "
    "decorations on the skirt hem, white tights and dark navy shoes with white trim, and she has a "
    "large navy-blue whale tail with a lighter underside behind her. "
    "<Picture 1> is the official model sheet for <Subject 1> with front, side and back views plus "
    "detail callouts, and it is the authoritative reference for her design, colours, proportions "
    "and outfit. <Subject 1> is the only character on screen."
)

#: 3D 渲染管线：把 2D 三视图"翻译"成实体手办的关键段（实测有效）
STYLE_3D = (
    "Rendering style: <Subject 1> is realised as a PHYSICAL THREE-DIMENSIONAL 3D CGI CHARACTER — "
    "a real sculpted 3D model with genuine volume, depth and thickness, exactly like a high-end "
    "collectible PVC figurine shot in a studio. Physically based rendering with subsurface "
    "scattering on the skin making it look soft and translucent like vinyl, glossy eyes with "
    "layered specular highlights and tiny environment reflections, hair built from thick sculpted "
    "3D strands with anisotropic highlights, fabric with woven normal-mapped texture and real "
    "folds, soft ray-traced contact shadows under her feet, and a shallow depth of field. "
    "IMPORTANT: <Picture 1> is ONLY the design reference sheet that defines her colours, outfit "
    "and proportions. It is NOT the visual style of the video. The video must NOT be flat 2D "
    "anime line art, NOT a 2D drawing and NOT cel-shaded illustration — the video is a 3D render."
)

#: 通用约束（每条提示词都会拼上）
RULES = (
    " The camera is COMPLETELY LOCKED OFF — no movement, no sway, no shake, no zoom, no pan, no "
    "tilt and no cut at any point; a single continuous shot. "
    "<Subject 1> stays centred in the frame the whole time and does not walk or move away; her "
    "feet stay in the same spot on the studio floor. "
    "The background is a completely uniform, clean, flat chroma-key GREEN studio backdrop "
    "(a pure bright green screen) with absolutely nothing else in it: no props, no furniture, no "
    "decorations, no pattern, no gradient, no shadow cast on the backdrop and no floor line. "
    "There must be ABSOLUTELY NO TEXT of any kind anywhere in the frame: no subtitles, no spoken "
    "dialogue text, no speech bubbles, no captions, no titles, no watermarks, no signatures and "
    "no borders. There must be NO comic or effect symbols at all: no exclamation marks, no stars, "
    "no hearts, no sweat drops, no speed lines, no sparkles, no floating petals or light dots. "
    "The frame contains nothing but <Subject 1> and the flat green backdrop. "
    "Her whole body is inside the frame and physically correct, with no extra or duplicated limbs. "
    "The first frame and the last frame show the same pose so the clip loops seamlessly."
)

#: 运镜/表情：不要台词，只描述口型
FACE = (" Her mouth is slightly open with a lively, natural, friendly expression, "
        "but no words and no text appear anywhere.")


def _prompt(motion: str, extra: str = "", face: str = FACE) -> str:
    """拼一条完整的 ref2v 结构化提示词。"""
    return (
        "subject_definitions:\n"
        f"{CHARACTER}\n\n"
        "summary:\n"
        "[reference generation] The target video is a short seamlessly looping clip of "
        f"<Subject 1> rendered as a 3D CGI character on a green screen. {STYLE_3D}"
        f"{motion}{face}{RULES}\n\n"
        "retention_analysis:\n"
        "<Subject 1> (appears in [Shot 1]): fully_preserved - her navy-to-ice-blue gradient hair, "
        "crescent-moon hair ornament, white ruffled maid headband, side blue bows, fin-like ears, "
        "big glossy deep-blue eyes, navy and white maid dress with the whale-emblem apron, collar "
        "ribbon with gem, dark shoes, whale tail and her chibi proportions are all retained exactly "
        "as defined in <Picture 1>, rebuilt as a three-dimensional sculpted character.\n"
        "<Picture 1> (design reference): fully_preserved as the authoritative source for design, "
        "colours and proportions only; it does not dictate the rendering style.\n\n"
        "detailed_description:\n"
        f"{STYLE_3D} The clip is 2 to 3 seconds long and loops seamlessly. "
        "[Shot 1] The scene is a studio with a flat chroma-key green backdrop and soft key light "
        "from the upper left plus a gentle rim light separating her hair and whale tail from the "
        "green. <Subject 1> stands centred in frame facing the camera in a calm neutral standing "
        f"pose. {motion}{face}{RULES}\n\n"
        "overall_soundscape:\n"
        "Silence. No speech, no voices, no music and no sound effects at all — a completely silent "
        "clip.\n\n"
        "non_diegetic_music:\n"
        "None. No music of any kind.\n"
    )


PRESETS: dict[str, dict] = {
    "bob": {
        "title": "3D·轻轻浮动",
        "desc": "实体手办原地缓慢上下漂浮，头发发梢和鲸鱼尾巴有延迟地摆动",
        "prompt": _prompt(
            "Motion: she floats slowly up and down in place, rising and falling about four percent "
            "of her body height with a soft, weighty, buoyant rhythm, as if suspended in water. "
            "The sculpted tips of her long hair and her whale tail swing with a slight delay and "
            "follow-through after each rise, the ruffled apron frills and skirt hem drift gently, "
            "and her chest rises and falls with calm breathing."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 3,
    },
    "squat": {
        "title": "3D·蹲下弹起",
        "desc": "实体手办蹲下再弹起，裙摆与尾巴跟着抖一下",
        "prompt": _prompt(
            "Motion: she quickly squats down, her knees bending and her whole body compressing "
            "about ten percent vertically while the skirt hem flares outward, then she springs back "
            "up to her full height with a light bounce, her hair and whale tail lagging behind and "
            "settling with a small overshoot before returning to the neutral standing pose."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "wave": {
        "title": "3D·挥手打招呼",
        "desc": "实体手办抬起右手左右挥手，身体重心轻微摆动",
        "prompt": _prompt(
            "Motion: she raises her right hand up beside her head and waves it side to side twice "
            "in a friendly greeting, her elbow and wrist moving loosely so the motion looks relaxed "
            "and natural. Her body weight shifts very slightly with each wave, her head tilts a "
            "little toward the waving hand, and her long hair and whale tail sway with a gentle "
            "delay. Then she lowers her arm back to the neutral standing pose."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 3,
    },
    "nod": {
        "title": "3D·点头回应",
        "desc": "实体手办轻轻点头两下，刘海和发饰跟着动",
        "prompt": _prompt(
            "Motion: she nods her head down and back up twice in a calm, attentive agreement, the "
            "motion starting from her neck and staying small and natural. Her bangs, her white "
            "ruffled headband and the crescent-moon ornament shift slightly with each nod and "
            "settle back afterwards, and her whale tail gives one slow relaxed swing."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "sway": {
        "title": "3D·左右摇摆",
        "desc": "实体手办上半身左右轻摆，裙摆和尾巴跟着甩",
        "prompt": _prompt(
            "Motion: she sways gently from side to side from the waist, her upper body leaning "
            "softly left and then right like a slow dance step, while her feet stay planted. Her "
            "skirt hem and ruffled apron swing outward against the direction of the lean, and her "
            "long hair and whale tail sweep side to side with a lazy follow-through."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "jump": {
        "title": "3D·原地跳一下",
        "desc": "实体手办轻轻跳一下，落地时裙摆弹动",
        "prompt": _prompt(
            "Motion: she bends her knees and jumps up lightly about fifteen percent of her body "
            "height, tucking her legs slightly at the top of the hop, then lands softly on the same "
            "spot with her knees absorbing the landing. Her hair, skirt hem and whale tail lift on "
            "the way up and bounce once on landing before settling back to the neutral pose."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 1,
    },
    "spin": {
        "title": "3D·转一圈",
        "desc": "实体手办原地转一整圈，裙摆和尾巴飞起来",
        "prompt": _prompt(
            "Motion: she turns a complete three-hundred-and-sixty-degree spin in place, rotating "
            "smoothly and steadily around her own vertical axis and finishing facing the camera "
            "again in the same spot. Her skirt hem flares outward by centrifugal force, her long "
            "hair and whale tail streamed out behind the rotation and settle with follow-through "
            "as she stops."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 1,
    },
    "sleep": {
        "title": "3D·打瞌睡",
        "desc": "实体手办站着打瞌睡，头一点一点地往下垂",
        "prompt": _prompt(
            "Motion: she dozes off while standing, her head slowly drooping forward and her body "
            "sagging a little as she loses focus, then she startles slightly and straightens up, "
            "only to begin drooping again in a slow sleepy rhythm. Her eyelids lower and lift, and "
            "her hair and whale tail hang heavy and swing only faintly."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 1,
    },
}


def get(name: str) -> dict:
    preset = PRESETS[name]
    # 防呆：提示词里绝不允许出现台词（会诱发模型把台词当字幕烧进画面）。
    # 注意 RULES 里的 "no subtitles / no captions" 是**禁止**措辞，属于合法内容，
    # 所以这里只拦"真的写了一句台词"的形态。
    banned = ['"，"', "她说", "台词", "字幕", "：「", "says the line", "spoken line",
              "says:", "saying the words"]
    for token in banned:
        if token.casefold() in preset["prompt"].casefold():
            raise ValueError(f"预设 {name} 的提示词里出现了禁止内容：{token!r}（会诱发字幕）")
    return preset


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for key, preset in PRESETS.items():
        print(f"{key:8} {preset['title']:16} {preset['duration']}s  "
              f"{len(preset['prompt'])} 字符")
