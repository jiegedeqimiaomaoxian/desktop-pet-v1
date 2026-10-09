# -*- coding: utf-8 -*-
"""诊断绿幕抠像：看真实帧的绿偏分布，以及当前阈值切出多少透明。

用法: python tools\probe_greenkey.py [视频或帧目录]
"""
from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tempfix                                            # noqa: E402
import animate_pipeline as pipe                           # noqa: E402

FFMPEG = os.path.join(HERE, "bin", "ffmpeg.exe")
VIDEO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "assets", "source", "video_cache", "3d_bob.mp4")

work = os.path.join(ROOT, "assets", "source", "_tmp", "greenkey_probe")
os.makedirs(work, exist_ok=True)
for old in os.listdir(work):
    os.remove(os.path.join(work, old))
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", VIDEO,
                "-vf", "fps=12", "-frames:v", "4", os.path.join(work, "f%02d.png")],
               check=True)
frames = sorted(os.path.join(work, f) for f in os.listdir(work) if f.endswith(".png"))
print(f"视频: {os.path.relpath(VIDEO, ROOT)}  抽出 {len(frames)} 帧")

arr = np.asarray(Image.open(frames[0]).convert("RGB"), dtype=np.int16)
r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
dom = g - np.maximum(r, b)

h, w = dom.shape
border = np.concatenate([dom[:6].ravel(), dom[-6:].ravel(),
                         dom[:, :6].ravel(), dom[:, -6:].ravel()])
print(f"\n边框（背景）绿偏 dom = g - max(r,b):")
print(f"  min={border.min()}  中位={np.median(border):.0f}  max={border.max()}")
print(f"  RGB 采样（左上角）= {arr[3, 3].tolist()}")
print(f"  RGB 采样（右下角）= {arr[h - 4, w - 4].tolist()}")
print(f"  RGB 采样（正中偏下，角色身上）= {arr[int(h * 0.7), w // 2].tolist()}")

print("\n整帧 dom 分位数：")
for q in (1, 10, 25, 50, 75, 90, 99):
    print(f"  {q:>2}% -> {np.percentile(dom, q):.0f}")

print("\n色相抠像：不同 (inner, outer, min_sat) 下的透明/不透明比例")
raw0 = np.asarray(Image.open(frames[0]).convert("RGB"), dtype=np.uint8)
hue0, sat0, _ = pipe.rgb_to_hsv_arrays(raw0)
hb = np.concatenate([hue0[:6].ravel(), hue0[-6:].ravel(),
                     hue0[:, :6].ravel(), hue0[:, -6:].ravel()])
sb = np.concatenate([sat0[:6].ravel(), sat0[-6:].ravel(),
                     sat0[:, :6].ravel(), sat0[:, -6:].ravel()])
colored = hb[sb > 0.08]
print(f"  边框有彩色像素的色相中位数 = {np.median(colored):.0f}°"
      f"（{len(colored)} 个像素，占比 {len(colored) / len(hb):.0%}）")
print(f"  角色深蓝裙摆色相采样 = "
      f"{hue0[int(raw0.shape[0] * 0.55), int(raw0.shape[1] * 0.25)]:.0f}°")
for inner, outer, minsat in ((12, 30, 0.10), (14, 34, 0.12), (10, 26, 0.08),
                             (16, 40, 0.10), (12, 30, 0.06)):
    alpha, _ = pipe.alpha_from_hue_screen(raw0, inner=inner, outer=outer,
                                          min_sat=minsat)
    transparent = (alpha < 8).mean()
    opaque = (alpha > 247).mean()
    print(f"  inner={inner:>3} outer={outer:>3} min_sat={minsat:.2f} -> "
          f"透明 {transparent:6.1%} | 不透明 {opaque:6.1%} | "
          f"半透明 {1 - transparent - opaque:5.1%}")

alpha_best, _ = pipe.alpha_from_hue_screen(raw0, inner=12, outer=30, min_sat=0.10)
mask = alpha_best > 128
rows = np.where(mask.any(axis=1))[0]
cols = np.where(mask.any(axis=0))[0]
h, w = alpha_best.shape
if len(rows):
    print(f"\n角色包围盒：高 {rows[-1] - rows[0] + 1}px/{h}px = "
          f"{(rows[-1] - rows[0] + 1) / h:.1%}，宽 {cols[-1] - cols[0] + 1}px/{w}px = "
          f"{(cols[-1] - cols[0] + 1) / w:.1%}")
# 抠像结果贴到深色底上看边缘
composite = Image.new("RGB", (w * 2 + 12, h), (24, 26, 34))
rgba_frame = pipe.frames_to_rgba_hue([frames[0]], inner=12, outer=30,
                                     min_sat=0.10)[0]
composite.paste(rgba_frame, (0, 0), rgba_frame)
composite.paste(rgba_frame, (w + 12, 0), rgba_frame)
out_path = os.path.join(work, "keyed_preview.png")
composite.resize((composite.width // 2, composite.height // 2)).save(out_path)
print(f"抠像预览（深色底）-> {os.path.relpath(out_path, ROOT)}")
