# -*- coding: utf-8 -*-
"""诊断：屏幕/DPI 量出来是多少，透明色键为什么被拒，哪个候选色最合适。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk
import numpy as np

from pet import app as app_mod
from pet import clips as clips_mod


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    dpr = max(1.0, root.winfo_fpixels("1i") / 96.0)
    print(f"winfo_screen        = {root.winfo_screenwidth()} x {root.winfo_screenheight()}")
    area = app_mod.work_area(root)
    print(f"work_area           = {area}  -> {area[2]-area[0]} x {area[3]-area[1]}")
    print(f"fpixels('1i')       = {root.winfo_fpixels('1i'):.2f}   dpr = {dpr:.3f}")
    print(f"tk scaling          = {root.tk.call('tk', 'scaling')}")

    screen_h = area[3] - area[1]
    want = min(max(int(screen_h * 0.30), 190), 360)
    print(f"目标角色高度(逻辑)  = {want}   乘 dpr = {int(round(want * dpr))}")
    root.destroy()

    # --- 素材 ---
    lib = clips_mod.load_library()
    print(f"\n片段 {len(lib)} 个")
    for name in ("idle", "act_wave", "held"):
        clip = lib.get(name)
        if clip is None:
            continue
        with __import__("PIL.Image", fromlist=["Image"]).open(clip.files[0]) as raw:
            fw, fh = raw.size
        box = clip.content_box()
        print(f"  {name:10} 帧 {fw}x{fh}  内容框 {box}  内容高 {box[3]-box[1]}"
              f"  锚点 {clip.anchor}  循环 {clip.loop}  {len(clip.files)} 帧")

    # --- 色键候选：找"够暗"且离角色足够远的颜色 ---
    clip = lib["idle"]
    img = clip.open_frame(clip.files[len(clip.files) // 3]).convert("RGB")
    img.thumbnail((220, 220))
    arr = np.asarray(img).reshape(-1, 3).astype(np.int32)
    alpha = np.asarray(clip.open_frame(clip.files[len(clip.files) // 3])
                       .convert("RGBA").getchannel("A"))
    print(f"\n角色主色（出现最多的 6 种）：")
    packed = (arr[:, 0] << 16) | (arr[:, 1] << 8) | arr[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)[:6]
    for i in order:
        v = int(vals[i])
        print(f"    #{v:06x}  {counts[i]:>7} 像素")

    print("\n色键候选（到角色所有像素的最小曼哈顿距离，越大越安全）：")
    candidates = ["#0a1020", "#080c18", "#0b0f1e", "#05070d", "#ff00ff",
                  "#00ff00", "#000000", "#101828"]
    best = []
    for hexc in candidates:
        key = np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.int32)
        d = np.abs(arr - key).sum(axis=1)
        mind = int(d.min())
        ok = "✅" if mind >= 26 else ("⚠️" if mind >= 12 else "❌")
        # 亮度：暗的色键会让半透明的影子混出来还是暗的，观感好
        lum = int(0.299 * key[0] + 0.587 * key[1] + 0.114 * key[2])
        print(f"    {hexc}  最小距离 {mind:>3}  亮度 {lum:>3}  {ok}")
        if mind >= 26:
            best.append((lum, hexc, mind))
    if best:
        best.sort()
        print(f"\n  推荐（最暗且安全）：{best[0][1]}  最小距离 {best[0][2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
