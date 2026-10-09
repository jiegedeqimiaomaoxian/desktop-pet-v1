# -*- coding: utf-8 -*-
"""把某一套动作拼成总览图，检查抠像质量与角色一致性。

每行一个动作：抽 6 帧拼一排，贴在深色底上看边缘残留。

用法:
    python tools\\overview_actions.py            # 全部动作
    python tools\\overview_actions.py 2d_        # 只看 2d_ 前缀那套
    python tools\\overview_actions.py 3d_        # 只看 3d_ 那套
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ACTIONS = os.path.join(ROOT, "assets", "actions")
PREVIEW = os.path.join(ROOT, "assets", "source", "action_preview")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PICK = 6          # 每个动作抽几帧
BG = (26, 29, 38)


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(n for n in os.listdir(ACTIONS)
                   if (not prefix or n.startswith(prefix)) and
                   os.path.isfile(os.path.join(ACTIONS, n, "action.json")))
    if not names:
        print(f"没有找到动作（前缀 {prefix!r}）")
        return 1

    rows = []
    for name in names:
        frames_dir = os.path.join(ACTIONS, name, "frames")
        files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
        if not files:
            continue
        idx = [round(i * (len(files) - 1) / (PICK - 1)) for i in range(PICK)]
        imgs = []
        for i in idx:
            with Image.open(os.path.join(frames_dir, files[i])) as raw:
                imgs.append(raw.convert("RGBA").copy())
        manifest = json.load(open(os.path.join(ACTIONS, name, "action.json"),
                                 encoding="utf-8"))
        rows.append((name, manifest, imgs))
    if not rows:
        print("没有可用帧")
        return 1

    tile_w, tile_h = max(r[2][0].width for r in rows), max(r[2][0].height for r in rows)
    label_w, pad = 260, 10
    width = label_w + PICK * (tile_w + pad) + pad
    height = len(rows) * (tile_h + pad) + pad
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    for r, (name, manifest, imgs) in enumerate(rows):
        y = pad + r * (tile_h + pad)
        draw.text((pad + 4, y + tile_h // 2 - 16),
                  f"{name}\n{manifest.get('title', '')}\n"
                  f"{manifest.get('frames')}帧 {manifest.get('size')}",
                  fill=(230, 232, 240))
        for c, img in enumerate(imgs):
            x = label_w + pad + c * (tile_w + pad)
            sheet.paste(img, (x, y), img)

    tag = prefix.rstrip("_") or "all"
    out = os.path.join(PREVIEW, f"{tag}_overview.png")
    sheet.save(out)
    print(f"总览图 -> {os.path.relpath(out, ROOT)}  ({sheet.width}x{sheet.height})")

    print("\n各动作不透明像素占比（正常应在 20%~50% 之间）：")
    for name, manifest, imgs in rows:
        ratios = [float((np.asarray(im.getchannel("A")) > 128).mean()) for im in imgs]
        avg = sum(ratios) / len(ratios)
        flag = "" if 0.15 <= avg <= 0.55 else "  <-- 检查"
        print(f"  {name:10} {avg:6.1%}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
