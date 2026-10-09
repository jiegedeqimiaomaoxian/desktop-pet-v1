# -*- coding: utf-8 -*-
"""2D 可爱版动作预设（ComfyUI 版 MiniMax-H3 ref2v 用）。

和 action_presets_3d.py 的区别只有一个核心点：**渲染风格从"实体手办"换成"2D 动漫赛璐璐"**，
但保持同一套 ref2v 结构化提示词骨架（角色锚定 / 保留分析 / 详细描述 / 音频）。

为什么能这么换：
    实测（见 `gen_whale_girl_3d.py` 的反面案例）——**参考图的画风会主导成片风格**。
    参考图是 2D 三视图，所以只要不在提示词里塞 3D 语义（PBR / SSS / 手办 / 路径追踪），
    模型就会老老实实出 2D。3D 那套是**靠强 3D 语义硬掰过去**的；这里反过来，
    明确写"平涂赛璐璐、粗描边、干净线条"，并显式排除 3D/写实/手办。

这一套的重点是"可爱"，分两层写：
    · **表情可爱**：buling 大眼高光、腮红、张嘴笑、眨眼、眯眼笑、歪头
    · **动作可爱**：小而弹、软、有回味（overshoot），手脚幅度小但节奏轻快

踩过的坑（沿用前两轮结论，全部写死）：
  1. 【绝不能写台词】提示词里出现台词 → 模型把台词当字幕烧进画面。
  2. 【不写带符号的拟声词】（哎！嘿！）→ 会画出感叹号/星星特效。
  3. 【不要用"不要…"这类否定句描述角色】模型容易把否定词里的东西画出来，
     所以发光效果用正面措辞写（"无论明暗都保持平整"），不用"别发光"。
"""

from __future__ import annotations

#: 角色锚定（英文，把三视图里的设计细节写清楚 —— ref2v 认细节不认"保持一致"）
CHARACTER = (
    "<Subject 1> is the chibi whale-girl maid character from the model sheet in <Picture 1>: "
    "a small chibi girl with a big round head and a short body, huge sparkling deep-blue eyes with "
    "big bright white highlights and a glossy shine, a tiny nose, a small open smiling mouth, and "
    "soft pink blush marks on both cheeks. She has long wavy hair that is deep navy blue at the "
    "roots and fades to light ice-blue at the tips, a navy crescent-moon hair ornament on top of her "
    "head, a white ruffled maid headband, small blue bow ornaments at both sides of her hair, and "
    "fin-like ears. She wears a navy-blue maid dress with a white frilled apron carrying a small "
    "whale emblem, a white high collar with a navy ribbon bow and a tiny blue gem, white ruffled "
    "trim, gold star decorations on the skirt hem, white tights, dark navy shoes with white trim, "
    "and she has a large navy-blue whale tail with a lighter underside behind her. "
    "<Picture 1> is the official model sheet for <Subject 1> with front, side and back views plus "
    "detail callouts, and it is the authoritative reference for her design, colours, proportions "
    "and outfit. <Subject 1> is the only character on screen."
)

#: 2D 可爱渲染风格：把"这是什么画风"写死（不写 3D 语义，模型就不会往 3D 跑）
STYLE_2D = (
    "Rendering style: a clean Japanese anime cel-shaded 2D illustration, exactly the same style as "
    "<Picture 1> — crisp bold dark outlines of even weight, flat solid colour fills, and simple "
    "two-tone cel shading with a single soft shadow step and one rim-light edge, plus soft airbrush "
    "blush on the cheeks. The eyes are drawn large and sparkling with layered highlights, a bright "
    "upper lash line and a glossy shine. Pastel, bright, soft and gentle colour grading with a "
    "cheerful mood. The illustration is completely flat and two-dimensional: it is NOT 3D, NOT a 3D "
    "render, NOT CGI, NOT a sculpted figurine, NOT photorealistic, and has no real volume, no "
    "physically based materials, no subsurface scattering and no depth of field. "
    "IMPORTANT: <Picture 1> defines both her design AND the visual style of the video."
)

#: 通用约束（每条提示词都会拼上）
RULES = (
    " The camera is COMPLETELY LOCKED OFF — no movement, no sway, no shake, no zoom, no pan, no "
    "tilt and no cut at any point; a single continuous shot. "
    "<Subject 1> stays centred in the frame the whole time and does not walk away; her feet stay in "
    "the same spot. "
    "The background is a completely uniform, clean, flat chroma-key GREEN backdrop (a pure bright "
    "green screen) with absolutely nothing else in it: no props, no furniture, no decorations, no "
    "pattern, no gradient, no blush of light and no ground line. "
    "There must be ABSOLUTELY NO TEXT anywhere in the frame: no subtitles, no dialogue text, no "
    "speech bubbles, no captions, no titles, no watermarks, no signatures and no borders. "
    "There must be NO comic or effect symbols at all: no exclamation marks, no question marks, no "
    "stars, no hearts, no sweat drops, no speed lines, no sparkles, no floating petals, no light "
    "dots and no chibi emotion marks. "
    "Her crescent-moon hair ornament and her bow ornaments stay exactly as drawn in <Picture 1> and "
    "keep the same flat colour and shape whether the scene reads light or dark; nothing on her body "
    "glows or changes brightness. "
    "Her blush marks and her big sparkling eye highlights stay visible through the whole clip. "
    "The frame contains nothing but <Subject 1> and the flat green backdrop. "
    "Her whole body is inside the frame and physically correct, with no extra or duplicated limbs "
    "and no extra fingers. "
    "The first frame and the last frame show the same pose so the clip loops seamlessly."
)

#: 表情（不写台词，只描述表情与口型）
#: 注意：这里以前留着一句 "Her glasses move together with her face…"，
#: 是从别的角色（戴墨镜的那位）复制过来的残留。这只小鲸鱼女仆**没有眼镜**，
#: 留着会让模型时不时给她画一副。已改成本角色真正会动的东西。
FACE = (
    " Her expression is adorable and full of life: her big eyes sparkle with bright highlights, her "
    "cheeks are softly blushed, and her tiny mouth is open in a happy smile. Her crescent-moon hair "
    "ornament, her ruffled headband and her fin-like ears move together with her head whenever she "
    "blinks or tilts it, and her eyes blink softly and naturally. She has no glasses and nothing "
    "covers her eyes. No words and no text appear anywhere."
)

#: 可爱动作的公共写法：小幅度、有弹性、带跟随与回味
BOUNCE = (
    " Keep every motion small, soft, springy and light — a gentle squash-and-stretch with a small "
    "overshoot and follow-through, like a cute animated character, never stiff and never violent."
)

#: 【流畅度约束】直接写给视频模型。
#: 桌宠最怕的就是"顿"：模型偶尔会在一段里插几个重复帧或突然跳一下姿势，
#: 抠像打包后逐帧播放就是肉眼可见的卡顿。在提示词里把"匀速、连续、不要冻结帧"
#: 写死，能从源头减少这类帧（实测比事后插帧划算得多）。
SMOOTH = (
    " MOTION CONTINUITY (very important): the animation is evenly paced and continuous from the "
    "first frame to the very last frame. Every single frame advances the pose by a small, similar "
    "amount — there are NO repeated identical frames, NO frozen holds, NO sudden jumps, NO "
    "teleporting of the body or the limbs, and NO jump cuts anywhere in the clip. The timing eases "
    "in and out smoothly like hand-drawn animation on twos and threes, so the motion reads as one "
    "fluid, gliding movement with no stutter and no jerkiness at any point."
)


def _prompt(motion: str, extra: str = "", face: str = FACE) -> str:
    """拼一条完整的 2D 可爱版 ref2v 提示词。"""
    return (
        "subject_definitions:\n"
        f"{CHARACTER}\n\n"
        "summary:\n"
        "[reference generation] The target video is a short seamlessly looping clip of "
        f"<Subject 1> drawn in the same cute 2D anime style as <Picture 1>, animated adorably on a "
        f"green screen. {STYLE_2D}{motion}{face}{BOUNCE}{SMOOTH}{RULES}\n\n"
        "retention_analysis:\n"
        "<Subject 1> (appears in [Shot 1]): fully_preserved - her navy-to-ice-blue gradient hair, "
        "crescent-moon hair ornament, white ruffled maid headband, side blue bows, fin-like ears, "
        "huge sparkling deep-blue eyes, soft cheek blush, navy and white maid dress with the "
        "whale-emblem apron, collar ribbon with gem, white tights, dark shoes, whale tail and her "
        "chibi proportions are all retained exactly as defined in <Picture 1>, in the same flat "
        "cel-shaded 2D style with the same line weight and colour scheme.\n"
        "<Picture 1> (design and style reference): fully_preserved as the authoritative source for "
        "her design, colours, proportions and the 2D anime illustration style.\n\n"
        "detailed_description:\n"
        f"{STYLE_2D} The clip is 2 to 3 seconds long and loops seamlessly. "
        "[Shot 1] <Subject 1> stands centred in the frame facing the camera on the flat green "
        "backdrop, drawn small and round and cute. She starts from a calm, cheerful standing pose, "
        f"then moves. {motion}{face}{BOUNCE}{SMOOTH}{RULES}\n\n"
        "overall_soundscape:\n"
        "Silence. No speech, no voices, no music and no sound effects at all — a completely silent "
        "clip.\n\n"
        "non_diegetic_music:\n"
        "None. No music of any kind.\n"
    )


PRESETS: dict[str, dict] = {
    "bob": {
        "title": "2D可爱·轻轻弹跳漂浮",
        "desc": "像漂在水里一样上下轻弹，发梢和尾巴慢半拍跟动，眼睛慢慢眨",
        "prompt": _prompt(
            "Motion: she bobs gently up and down in place with a soft springy bounce, rising and "
            "falling about four percent of her body height, her body squashing very slightly at the "
            "bottom of each bounce and stretching a little at the top. The tips of her long hair, her "
            "skirt hem and her whale tail swing with a light delay after each rise, and her ruffled "
            "apron frills flutter. She blinks slowly and contentedly as she floats, her eyes "
            "sparkling each time they open."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 3,
    },
    "wave": {
        "title": "2D可爱·双手挥手招呼",
        "desc": "两只手举到脸旁边左右挥两下，身体跟着轻轻晃，笑得很开心",
        "prompt": _prompt(
            "Motion: this shot is all about the waving, and the waving must be clearly and "
            "continuously visible. She lifts BOTH arms up and out to the sides so that her hands are "
            "raised up beside her face, well clear of her body with a clear gap of background "
            "between each arm and her torso, elbows bent and hands open with the fingers spread. "
            "With her hands up like that she sweeps both hands briskly side to side in a wide arc, "
            "twice: hands swinging out away from her face and then back in again, a big obvious "
            "left-right-left motion of about thirty degrees each way, her wrists and elbows loose "
            "and springy so the hands trail slightly behind the arms. Her whole body rocks very "
            "slightly in time with the waves and she rises onto her toes for a moment at the peak of "
            "each sweep. Her head tilts to one side, she grins widely and her eyes curve into happy "
            "crescents. Her long hair, side bows and whale tail swing along with a light delay. "
            "Then she lowers her arms back down to her sides at the end of the clip. "
            "Keep the arms clearly separated from the torso at all times, and keep the whole arc of "
            "the wave inside the frame."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 3,
    },
    "tilt": {
        "title": "2D可爱·歪头眨眼",
        "desc": "把头歪向一边，眼睛眨一下再睁开，像在撒娇",
        "prompt": _prompt(
            "Motion: she tilts her head slowly over to one side in a curious, coaxing little tilt, "
            "at the same time closing both eyes for a moment and then opening them wide again with a "
            "bright sparkle, and her tiny mouth opens into a soft happy smile. Her big eyes curve "
            "into happy shapes as they close. Her bangs, her white ruffled headband and the "
            "crescent-moon ornament lean with the tilt and settle back as she returns her head to "
            "upright, and her whale tail gives one slow relaxed swing."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 3,
    },
    "spin": {
        "title": "2D可爱·开心转一圈",
        "desc": "原地转一整圈，裙摆像花朵一样张开，转完笑着看镜头",
        "prompt": _prompt(
            "Motion: she twirls through one complete three-hundred-and-sixty-degree spin in place, "
            "rotating smoothly around her own vertical axis with her arms held out a little, then "
            "finishes facing the camera again in exactly the same spot. Her skirt hem and ruffled "
            "apron flare outward like an opening flower as she turns, her long hair and whale tail "
            "stream out behind the rotation and settle with a soft bounce as she stops, and she ends "
            "with a bright happy smile and a tiny bounce."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "squat": {
        "title": "2D可爱·蹲下弹起",
        "desc": "软软地蹲下去再弹回来，裙摆抖一下，像小弹簧",
        "prompt": _prompt(
            "Motion: she squats down softly, her knees bending and her whole body compressing about "
            "ten percent vertically while her skirt hem flares outward like a little bell, and she "
            "presses her hands together in front of her chest as she dips. Then she springs straight "
            "back up to her full height with a light, bouncy hop, her hair and whale tail lagging "
            "behind and settling with a small overshoot before she returns to the neutral standing "
            "pose, smiling the whole way."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "nod": {
        "title": "2D可爱·用力点头",
        "desc": "认真地点头两下，刘海和月牙发饰跟着弹，嘴巴一张一合",
        "prompt": _prompt(
            "Motion: she nods her head down and back up twice in an eager, attentive agreement, the "
            "motion starting from her neck and staying small but springy, with a tiny overshoot at "
            "the top of each nod. Her bangs, her white ruffled headband and the crescent-moon "
            "ornament flip slightly with each nod and settle back afterwards, her tiny mouth opens "
            "and closes along with the nods, and her whale tail gives one slow happy swing."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "jump": {
        "title": "2D可爱·高兴小跳",
        "desc": "屈膝轻轻跳一下，到最高点双腿微收，落地裙摆回弹",
        "prompt": _prompt(
            "Motion: she bends her knees and hops up lightly about fifteen percent of her body "
            "height, tucking her legs up a little at the very top of the hop and throwing both hands "
            "up in the air, then landing softly on the same spot with her knees absorbing the "
            "landing. Her hair, skirt hem and whale tail lift on the way up and bounce once on "
            "landing before settling back to the neutral pose, and she beams with delight."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "sway": {
        "title": "2D可爱·扭扭摇摆",
        "desc": "上半身左右轻轻扭摆，裙摆和尾巴跟着甩，像在哼歌",
        "prompt": _prompt(
            "Motion: she sways gently from side to side from the waist, her upper body leaning softly "
            "left and then right like a happy little dance step, her feet staying planted. Her skirt "
            "hem and ruffled apron swing outward against the direction of the lean, her long hair "
            "and whale tail sweep side to side with a lazy follow-through, and her head tips a "
            "little in the same direction as each lean."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 2,
    },
    "sleep": {
        "title": "2D可爱·打瞌睡",
        "desc": "站着一点点往下垂头，然后惊醒挺直，眼睛一睁一闭",
        "prompt": _prompt(
            "Motion: she dozes off while standing, her head slowly drooping forward and her whole "
            "body sagging a little as she loses focus, her eyelids lowering until her eyes are "
            "closed, then she startles slightly, snaps upright with a small bounce and opens her "
            "eyes wide again, only to begin drooping once more in a slow sleepy rhythm. Her hair and "
            "whale tail hang heavy and swing only faintly, and her little mouth stays slightly open "
            "while she dozes."),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "click_idle", "weight": 1,
    },
}


def get(name: str) -> dict:
    """取预设，并做两项防呆。"""
    preset = PRESETS[name]
    text = preset["prompt"].casefold()

    # 1) 不许出现会诱发字幕的台词写法
    banned = ['"，"', "她说", "台词", "字幕", "：「", "says the line", "spoken line",
              "says:", "saying the words"]
    for token in banned:
        if token.casefold() in text:
            raise ValueError(f"预设 {name} 的提示词里出现了禁止内容：{token!r}（会诱发字幕）")

    # 2) 不许出现**肯定语气**的 3D 语义（会把手办风带回来）。
    #    注意不能简单搜 "3D CGI" —— STYLE_2D 里的排除句正是 "NOT 3D, NOT a 3D render,
    #    NOT CGI..."，那种否定写法是必须保留的。这里只拦"肯定式"写法。
    affirmative = ("is realised as a physical three-dimensional",
                   "physical three-dimensional 3d cgi character",
                   "collectible pvc figurine",
                   "subsurface scattering on the skin")
    for token in affirmative:
        if token in text:
            raise ValueError(f"预设 {name} 混进了肯定语气的 3D 语义：{token!r}")
    # STYLE_2D 必须带上"排除 3D"的那句，否则模型会漂成手办
    if "not 3d" not in text or "not a 3d render" not in text:
        raise ValueError(f"预设 {name} 缺少「排除 3D」的措辞，容易漂成手办风")
    return preset


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for key in PRESETS:
        item = PRESETS[key]
        print(f"{key:8} {item['title']:18} {item['duration']}s  {len(item['prompt'])} 字符")
