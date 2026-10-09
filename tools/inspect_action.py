# -*- coding: utf-8 -*-
"""放大检查单个动作的抠像边缘：贴深色底 + 放大局部，看有没有幕布残留。

用法: python tools\inspect_action.py 3d_wave [帧号]
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NAME = sys.argv[1] if len(sys.argv) > 1 else "3d_wave"
IDX = int(sys.argv[2]) if len(sys.argv) > 2 else 14
FRAMES = os.path.join(ROOT, "assets", "actions", NAME, "frames")
OUT_DIR = os.path.join(ROOT, "assets", "source", "action_preview")

files = sorted(f for f in os.listdir(FRAMES) if f.endswith(".png"))
path = os.path.join(FRAMES, files[IDX])
frame = Image.open(path).convert("RGBA")
w, h = frame.size
print(f"{NAME} 第 {IDX} 帧 {w}x{h} -> {os.path.relpath(path, ROOT)}")

# 1) 整帧贴深色底
dark = Image.new("RGB", (w, h), (26, 29, 38))
dark.paste(frame, (0, 0), frame)

# 2) 下半身 2 倍放大（脚部最容易残留幕布）
crop = frame.crop((int(w * 0.15), int(h * 0.55), int(w * 0.85), h))
cw, ch = crop.size
big = Image.new("RGB", (cw * 2, ch * 2), (26, 29, 38))
big.paste(crop.resize((cw * 2, ch * 2), Image.NEAREST), (0, 0), 
          crop.resize((cw * 2, ch * 2), Image.NEAREST))

sheet = Image.new("RGB", (w + cw * 2 + 24, max(h, ch * 2)), (26, 29, 38))
sheet.paste(dark, (0, 0))
sheet.paste(big, (w + 24, 0))
out = os.path.join(OUT_DIR, f"inspect_{NAME}_{IDX}.png")
sheet.save(out)
print(f"检查图 -> {os.path.relpath(out, ROOT)}")

# 3) 量化残留：alpha>128 的像素里，有多少还带幕布色相（绿/黄绿）
alpha = np.asarray(frame.getchannel("A"))
rgb = np.asarray(frame.convert("RGB"), dtype=np.float32)
r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
mx = rgb.max(axis=2)
mn = rgb.min(axis=2)
diff = np.maximum(mx - mn, 1e-6)
hue = np.zeros_like(mx)
safe = (mx - mn) > 1e-6
with np.errstate(invalid="ignore", divide="ignore"):
    hr = ((g - b) / diff) % 6.0
    hg = ((b - r) / diff) + 2.0
    hb = ((r - g) / diff) + 4.0
is_r = safe & (mx == r)
is_g = safe & (mx == g) & ~is_r
is_b = safe & (mx == b) & ~is_r & ~is_g
hue = np.where(is_r, hr, np.where(is_g, hg, np.where(is_b, hb, 0.0))) * 60.0
sat = np.where(mx > 1e-6, (mx - mn) / np.where(mx > 1e-6, mx, 1.0), 0.0)

visible = alpha > 128
target = float(np.median(hue[(alpha < 8)]) ) if (alpha < 8).any() else 74.0
delta = np.abs(hue - target) % 360.0
delta = np.minimum(delta, 360.0 - delta)
residue = visible & (delta < 25) & (sat > 0.15)
print(f"\n可见像素 {visible.sum()} 个，其中仍带幕布色相(delta<25°, sat>0.15)的："
      f"{residue.sum()} 个 = {residue.mean():.2%}")
if residue.any():
    ys, xs = np.where(residue)
    print(f"  残留集中在 y={ys.min()}~{ys.max()}（画面高 {h}），"
          f"x={xs.min()}~{xs.max()}（画面宽 {w}）")
    print(f"  残留像素平均色 {rgb[residue].mean(axis=0).round(0).tolist()}")
