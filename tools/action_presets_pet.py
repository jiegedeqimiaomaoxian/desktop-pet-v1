# -*- coding: utf-8 -*-
"""桌宠 v2 的素材清单：待机 / 视线 / 被抓 / 下落 / 落地 / 睡着 / 惊醒 / 表情。

和 `action_presets_2dcute.py` 的关系
------------------------------------
**风格段落一个字都不重写** —— 直接 import 它的 `CHARACTER` / `STYLE_2D` / `RULES` /
`FACE` / `BOUNCE` / `SMOOTH`。提示词里描述画风的那几段只要改一个字，出来的角色
就可能变样；共用一个来源是保证"整套素材像同一个人画的"最省事的办法。

和"点击动作"的关系
------------------
点击动作（`act_*`，9 个）是上一批用 **同一个参考图 + 同一个 seed** 出的，
所以这里的每一条也沿用 **同一个参考图 + 同一个 seed** —— 这样待机和动作才是
同一个角色。上一版最大的毛病就是：待机精灵是从三视图裁的静态图，动作是模型
重新演绎的，**两者根本不像同一个人**（发型长度、月牙发饰大小、体型都不一样）。
这一版把待机也交给模型出，从根上解决。

命名约定
--------
    idle / gaze_*          待机类（循环）
    held / falling         状态类（循环）
    landing / waking       状态类（一次性）
    asleep                 状态类（循环）
    cheer / shy / gasp     表情类（一次性）
    act_*                  点击动作（沿用上一批）
"""

from __future__ import annotations

import action_presets_2dcute as base

CHARACTER = base.CHARACTER
STYLE_2D = base.STYLE_2D
RULES = base.RULES
FACE = base.FACE
BOUNCE = base.BOUNCE
SMOOTH = base.SMOOTH

#: RULES 里有一句"她的脚始终停在原地"。被抓 / 下落 / 落地这三条**必须**去掉它，
#: 否则模型会一边飘一边把脚钉在地上，出来是废片。
RULES_FREE = RULES.replace(
    "<Subject 1> stays centred in the frame the whole time and does not walk away; "
    "her feet stay in the same spot. ",
    "<Subject 1> stays centred horizontally in the frame the whole time, but her whole body "
    "is free to move vertically inside the frame — she does not walk away sideways. ")

#: 待机类要的是"活着"，不是"在表演"：把幅度压到极小写死
CALM = (
    " IMPORTANT — this is a calm idle loop, NOT a performance: the motion is extremely subtle "
    "and gentle, at a slow and even tempo. Nothing about her pose changes dramatically; she simply "
    "keeps breathing and stays alive on screen. Do not make her walk, jump, spin, wave or pose."
)

#: 视线要保持住（不能看一眼又转回来）
HOLD_GAZE = (
    " She keeps this gaze direction for the ENTIRE clip from the first frame to the last frame "
    "and never returns her gaze to the camera at any point."
)


def _prompt(motion: str, face: str = FACE, rules: str = RULES,
            extra: str = "", seconds: str = "2 to 3") -> str:
    """拼一条完整的 ref2v 提示词（结构照抄 2dcute 那套，只有动作段是新的）。"""
    return (
        "subject_definitions:\n"
        f"{CHARACTER}\n\n"
        "summary:\n"
        "[reference generation] The target video is a short clip of <Subject 1> drawn in the same "
        f"cute 2D anime style as <Picture 1>, animated adorably on a green screen. "
        f"{STYLE_2D}{motion}{extra}{face}{BOUNCE}{SMOOTH}{rules}\n\n"
        "retention_analysis:\n"
        "<Subject 1> (appears in the shot): fully_preserved - her navy-to-ice-blue gradient hair, "
        "crescent-moon hair ornament, white ruffled maid headband, side blue bows, fin-like ears, "
        "huge sparkling deep-blue eyes, soft cheek blush, navy and white maid dress with the "
        "whale-emblem apron, collar ribbon with gem, white tights, dark shoes, whale tail and her "
        "chibi proportions are all retained exactly as defined in <Picture 1>, in the same flat "
        "cel-shaded 2D style with the same line weight and colour scheme.\n"
        "<Picture 1> (design and style reference): fully_preserved as the authoritative source for "
        "her design, colours, proportions and the 2D anime illustration style.\n\n"
        "detailed_description:\n"
        f"{STYLE_2D} The clip is {seconds} seconds long. "
        "[Shot 1] <Subject 1> stands centred in the frame facing the camera on the flat green "
        f"backdrop, drawn small and round and cute. She starts from a calm, cheerful standing pose, "
        f"then moves. {motion}{extra}{face}{BOUNCE}{SMOOTH}{rules}\n\n"
        "overall_soundscape:\n"
        "Silence. No speech, no voices, no music and no sound effects at all — a completely silent "
        "clip.\n\n"
        "non_diegetic_music:\n"
        "None. No music of any kind.\n"
    )


# --------------------------------------------------------------------------- 动作描述

M_IDLE = (
    "Motion: she is standing still and simply breathing. Her chest and shoulders rise and fall "
    "very slowly and evenly, about two percent of her body height, and her whole body drifts up "
    "and down by a barely visible amount with each breath. The tips of her long wavy hair, the "
    "hem of her skirt, her apron frills and her whale tail sway and settle a moment BEHIND each "
    "breath, with a soft delayed follow-through. Her head has a tiny, slow, natural drift. "
    "She blinks softly two or three times during the clip, unhurried and natural, and her eyes "
    "sparkle each time they open. Her arms rest at her sides and her feet stay planted."
    + CALM
)

M_GAZE_LEFT = (
    "Motion: she is standing still and breathing gently, exactly like a calm idle loop, but her "
    "HEAD AND EYES ARE TURNED TO THE LEFT SIDE OF THE FRAME (which is her own right): her face "
    "turns about twenty degrees to the left of the camera, her pupils look toward the left edge "
    "of the frame, and her crescent-moon hair ornament and headband turn with her head. Her body "
    "stays facing the camera and does not turn. Her hair tips, skirt hem and whale tail sway "
    "gently in the delayed way they do when she breathes, and she blinks softly once or twice."
    + HOLD_GAZE + CALM
)

M_GAZE_RIGHT = (
    "Motion: she is standing still and breathing gently, exactly like a calm idle loop, but her "
    "HEAD AND EYES ARE TURNED TO THE RIGHT SIDE OF THE FRAME (which is her own left): her face "
    "turns about twenty degrees to the right of the camera, her pupils look toward the right edge "
    "of the frame, and her crescent-moon hair ornament and headband turn with her head. Her body "
    "stays facing the camera and does not turn. Her hair tips, skirt hem and whale tail sway "
    "gently in the delayed way they do when she breathes, and she blinks softly once or twice."
    + HOLD_GAZE + CALM
)

M_GAZE_UP = (
    "Motion: she is standing still and breathing gently, exactly like a calm idle loop, but her "
    "HEAD IS TILTED UP and her EYES ARE LOOKING UPWARD toward the top of the frame, as if "
    "something is floating above her. Her chin lifts, her head tilts back slightly, and her "
    "pupils look up. Her body stays facing the camera. Her hair tips and whale tail sway gently "
    "in the delayed way they do when she breathes, and she blinks softly."
    + HOLD_GAZE + CALM
)

M_HELD = (
    "Motion: she is being LIFTED UP BY AN INVISIBLE HAND GRIPPING THE BACK OF HER COLLAR, like a "
    "kitten picked up by its scruff. Her shoulders are pulled up and she hangs suspended: her "
    "arms are raised loosely above her shoulders and sway, her legs hang straight down and swing "
    "gently back and forth like a pendulum, her body is stretched slightly longer than usual, and "
    "her whole body swings softly side to side as if dangling. Her long hair falls upward around "
    "the invisible grip and her skirt and whale tail hang straight down and sway with the "
    "pendulum, lagging behind the body. Her expression is a startled, wide-eyed surprise that "
    "settles into a resigned little pout. Her feet are off the ground and she is floating slightly "
    "higher in the frame than usual."
)

M_FALLING = (
    "Motion: she is FALLING straight down through the air. Her arms are flung out to the sides, "
    "her legs are bent and tucked up slightly, and her whole body leans back a little from the "
    "rush of air. Her long hair, her skirt hem, her apron frills and her whale tail are all blown "
    "UPWARD and flutter continuously, streaming above and around her, and they keep fluttering "
    "the whole time. Her body wobbles slightly from side to side as she falls. Her expression is "
    "a wide-eyed, open-mouthed startled yelp. Her feet are off the ground and she hangs in the "
    "middle of the frame."
)

M_LANDING = (
    "Motion: this is a landing, in three clear beats. Beat one: she drops in from above and her "
    "feet hit the ground, and on impact her whole body SQUASHES down — she is compressed shorter "
    "and wider, her knees bend deeply, her head sinks into her shoulders, her hair and skirt are "
    "still blown upward from the fall. Beat two: she springs back up and STRETCHES taller than "
    "her normal height for a moment, her arms lift, her hair and skirt flip down and overshoot. "
    "Beat three: she settles back into her normal calm standing pose with one small extra bounce "
    "of her skirt hem and one flick of her whale tail, and her expression relaxes from a startled "
    "face into a relieved smile. The first frame and the last frame are both her normal standing "
    "pose at her normal height so the clip connects cleanly to her idle animation."
)

M_ASLEEP = (
    "Motion: she is fast asleep while standing. Her eyes are CLOSED the whole time — drawn as "
    "gentle closed curves with her lashes showing, never open. Her head droops slowly forward and "
    "down, then nods back up a little, then droops again, in a slow sleepy rhythm with a long "
    "pause between nods. Her breathing is slow and deep, her chest and shoulders rising and "
    "falling more than usual. Her whole body leans very slightly forward and sways a tiny amount. "
    "Her hair tips, skirt hem and whale tail hang and sway slowly and sleepily. Her mouth is "
    "small and relaxed. She is calm and peaceful."
)

M_WAKING = (
    "Motion: she is waking up with a start, in three clear beats. Beat one: she is asleep, head "
    "drooped forward, eyes closed. Beat two: she JERKS upright all at once — her head snaps up, "
    "her eyes fly wide open, her body straightens and lifts, her shoulders jump up, and her hair, "
    "hair ornament and skirt all bounce and wobble from the sudden movement. Beat three: she "
    "settles, blinks twice quickly, and her expression turns into a slightly embarrassed little "
    "smile. The first frame is her asleep pose; the last frame is her normal standing pose."
)

M_CHEER = (
    "Motion: she is delighted and bounces on the spot twice. Each bounce she pushes up off the "
    "ground a small amount, her arms lift happily, and her whole body squashes slightly at the "
    "bottom of each bounce and stretches at the top. On each landing her skirt hem, apron frills "
    "and whale tail flip up and settle with a springy overshoot, and her whale tail wags quickly "
    "side to side. Her eyes are squeezed shut in a big happy smile with her mouth wide open and "
    "her cheeks brightly blushed. The first frame and the last frame are the same normal standing "
    "pose."
)

M_SHY = (
    "Motion: she is embarrassed and shy. She raises BOTH HANDS UP TO HER CHEEKS and covers part of "
    "her face with them, her shoulders hunch up, and she turns her head slightly away from the "
    "camera and dips it down. Her cheek blush is noticeably deeper and pinker than usual. Then "
    "she slowly peeks back up over her fingertips at the camera, still covering her cheeks, and "
    "her eyes dart away again. Her hair tips and whale tail curl slightly inward. Her mouth is a "
    "small embarrassed squiggle. The first frame and the last frame are the same normal standing "
    "pose."
)

M_GASP = (
    "Motion: she is startled. Her whole body JERKS backward and up in one sudden movement — she "
    "leans back away from the camera, her shoulders jump, and her arms fly up. Her eyes fly WIDE "
    "open with the pupils shrunk small, and her mouth opens into a small round O. Her hair, her "
    "crescent-moon ornament, her headband and her skirt all bounce and wobble from the sudden "
    "jolt, then settle. She then holds that startled pose for the rest of the clip, trembling very "
    "slightly. The first frame is her normal standing pose; the last frame is the startled pose."
)


PRESETS: dict[str, dict] = {
    # ---------------------------------------------------------------- 待机类
    "idle": {
        "title": "待机·呼吸眨眼",
        "desc": "静静站着呼吸，发梢裙摆尾巴慢半拍跟动，偶尔眨一下眼",
        "prompt": _prompt(M_IDLE, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "idle", "weight": 1,
    },
    "gaze_left": {
        "title": "待机·看向左边",
        "desc": "身体朝前，头和眼睛转向画面左侧，保持住不转回来",
        "prompt": _prompt(M_GAZE_LEFT, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "idle", "weight": 1,
    },
    "gaze_right": {
        "title": "待机·看向右边",
        "desc": "身体朝前，头和眼睛转向画面右侧，保持住不转回来",
        "prompt": _prompt(M_GAZE_RIGHT, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "idle", "weight": 1,
    },
    "gaze_up": {
        "title": "待机·抬头看上面",
        "desc": "下巴微抬、眼睛向上看，像在看飘过头顶的东西",
        "prompt": _prompt(M_GAZE_UP, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "idle", "weight": 1,
    },
    # ---------------------------------------------------------------- 状态类
    "held": {
        "title": "被拎起来",
        "desc": "后领被拎住悬空，手臂上举、腿垂下钟摆式晃动，一脸无奈",
        "prompt": _prompt(M_HELD, rules=RULES_FREE, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "drag", "weight": 1,
    },
    "falling": {
        "title": "下落中",
        "desc": "往下掉，裙摆头发全向上翻飞，手脚张开，一脸惊慌",
        "prompt": _prompt(M_FALLING, rules=RULES_FREE, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "fall", "weight": 1,
    },
    "landing": {
        "title": "落地回弹",
        "desc": "落地压扁 → 弹起拉长 → 抖一下站好，首尾都是站姿",
        "prompt": _prompt(M_LANDING, rules=RULES_FREE, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": False,
        "trigger": "land", "weight": 1,
    },
    "asleep": {
        "title": "睡着了",
        "desc": "闭着眼，头一点一点往下垂，呼吸又慢又深",
        "prompt": _prompt(M_ASLEEP, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": True,
        "trigger": "sleep", "weight": 1,
    },
    "waking": {
        "title": "惊醒",
        "desc": "猛地抬头睁大眼，头发弹一下，然后不好意思地笑",
        "prompt": _prompt(M_WAKING, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": False,
        "trigger": "wake", "weight": 1,
    },
    # ---------------------------------------------------------------- 表情类
    "cheer": {
        "title": "开心地蹦两下",
        "desc": "眯眼大笑原地蹦两下，尾巴飞快摇",
        "prompt": _prompt(M_CHEER, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": False,
        "trigger": "emote", "weight": 1,
    },
    "shy": {
        "title": "害羞捂脸",
        "desc": "双手捧脸、脸红加深、别过头去，又偷偷抬头看",
        "prompt": _prompt(M_SHY, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": False,
        "trigger": "emote", "weight": 1,
    },
    "gasp": {
        "title": "吓一跳",
        "desc": "整个人往后一震，眼睛瞪圆嘴张成 O，然后僵住微微发抖",
        "prompt": _prompt(M_GASP, seconds="2 to 3"),
        "duration": 2.33, "fps": 24.0, "loop": False,
        "trigger": "emote", "weight": 1,
    },
}

#: 明确声明"哪些是循环的"，`generate_actions.py --list` 会用到
DEFAULT_ORDER = list(PRESETS)


def get(name: str) -> dict:
    if name not in PRESETS:
        raise KeyError(f"没有这个动作：{name}（可选 {', '.join(PRESETS)}）")
    return PRESETS[name]


if __name__ == "__main__":
    for key, item in PRESETS.items():
        print(f"{key:12} {item['title']:16} {'循环' if item['loop'] else '一次性'}"
              f"  {len(item['prompt'])} 字符")
