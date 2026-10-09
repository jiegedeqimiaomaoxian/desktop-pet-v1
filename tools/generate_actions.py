# -*- coding: utf-8 -*-
"""生成桌宠动作素材：图片 → 视频模型 → 透明帧序列 → 动作清单。

examples
--------
    :: 不花钱，先用本地形变把管道跑通（各生成一套动作）
    python tools\\generate_actions.py --provider mock

    :: 只看要花多少钱/发什么提示词，不真的调用
    python tools\\generate_actions.py --provider fal --actions bob,squat --dry-run

    :: 用可灵真的生成两个动作（Key 放在 apikey.txt）
    python tools\\generate_actions.py --provider fal --actions bob,squat

    :: 已经用别的工具生成好视频了，直接喂进来处理
    python tools\\generate_actions.py --provider file --video D:\\bob.mp4 --actions bob
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tempfix                                           # noqa: E402  (必须早于拆帧)
import action_presets                                     # noqa: E402
import animate_pipeline as pipe                            # noqa: E402
import frames as framelib                                  # noqa: E402
import keyfile                                             # noqa: E402
import providers                                           # noqa: E402

try:
    import action_presets_mmx                            # noqa: E402
except Exception:                                        # 没有也不影响
    action_presets_mmx = None

try:
    import action_presets_3d                             # noqa: E402
except Exception:                                        # 没有也不影响
    action_presets_3d = None

try:
    import action_presets_2dcute                         # noqa: E402
except Exception:                                        # 没有也不影响
    action_presets_2dcute = None

try:
    import action_presets_pet                            # noqa: E402
except Exception:                                        # 没有也不影响
    action_presets_pet = None


def _prefixed_set(module, prefix: str):
    """把一套预设包成"带前缀命名"的版本（动作目录叫 3d_bob，提示词取 bob）。"""
    if module is None:
        return None

    class _Prefixed:
        PRESETS = {f"{prefix}{k}": v for k, v in module.PRESETS.items()}
        DEFAULT_ORDER = [f"{prefix}{k}" for k in getattr(module, "DEFAULT_ORDER",
                                                         list(module.PRESETS))]
        BASE = module          # 记住"没加前缀"的原版，--preset-prefix 要拿它再包一次

        @staticmethod
        def get(name):
            base = name[len(prefix):] if prefix and name.startswith(prefix) else name
            return module.get(base)
    return _Prefixed


#: 提示词方案：
#:   default = 写给云端英文模型（短指令）
#:   mmx     = 写给本机 MiniMax-H3 Gradio 版（中文、2D 赛璐璐、青幕首帧）
#:   3d      = 写给本机 ComfyUI 版 MiniMax-H3 ref2v（英文、3D 手办风、绿幕）
#:   3d_pfx  = 同上，但动作目录带 3d_ 前缀（2D/3D 两套共存）
#:   2dcute  = 同 ref2v，但换成 2D 动漫赛璐璐可爱风
#:   2dcute_pfx = 同上，动作目录带 2d_ 前缀
#:   pet     = 桌宠 v2 的整套素材（待机/视线/被抓/下落/落地/睡着/惊醒/表情）
PRESET_SETS = {name: mod for name, mod in
               (("default", action_presets), ("mmx", action_presets_mmx),
                ("3d", action_presets_3d),
                ("3d_pfx", _prefixed_set(action_presets_3d, "3d_")),
                ("2dcute", action_presets_2dcute),
                ("2dcute_pfx", _prefixed_set(action_presets_2dcute, "2d_")),
                ("pet", action_presets_pet)) if mod}

CACHE_DIR = os.path.join(ROOT, "assets", "source", "video_cache")
PREVIEW_DIR = os.path.join(ROOT, "assets", "source", "action_preview")
INPUT_DIR = os.path.join(ROOT, "assets", "source", "input_frames")


def preset_module(args):
    """取当前生效的提示词方案。

    `--preset-prefix` 可以在方案之上再套一层动作名前缀 ——
    生成器（generate_mmx_comfy.py）用它做"同一套提示词、出好几批素材"，
    比如 2dcute + 前缀 2dh_ 就是"2D 可爱风的高清重制版"，和旧的 2d_ 并存。
    """
    name = getattr(args, "preset_set", "default") or "default"
    if name not in PRESET_SETS:
        raise SystemExit(f"没有这套提示词方案：{name}（可选 {', '.join(PRESET_SETS)}）")
    module = PRESET_SETS[name]
    prefix = (getattr(args, "preset_prefix", "") or "").strip()
    if prefix:
        base = getattr(module, "BASE", module)
        module = _prefixed_set(base, "" if prefix.lower() == "none" else prefix)
    return module


def build_first_frame(name: str, sprite, args):
    """按参数生成"给视频模型的首帧"，存下来（本地模型需要图片路径）。"""
    size = (720, 1280)
    if args.size and "x" in args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
        size = (w, h)
    screen = pipe.pick_screen(sprite)
    frame = pipe.build_input_frame(
        sprite, screen=screen, size=size,
        height_ratio=float(args.char_ratio), baseline=float(args.baseline))
    os.makedirs(INPUT_DIR, exist_ok=True)
    path = os.path.join(INPUT_DIR, f"{name}_{size[0]}x{size[1]}.png")
    frame.save(path)
    return frame, screen, path


def harden_console() -> None:
    """控制台默认 GBK，先把 stdout/stderr 换成 UTF-8，免得打 ¥ 这种字符就崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        enc = (sys.stdout.encoding or "utf-8")
        print(message.encode(enc, "replace").decode(enc, "replace"), flush=True)


harden_console()


# --------------------------------------------------------------------------- 生成

def generate_one(name: str, args, provider, presets=None) -> str | None:
    presets = presets or action_presets
    preset = presets.get(name)
    action_dir = os.path.join(pipe.ACTIONS_DIR, name)
    if os.path.isdir(action_dir) and not args.force and not args.video:
        log(f"  [{name}] 已经有素材了，跳过（要重做加 --force）")
        return action_dir

    sprite = pipe.load_sprite(args.sprite)
    duration = float(args.duration or preset["duration"])
    fps = float(args.fps or preset["fps"])
    first, screen, input_path = build_first_frame(name, sprite, args)
    log(f"  [{name}] {preset['title']}：{duration:g}s @ {fps:g}fps，"
        f"幕布色 {screen}，首帧 {os.path.relpath(input_path, ROOT)}")

    if args.dry_run:
        log(f"  [{name}] --dry-run：不调用接口。")
        log(f"        提示词：{preset['prompt'][:200]}…")
        return None

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{name}.{args.cache_ext}")
    video = None
    if args.video and provider.info.name == "file":
        cache = args.video
        log(f"  [{name}] 使用本地视频 {cache}")
    elif os.path.isfile(cache) and not args.force:
        log(f"  [{name}] 命中视频缓存 {cache}")
    else:
        log(f"  [{name}] 调用 {provider.info.label} 生成中（可能要几分钟）…")
        started = time.time()
        import io
        buf = io.BytesIO()
        first.save(buf, format="PNG")
        video = provider.generate(preset["prompt"], buf.getvalue(), duration=duration,
                                  model=args.model or None, resolution=args.resolution,
                                  fps=fps)
        log(f"  [{name}] 生成完成，用时 {time.time() - started:.0f}s，"
            f"{len(video.data) / 1e6:.1f} MB")
        if video.info.get("frames_dir"):
            cache = None
        else:
            with open(cache, "wb") as fh:
                fh.write(video.data)

    # --- 拆帧 ---
    if video is not None and video.info.get("frames_dir"):
        frame_paths = sorted(
            os.path.join(video.info["frames_dir"], f)
            for f in os.listdir(video.info["frames_dir"]) if f.startswith("f"))
        tmpdir = video.info["frames_dir"]
        log(f"  [{name}] 直接使用 {len(frame_paths)} 张帧（未经视频编码）")
    else:
        with open(cache, "rb") as fh:
            data = fh.read()
        fmt = os.path.splitext(cache)[1].lstrip(".") or "mp4"
        frame_paths, tmpdir, info = framelib.load_frames(
            data, fmt=fmt, fps=fps, max_frames=args.max_frames)
        log(f"  [{name}] 拆出 {len(frame_paths)} 帧"
            + (f"，视频 {info.get('width')}x{info.get('height')} @ {info.get('fps')}fps"
               if info.get("width") else ""))

    # --- 抠像 / 稳定 / 打包 ---
    try:
        if args.key == "hue":
            # 色相判据：抗幕布明暗渐变（3D 手办风的"绿幕"其实是橄榄绿渐变）
            rgba = pipe.frames_to_rgba_hue(frame_paths, inner=args.key_low,
                                           outer=args.key_high,
                                           min_sat=args.key_min_sat,
                                           contamination=args.key_contamination)
            log(f"  [{name}] 色相抠像（inner={args.key_low} outer={args.key_high} "
                f"min_sat={args.key_min_sat} 污染阈值={args.key_contamination}）")
        else:
            rgba = pipe.frames_to_rgba(frame_paths, tol=args.tolerance,
                                       mask_top=args.mask_top)
            log(f"  [{name}] 抠掉幕布，得到透明帧"
                + (f"（顶部 {args.mask_top:.0%} 已抹透明，用来清字幕）" if args.mask_top else ""))
        if args.mask_top:
            cut = int(rgba[0].height * args.mask_top)
            if cut > 0:
                for frame in rgba:
                    alpha = frame.getchannel("A")
                    alpha.paste(0, (0, 0, frame.width, cut))
                    frame.putalpha(alpha)
                log(f"  [{name}] 顶部 {args.mask_top:.0%} 已抹透明")
        if args.despill > 0:
            rgba = pipe.despill(rgba, strength=args.despill)
            log(f"  [{name}] 去绿幕环境光（强度 {args.despill}）")
        tiles = pipe.stabilize_and_crop(rgba, target_height=args.height, pad=args.pad,
                                        skip_top=args.skip_top,
                                        stabilize=not args.no_stabilize)
        if preset.get("loop") and not args.no_trim:
            before = len(tiles)
            tiles = pipe.trim_loop(tiles)
            if len(tiles) != before:
                log(f"  [{name}] 去掉尾部重复帧 {before} -> {len(tiles)}")
        tiles = pipe.harden(tiles)
        if args.frames and len(tiles) > args.frames:
            step = len(tiles) / args.frames
            tiles = [tiles[int(i * step)] for i in range(args.frames)]
            log(f"  [{name}] 抽稀到 {len(tiles)} 帧")

        saved = pipe.save_action(name, tiles, fps=fps, loop=bool(preset.get("loop")),
                                 action_dir=action_dir, quantize=bool(args.quantize),
                                 extra={"title": preset["title"], "desc": preset["desc"],
                                        "trigger": preset.get("trigger", "click_idle"),
                                        "weight": preset.get("weight", 1),
                                        "prompt": preset["prompt"],
                                        "provider": provider.info.name,
                                        "source_video": os.path.basename(cache) if cache else "",
                                        "created": time.strftime("%Y-%m-%d %H:%M:%S")})
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        pipe.preview_gif(tiles, os.path.join(PREVIEW_DIR, f"{name}.gif"), fps=fps)
        pipe.contact_sheet(tiles, os.path.join(PREVIEW_DIR, f"{name}_sheet.png"))
    except Exception:
        import traceback
        log(f"  [{name}] 处理失败：")
        traceback.print_exc()
        raise
    log(f"  [{name}] 已保存 {len(tiles)} 帧 -> {os.path.relpath(saved, ROOT)}"
        f"（预览 {os.path.relpath(PREVIEW_DIR, ROOT)}\\{name}.gif）")
    if tmpdir and os.path.isdir(tmpdir) and not args.keep_temp:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return saved


# --------------------------------------------------------------------------- 汇总

def rebuild_library() -> str:
    """扫描 assets/actions 下的 action.json，汇总成桌宠读取的总清单。"""
    entries = {}
    if os.path.isdir(pipe.ACTIONS_DIR):
        for name in sorted(os.listdir(pipe.ACTIONS_DIR)):
            manifest_path = os.path.join(pipe.ACTIONS_DIR, name, "action.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                log(f"  [清单] {name} 读取失败：{exc}")
                continue
            frames_dir = os.path.join(ROOT, data.get("frames_dir", ""))
            count = len([f for f in os.listdir(frames_dir) if f.endswith(".png")]) \
                if os.path.isdir(frames_dir) else 0
            data["frames"] = count or data.get("frames", 0)
            if not data["frames"]:
                log(f"  [清单] {name} 没有帧，跳过")
                continue
            entries[name] = data
    library = {
        "version": 1,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "actions": entries,
    }
    path = os.path.join(pipe.ACTIONS_DIR, "library.json")
    os.makedirs(pipe.ACTIONS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(library, fh, ensure_ascii=False, indent=2)
    return path


def preview_preset(name: str, preset: dict, duration: float, fps: float,
                   sprite, args) -> str:
    """不调用接口，先用本地形变演一遍这个动作，让人看到"大概是什么效果"。

    注意：形变要作用在"角色精灵"上，而不是已经合成好的首帧，
    否则连幕布一起缩放，抠像就全乱了。
    """
    from mock_provider import MockProvider
    screen = pipe.pick_screen(sprite)
    # 先把精灵摆到幕布上（和真实生成时的首帧一致），再让 mock 在那个首帧上做形变
    first = pipe.build_input_frame(sprite, screen=screen, size=(720, 1280))
    mock = MockProvider(fps=fps, duration=duration)
    frames = mock.render_frames(name if name in MockProvider.MOTIONS else "bob",
                                first, first.size, screen, fit=False)
    rgba = pipe.frames_to_rgba_from_images(frames, screen=screen)
    tiles = pipe.harden(pipe.stabilize_and_crop(rgba, target_height=args.height,
                                                pad=args.pad))
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    gif = os.path.join(PREVIEW_DIR, f"{name}_dryrun.gif")
    pipe.preview_gif(tiles, gif, fps=fps)
    return gif


def estimate_cost(args, names: list[str], provider, presets=None) -> float:
    presets = presets or action_presets
    seconds = sum(float(args.duration or presets.get(n)["duration"]) for n in names)
    log("")
    log(f"计划生成 {len(names)} 个动作，共约 {seconds:.0f} 秒素材：")
    for name in names:
        preset = presets.get(name)
        log(f"  · {name:6} {preset['title']:8} {args.duration or preset['duration']:>4}s")
    rates = {"fal": 0.029, "replicate": 0.032, "openai": 0.10, "mock": 0.0, "file": 0.0}
    rate = rates.get(provider.info.name, 0.03)
    cost = seconds * rate
    log(f"参考单价 ${rate}/秒（{provider.info.name}）→ 预计 ${cost:.2f}"
        f"（≈ ¥{cost * 7.2:.2f}）")
    if provider.info.note:
        log(f"备注：{provider.info.note}")
    return cost


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用视频模型生成桌宠动作素材",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("--provider", default="mock",
                        choices=["mock", "fal", "replicate", "openai", "mmx-local", "file"],
                        help="视频服务商（默认 mock，不花钱；mmx-local = 本机 MiniMax-H3）")
    parser.add_argument("--preset-set", default="default",
                        choices=sorted(PRESET_SETS),
                        help="提示词方案：default=云端英文模型，mmx=本机 MiniMax-H3（中文+台词）")
    parser.add_argument("--preset-prefix", default="",
                        help="在方案之上再套一层动作名前缀（如 2dh_）。"
                             "让同一套提示词可以出好几批素材、互不覆盖")
    parser.add_argument("--size", default="",
                        help="首帧尺寸 宽x高（如 480x832）；本机 MiniMax 出图尺寸要对齐它")
    parser.add_argument("--char-ratio", type=float, default=0.62,
                        help="角色高度占画面的比例（默认 0.62）")
    parser.add_argument("--baseline", type=float, default=0.88,
                        help="脚底落在画面高度的百分之几（默认 0.88）")
    parser.add_argument("--actions", default="",
                        help="要生成的动作，逗号分隔；默认按推荐顺序 "
                             "（--provider mock 时默认全部）")
    parser.add_argument("--model", default="", help="模型/端点 ID，覆盖默认值")
    parser.add_argument("--resolution", default="720p", help="分辨率参数（部分模型用）")
    parser.add_argument("--duration", type=float, default=0.0, help="每个动作时长（秒）")
    parser.add_argument("--fps", type=float, default=0.0, help="抽帧帧率（默认取预设）")
    parser.add_argument("--height", type=int, default=430, help="成品帧高度（像素）")
    parser.add_argument("--frames", type=int, default=0, help="限制每个动作的帧数")
    parser.add_argument("--max-frames", type=int, default=96, help="抽帧上限")
    parser.add_argument("--tolerance", type=float, default=34.0, help="抠幕布容差")
    parser.add_argument("--key", choices=("auto", "hue"), default="auto",
                        help="抠像方式：auto=按边框采样色的距离（老行为）；"
                             "hue=色相判据（3D 手办风的橄榄绿渐变幕布用这个）")
    parser.add_argument("--key-low", type=float, default=12.0,
                        help="--key hue：与幕布色相距离小于此值判为背景（度）")
    parser.add_argument("--key-high", type=float, default=30.0,
                        help="--key hue：距离大于此值判为角色（度）")
    parser.add_argument("--key-min-sat", type=float, default=0.10,
                        help="--key hue：饱和度低于此值算中性色（白围裙等），交给污染阈值判断")
    parser.add_argument("--key-contamination", type=float, default=10.0,
                        help="--key hue：中性像素的 g-max(r,b) 超过它就算幕布光污染，一并抠掉")
    parser.add_argument("--despill", type=float, default=0.0,
                        help="去绿幕环境光强度 0~1（0=关）。3D 手办风的绿幕会反射到"
                             "白裤袜/浅色布料上，建议 0.85")
    parser.add_argument("--mask-top", type=float, default=0.0,
                        help="把画面上方这个比例抹透明（默认 0；有的模型会把台词烧成字幕）")
    parser.add_argument("--keep-captions", action="store_true",
                        help="不要自动检测/抹掉烧进画面的字幕")
    parser.add_argument("--caption-check", action="store_true",
                        help="额外用「帧间静止」特征抹字幕"
                             "（白色围裙这类不动的高光容易误伤，默认关）")
    parser.add_argument("--pad", type=int, default=6, help="裁切时脚下留白")
    parser.add_argument("--skip-top", type=float, default=0.0,
                        help="量包围盒时忽略画面上方这个比例（清字幕用；默认 0，"
                             "忽略顶部会把头顶的月牙发饰裁掉）")
    parser.add_argument("--no-stabilize", action="store_true",
                        help="不做逐帧重摆位。逐帧按包围盒对齐会抵消蹦跳的位移、"
                             "并引入包围盒噪声抖动，锁死镜头的素材建议关掉")
    parser.add_argument("--sprite", default="", help="自定义精灵 PNG")
    parser.add_argument("--video", default="", help="本地视频文件（配合 --provider file）")
    parser.add_argument("--cache-ext", default="mp4", help="视频缓存扩展名")
    parser.add_argument("--force", action="store_true", help="忽略缓存重做")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调用接口：出预览 GIF + 提示词 + 费用估算")
    parser.add_argument("--no-trim", action="store_true", help="不要去掉尾部重复帧")
    parser.add_argument("--quantize", action="store_true",
                        help="帧存成调色板 PNG（体积小很多，但运行时会掉透明度，慎用）")
    parser.add_argument("--keep-temp", action="store_true", help="保留拆帧临时目录")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="某个动作失败也继续做后面的")
    parser.add_argument("--yes", action="store_true", help="花钱前不再确认")
    parser.add_argument("--list", action="store_true", help="列出所有动作预设")
    parser.add_argument("--list-models", action="store_true", help="列出服务商可用模型")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.list:
        presets = preset_module(args)
        log(f"可用动作预设（当前方案：{args.preset_set}）：")
        for name in presets.DEFAULT_ORDER:
            preset = presets.get(name)
            log(f"  {name:6} {preset['title']:10} {preset['duration']:>4}s  "
                f"{preset['desc']}")
        return 0

    if args.list_models:
        keys = keyfile.load_keys()
        for name in ("fal", "replicate", "openai"):
            try:
                provider = providers.get_provider(name, keys)
            except Exception as exc:
                log(f"{name:10} 不可用：{exc}")
                continue
            log(f"{name:10} {provider.info.label}")
            for model in provider.info.models:
                log(f"           · {model}")
        if args.provider == "fal":
            try:
                log("fal 上实际的图生视频模型（实时查询）：")
                for model_id, title in providers.list_fal_models("kling", keyfile.key_for("fal", keys)):
                    log(f"  {model_id}   {title}")
            except Exception as exc:
                log(f"  查询失败：{exc}")
        return 0

    presets = preset_module(args)
    if args.actions:
        names = [n.strip() for n in args.actions.split(",") if n.strip()]
    elif args.provider in ("mock", "file"):
        names = list(presets.PRESETS)
    else:
        names = presets.DEFAULT_ORDER[:2]
    unknown = [n for n in names if n not in presets.PRESETS]
    if unknown:
        log(f"不认识的动作：{unknown}\n可选：{', '.join(presets.PRESETS)}")
        return 2

    keys = keyfile.load_keys()
    try:
        provider = providers.get_provider(args.provider, keys,
                                          sprite=args.sprite or None,
                                          path=args.video)
        log(f"服务商：{provider.info.label}"
            f"（Key 来源：{keyfile.describe(args.provider, keys)}）")
    except Exception as exc:
        if not args.dry_run:
            log(f"服务商不可用：{exc}")
            return 2
        provider = None
        log(f"服务商暂不可用（{exc}）—— dry-run 不需要 Key，继续出预览。")

    cost = 0.0
    if provider is not None:
        cost = estimate_cost(args, names, provider, presets)
    else:
        log("")
        log(f"计划生成 {len(names)} 个动作：{', '.join(names)}")
    if args.dry_run:
        log("")
        log("--dry-run：不调用任何接口。下面会用本地形变演一遍每个动作，")
        log("         产出预览 GIF，先看效果再决定要不要花钱。")
        log("")
        sprite = pipe.load_sprite(args.sprite)
        for name in names:
            preset = presets.get(name)
            try:
                gif = preview_preset(name, preset, float(args.duration or preset["duration"]),
                                     float(args.fps or preset["fps"]), sprite, args)
                log(f"  [{name}] {preset['title']}：预览 {os.path.relpath(gif, ROOT)}")
            except Exception as exc:
                log(f"  [{name}] 预览失败：{type(exc).__name__}: {exc}")
            log(f"         提示词：{preset['prompt'][:150]}…")
        log("")
        log("满意的话去掉 --dry-run 再跑一次就会真的调用接口。")
        return 0

    if cost > 0.5 and not args.yes and sys.stdin and sys.stdin.isatty():
        answer = input(f"预计花费 ${cost:.2f}（≈¥{cost * 7.2:.2f}），继续吗？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            log("已取消，没有产生任何费用。")
            return 0
    log("")

    ok, failed = [], []
    for name in names:
        try:
            result = generate_one(name, args, provider, presets)
            (ok if result else failed if not args.dry_run else ok).append(name)
        except Exception as exc:
            failed.append(name)
            log(f"  [{name}] 失败：{type(exc).__name__}: {exc}")
            if not args.continue_on_error:
                log("  （加 --continue-on-error 可以跳过失败继续做下一个）")
                break

    library = rebuild_library()
    log("")
    log(f"动作清单：{os.path.relpath(library, ROOT)}")
    if ok:
        log(f"成功：{', '.join(ok)}")
    if failed:
        log(f"失败/跳过：{', '.join(failed)}")
    log("重启桌宠即可看到新动作（右键 → 退出，再双击 启动桌宠.vbs）。")
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("\n已中断。")
        raise SystemExit(130)
