# -*- coding: utf-8 -*-
"""量一个动作"到底动了没有"：逐帧两两比较 RGBA 差异，比看包围盒可靠得多。

为什么要这个：手臂**举到脸旁边**挥舞时，整段的外接包围盒几乎不变
（手举高了但肘部还在下面，宽度高度都顶到同一个范围），
所以按 bbox 极差判断会把"真的在挥手"误判成"静态"。

这里改用**相邻帧平均绝对差**（mean abs diff，0~255）：
    · < 0.5  基本静止
    · 0.5~2  有轻微动作
    · > 2    动作明显

用法: python tools\measure_motion.py            # 全部动作
      python tools\measure_motion.py 2d_        # 只看某个前缀
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ACTIONS = os.path.join(ROOT, "assets", "actions")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def motion_score(frames_dir: str) -> tuple[float, float, int]:
    """返回 (相邻帧平均差, 首尾差, 帧数)。"""
    files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    if len(files) < 2:
        return 0.0, 0.0, len(files)
    arrs = [np.asarray(Image.open(os.path.join(frames_dir, f)).convert("RGBA"),
                       dtype=np.float32) for f in files]
    diffs = [float(np.abs(arrs[i + 1] - arrs[i]).mean()) for i in range(len(arrs) - 1)]
    loop_gap = float(np.abs(arrs[-1] - arrs[0]).mean())
    return float(np.mean(diffs)), loop_gap, len(files)


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(n for n in os.listdir(ACTIONS)
                   if (not prefix or n.startswith(prefix)) and
                   os.path.isdir(os.path.join(ACTIONS, n, "frames")))
    if not names:
        print("没有动作")
        return 1
    print(f"{'动作':<10}{'帧数':>5}{'相邻帧差':>10}{'首尾差':>9}  判定")
    weak = []
    for name in names:
        mean_diff, loop_gap, count = motion_score(os.path.join(ACTIONS, name, "frames"))
        if mean_diff < 0.5:
            verdict = "基本静止 <-- 需要重做"
            weak.append(name)
        elif mean_diff < 2.0:
            verdict = "轻微动作"
        else:
            verdict = "动作明显"
        print(f"{name:<10}{count:>5}{mean_diff:>10.2f}{loop_gap:>9.2f}  {verdict}")
    print()
    if weak:
        print(f"几乎不动的动作：{', '.join(weak)}")
        print("重做：python tools\\generate_mmx_comfy.py --style <套装> --actions "
              + ",".join(n.split('_', 1)[-1] for n in weak) + " --force --seed <换一个>")
    else:
        print("所有动作都有可见运动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
