# -*- coding: utf-8 -*-
"""算 / 调"每个片段该放大多少倍"，让角色在状态切换时**看起来一样大**。

为什么需要
----------
视频模型不是逐像素复用参考图的，它在每一段里**重新演绎**角色。大多数片段
她的大小是一致的，但姿势差异大的那几段（被拎起来、下落）它会为了把张开的
头发和四肢塞进画面而**把她画小**。实测：

    idle      100%（基准）
    held       74%      ← 一眼就看得出来缩水了
    falling    68%      ← 同上
    landing    88%
    其余      96~107%

按"内容并集高度"缩放是看不出这个问题的（各片段内容高都是 422~427），
因为她的头发/四肢把画面撑满了，撑出来的高度掩盖了身体变小。

怎么算
------
用**不透明像素面积的平方根**当"角色有多大"的代理（面积 ∝ 尺寸²），
在一段里取若干帧求中位数，再和 `idle` 比。实测这个代理和肉眼判读
平均只差 0.045，比"行宽中位数""顶部最大行宽"之类稳得多。

结果写进 `assets/size_fix.json`，**和生成的素材分开** ——
素材是模型产物、每次重跑都可能变；这一层是人工校准，不该被覆盖。
想手工微调就改那个文件（改完重启桌宠生效）。

用法：
    python tools\\tune_sizes.py             算一遍并写 size_fix.json
    python tools\\tune_sizes.py --render    顺手画一张对比图（归一化后并排）
    python tools\\tune_sizes.py --show      只打印，不写文件
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pet import clips as clips_mod          # noqa: E402

FIX_PATH = os.path.join(ROOT, "assets", "size_fix.json")
REFERENCE = "idle"
SAMPLES = 7                                  # 一段里取几帧求中位数

#: 「压扁姿势」片段：面积天然就小，但**不是**模型把角色画小了，不该放大。
#:
#: 这是面积代理唯一的盲区：它分不清
#:     ① 模型把她整体画小了（面积 ∝ 尺寸²，该放大）
#:     ② 她自己蹲下去了（高度↓宽度↑，面积也小，但**不该**放大）
#: 从剪影上这两件事很难自动分开（头发和四肢会把包围盒撑满），
#: 所以这里用一份显式名单，配合 tune_sizes.py 画的对比图人工确认。
#: `act_jump` / `act_squat` 是 v1 就验证过大小一致的两个 squash 动作。
SQUASH_POSES = {"act_jump", "act_squat"}


def area_metric(clip) -> float:
    """不透明像素面积的平方根（取多帧中位数，躲开单帧的姿势噪声）。"""
    if not clip.files:
        return 0.0
    step = max(1, len(clip.files) // SAMPLES)
    vals = []
    for path in clip.files[::step][:SAMPLES]:
        img = clip.open_frame(path)
        alpha = np.asarray(img.getchannel("A"))
        vals.append(float((alpha > 40).sum()))
    return float(np.sqrt(np.median(vals))) if vals else 0.0


def compute(lib: dict, keep_manual: dict | None = None) -> dict:
    if REFERENCE not in lib:
        return {}
    ref = area_metric(lib[REFERENCE])
    if ref <= 0:
        return {}
    out = {}
    for name, clip in sorted(lib.items()):
        if name == REFERENCE:
            continue
        if name in SQUASH_POSES:
            out[name] = 1.0
            continue
        metric = area_metric(clip)
        fix = round(ref / metric, 3) if metric > 0 else 1.0
        # 差距小于 4% 的一律归 1.0 —— 肉眼看不出来，别引入无谓的变化
        if abs(fix - 1.0) < 0.04:
            fix = 1.0
        out[name] = fix
    if keep_manual:
        # 手工标过的以手工为准（人眼比代理准，尤其"手臂张开"那种姿势）
        for name, value in keep_manual.items():
            if name in out or name in lib:
                out[name] = float(value)
    return out


def render(lib: dict, fixes: dict, path: str, target: int = 280) -> str:
    """把各片段归一化后并排画出来（就是桌宠实际看到的相对大小）。

    每格按"内容底边贴同一条红线"摆，和桌宠的 floor 锚点一致 ——
    这样一眼就能看出谁比谁大。
    """
    names = [REFERENCE] + [n for n in sorted(lib) if n != REFERENCE]
    names = [n for n in names if n in lib]
    cols = 5
    tile_w, tile_h = 250, 400
    floor_in_tile = tile_h - 46
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w + 10, rows * tile_h + 10), (236, 237, 242))
    draw = ImageDraw.Draw(sheet)
    for k, name in enumerate(names):
        clip = lib[name]
        fix = 1.0 if name == REFERENCE else float(fixes.get(name, 1.0))
        box = clip.content_box()
        scale = target / max(1, box[3] - box[1]) * fix
        img = clip.open_frame(clip.files[len(clip.files) // 2])
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.LANCZOS)
        cell_x = (k % cols) * tile_w + 10
        cell_y = (k // cols) * tile_h + 10
        floor = cell_y + floor_in_tile
        draw.text((cell_x + 4, cell_y + 4), f"{name}  x{fix:g}", fill=(40, 44, 60))
        draw.line([(cell_x, floor), (cell_x + tile_w - 20, floor)], fill=(205, 120, 120))
        # 先把角色画到一整格的透明底上，再整块贴过去 —— 免得贴到格子外面被裁掉
        cell = Image.new("RGB", (tile_w - 10, tile_h - 10), (236, 237, 242))
        px = (tile_w - 10 - img.width) // 2
        py = floor_in_tile - int(box[3] * scale)
        cell.paste(img, (max(0, px), max(0, py)), img)
        sheet.paste(cell, (cell_x, cell_y))
    sheet.save(path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="算每个片段的大小修正系数")
    ap.add_argument("--render", action="store_true", help="画一张归一化对比图")
    ap.add_argument("--show", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    lib = clips_mod.load_library()
    if not lib:
        print("没有素材")
        return 2

    manual = {}
    if os.path.isfile(FIX_PATH):
        try:
            with open(FIX_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
            manual = {k: v for k, v in raw.items() if isinstance(v, (int, float))}
        except Exception as exc:
            print(f"size_fix.json 读取失败（当作没有）：{exc}")

    fixes = compute(lib, manual)
    print(f"基准片段 {REFERENCE}（系数 1.0），共 {len(fixes)} 个片段\n")
    print(f"{'片段':<14}{'修正系数':>10}   说明")
    for name, value in sorted(fixes.items(), key=lambda kv: -abs(kv[1] - 1.0)):
        note = "（手工）" if name in manual else ""
        if value > 1.04:
            note += " 模型把她画小了，放大"
        elif value < 0.96:
            note += " 模型把她画大了，缩小"
        print(f"{name:<14}{value:>10.3f}   {note}")

    if not args.show:
        with open(FIX_PATH, "w", encoding="utf-8") as fh:
            json.dump(fixes, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"\n已写入 {os.path.relpath(FIX_PATH, ROOT)}"
              f"（想手工微调就改这个文件，改完重启桌宠）")

    if args.render:
        out = os.path.join(ROOT, "assets", "source", "shots", "v2_sizecheck.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        render(lib, fixes, out)
        print(f"对比图 -> {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
