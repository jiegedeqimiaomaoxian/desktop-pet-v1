# -*- coding: utf-8 -*-
"""流畅度体检：量「源视频」和「打包后的动作帧」到底顺不顺。

为什么需要它：
    桌宠原来按 12fps 抽帧播放，看起来卡。但"卡"有两个完全不同的来源，
    修法也完全不同，必须先量出来是哪一个：

    1. **源头就卡** —— 生成的视频本身帧间跳变大 / 有重复帧（模型没画出连续运动）。
       这种只能重新生成（换提示词/参数）。
    2. **播放才卡** —— 视频本身是 24fps 连续运动，但被抽成 12fps 播。
       这种只要别丢帧就行，不用重新出片。

指标说明（都在"角色像素"上算，避开背景）：
    step      相邻帧平均绝对差（0~255）。0 = 完全静止（重复帧）。
    dup%      相邻帧差 < 0.5 的占比 —— 重复帧比例，越高越"顿"。
    jerk      帧间差的二阶差分（加速度）波动。稳定运动时它很小；
              忽快忽慢时它会飙高，人眼就会觉得"一顿一顿"。
    cy        角色不透明区域的竖直重心，用来判断运动轨迹是否单调平滑。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tempfix  # noqa: E402,F401  (必须在任何 tempfile 使用前导入)


# --------------------------------------------------------------------------- 度量

def frame_stats(arrays: list[np.ndarray]) -> dict:
    """arrays 是若干帧的 RGB 数组（已按角色区域裁过）。返回流畅度指标。"""
    if len(arrays) < 3:
        return {}
    diffs = [float(np.abs(arrays[i].astype(np.int16)
                          - arrays[i - 1].astype(np.int16)).mean())
             for i in range(1, len(arrays))]
    d = np.array(diffs, dtype=float)
    # 二阶差分：相邻"速度"之间的变化。理想匀速运动 -> 接近 0
    jerk = np.abs(np.diff(d)) if len(d) > 1 else np.array([0.0])
    dup = float((d < 0.5).mean() * 100.0)
    return {
        "n": len(arrays),
        "step_mean": float(d.mean()),
        "step_min": float(d.min()),
        "step_max": float(d.max()),
        "step_std": float(d.std()),
        "dup_pct": dup,
        "jerk_mean": float(jerk.mean()),
        "jerk_max": float(jerk.max()) if len(jerk) else 0.0,
        "diffs": d,
    }


def content_mask_arrays(paths: list[str], box_pad: int = 8) -> tuple[list[np.ndarray], tuple]:
    """读帧 -> 取整段的内容并集包围盒 -> 裁出来（只比角色，不比背景）。"""
    imgs = []
    for p in paths:
        with Image.open(p) as raw:
            imgs.append(raw.convert("RGB"))
    union = None
    for im in imgs:
        a = np.asarray(im.convert("L"))
        # 背景通常是单色（绿幕/纯色）。用"和四角颜色差得多"当角色判据。
        corners = np.concatenate([a[:6, :6].ravel(), a[:6, -6:].ravel(),
                                  a[-6:, :6].ravel(), a[-6:, -6:].ravel()])
        bg = float(np.median(corners))
        rows = np.where((np.abs(a.astype(float) - bg) > 18).any(axis=1))[0]
        cols = np.where((np.abs(a.astype(float) - bg) > 18).any(axis=0))[0]
        if len(rows) == 0 or len(cols) == 0:
            continue
        cur = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
        if union is None:
            union = cur
        else:
            union = (min(union[0], cur[0]), min(union[1], cur[1]),
                     max(union[2], cur[2]), max(union[3], cur[3]))
    if union is None:
        union = (0, 0, imgs[0].width, imgs[0].height)
    x0 = max(0, union[0] - box_pad)
    y0 = max(0, union[1] - box_pad)
    x1 = min(imgs[0].width, union[2] + box_pad)
    y1 = min(imgs[0].height, union[3] + box_pad)
    out = [np.asarray(im.crop((x0, y0, x1, y1))).astype(np.uint8) for im in imgs]
    return out, (x0, y0, x1, y1)


def centroid_y(arrays: list[np.ndarray]) -> np.ndarray:
    """角色内容的竖直重心序列（归一化到 0~1），用来看运动轨迹。"""
    out = []
    for arr in arrays:
        g = arr.astype(np.float32).mean(axis=2)
        bg = float(np.median(np.concatenate([g[:4, :4].ravel(), g[:4, -4:].ravel(),
                                             g[-4:, :4].ravel(), g[-4:, -4:].ravel()])))
        m = np.abs(g - bg) > 18
        if not m.any():
            out.append(0.5)
            continue
        rows = np.where(m.any(axis=1))[0]
        w = m.sum(axis=1).astype(np.float64)
        out.append(float((rows * w[rows]).sum() / max(1e-9, w[rows].sum())) / g.shape[0])
    return np.array(out)


# --------------------------------------------------------------------------- 取帧

def extract_all(video: str, out_dir: str) -> list[str]:
    """按视频原生帧率把**所有**帧抽出来（不做任何丢帧）。"""
    import frames as framelib
    exe = framelib.require_ffmpeg()
    import glob
    import subprocess
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "f%04d.png")
    subprocess.run([exe, "-y", "-loglevel", "error", "-i", video, pattern],
                   check=True, capture_output=True)
    return sorted(glob.glob(os.path.join(out_dir, "f*.png")))


def action_frames(name: str) -> list[str]:
    d = os.path.join(ROOT, "assets", "actions", name, "frames")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".png"))


# --------------------------------------------------------------------------- 报告

def verdict(st: dict) -> str:
    if not st:
        return "帧太少，量不了"
    if st["step_mean"] < 0.5:
        return "❌ 几乎静止（模型没画出运动）"
    if st["dup_pct"] > 35:
        return f"❌ 重复帧太多（{st['dup_pct']:.0f}%）——源头就顿，需要重新生成"
    if st["dup_pct"] > 12:
        return f"⚠️ 有 {st['dup_pct']:.0f}% 重复帧，偏顿"
    if st["jerk_mean"] > st["step_mean"] * 0.9:
        return "⚠️ 忽快忽慢（jerk 偏高）"
    return "✅ 帧间连续，源头是流畅的"


def report(label: str, arrays: list[np.ndarray], verbose: bool) -> dict:
    st = frame_stats(arrays)
    if not st:
        print(f"  {label}: 帧数不足")
        return st
    print(f"  {label}")
    print(f"    帧数 {st['n']}｜步长 均{st['step_mean']:.2f} 最小{st['step_min']:.2f} "
          f"最大{st['step_max']:.2f} 标准差{st['step_std']:.2f}")
    print(f"    重复帧 {st['dup_pct']:.1f}%｜jerk 均{st['jerk_mean']:.2f} 最大{st['jerk_max']:.2f}")
    print(f"    判定：{verdict(st)}")
    if verbose:
        cy = centroid_y(arrays)
        print("    每帧步长: " + " ".join(f"{v:.1f}" for v in st["diffs"]))
        print("    竖直重心: " + " ".join(f"{v:.3f}" for v in cy))
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description="量动作素材的流畅度")
    ap.add_argument("--videos", default="", help="逗号分隔的视频名（video_cache 下的），"
                                                 "或 all")
    ap.add_argument("--actions", default="", help="逗号分隔的动作名（assets/actions 下的），"
                                                  "或 all / 某前缀如 2d_")
    ap.add_argument("--verbose", action="store_true", help="打印每帧步长")
    args = ap.parse_args()

    if args.videos:
        cache = os.path.join(ROOT, "assets", "source", "video_cache")
        names = ([f[:-4] for f in sorted(os.listdir(cache)) if f.endswith(".mp4")]
                 if args.videos == "all" else args.videos.split(","))
        print("=" * 72)
        print("源视频（原生帧率，一帧不丢）")
        print("=" * 72)
        for n in names:
            v = os.path.join(cache, n + ".mp4")
            if not os.path.isfile(v):
                print(f"  {n}: 没有这个视频")
                continue
            tmp = os.path.join(tempfile.gettempdir(), "smooth_" + n)
            paths = extract_all(v, tmp)
            arrays, box = content_mask_arrays(paths)
            report(f"{n}  ({len(paths)} 帧)", arrays, args.verbose)

    if args.actions:
        lib = ("all",) if args.actions == "all" else tuple(args.actions.split(","))
        if lib == ("all",):
            adir = os.path.join(ROOT, "assets", "actions")
            names = [d for d in sorted(os.listdir(adir))
                     if os.path.isdir(os.path.join(adir, d))]
        elif len(lib) == 1 and lib[0].endswith("_"):
            adir = os.path.join(ROOT, "assets", "actions")
            names = [d for d in sorted(os.listdir(adir)) if d.startswith(lib[0])]
        else:
            names = list(lib)
        print("=" * 72)
        print("打包后的动作帧（桌宠实际播的）")
        print("=" * 72)
        for n in names:
            paths = action_frames(n)
            if not paths:
                print(f"  {n}: 没有帧")
                continue
            arrays, _ = content_mask_arrays(paths)
            report(f"{n}  ({len(paths)} 帧)", arrays, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
