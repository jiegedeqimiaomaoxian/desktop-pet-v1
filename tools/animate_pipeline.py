# -*- coding: utf-8 -*-
"""把「视频模型生成的一段视频」变成桌宠能直接播放的动作素材。

整条链路：
    首帧合成（青幕）→ 视频生成 → 拆帧 → 抠掉背景变透明
    → 统一裁切（保留缩放，去掉平移抖动）→ 去绿边 → 打包 APNG + 清单

关键约定：视频模型不认识"透明"，所以首帧把角色摆在纯色幕布上，
生成完再按颜色把幕布抠掉。幕布颜色会先核对过角色身上不会出现（色键安全）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
ACTIONS_DIR = os.path.join(ASSETS, "actions")

#: 幕布颜色候选（和角色配色都不撞，按顺序试）
SCREEN_CANDIDATES = [(0, 200, 90), (0, 255, 0), (255, 0, 255), (0, 160, 255)]


# --------------------------------------------------------------------------- 首帧

def load_sprite(path: str | None = None) -> Image.Image:
    path = path or os.path.join(ASSETS, "pet_body.png")
    return Image.open(path).convert("RGBA")


def pick_screen(sprite: Image.Image, min_gap: float = 60.0) -> tuple[int, int, int]:
    """挑一个和角色身上任何像素都差得够远的幕布颜色。"""
    small = sprite.resize((max(1, sprite.width // 4), max(1, sprite.height // 4)))
    arr = np.asarray(small.convert("RGB"), dtype=np.int16)
    alpha = np.asarray(small.getchannel("A"))
    opaque = arr[alpha > 8]
    if len(opaque) == 0:
        return SCREEN_CANDIDATES[0]
    for candidate in SCREEN_CANDIDATES:
        diff = np.abs(opaque - np.array(candidate, dtype=np.int16)).sum(axis=1)
        if diff.min() > min_gap:
            return candidate
    # 都不够远就选"最远"的那个
    best, best_gap = SCREEN_CANDIDATES[0], -1.0
    for candidate in SCREEN_CANDIDATES:
        diff = np.abs(opaque - np.array(candidate, dtype=np.int16)).sum(axis=1)
        gap = float(diff.min())
        if gap > best_gap:
            best, best_gap = candidate, gap
    return best


def build_input_frame(sprite: Image.Image, size: tuple[int, int] = (720, 1280),
                      height_ratio: float = 0.62, baseline: float = 0.88,
                      screen: tuple[int, int, int] | None = None) -> Image.Image:
    """把角色放到纯色幕布中间偏下，作为视频模型的首帧。

    height_ratio: 角色高度占画面的比例（别太满，给动作留空间）
    baseline:     脚底大约落在画面高度的百分之几
    """
    w, h = size
    screen = screen or pick_screen(sprite)
    target_h = max(8, int(h * height_ratio))
    scale = target_h / sprite.height
    scaled = sprite.resize((max(1, int(sprite.width * scale)), target_h), Image.LANCZOS)
    canvas = Image.new("RGBA", size, screen + (255,))
    x = (w - scaled.width) // 2
    y = int(h * baseline) - scaled.height
    canvas.alpha_composite(scaled, (max(0, x), max(0, y)))
    return canvas.convert("RGB")


# --------------------------------------------------------------------------- 抠像

def detect_background(frames: list[np.ndarray], border: int = 6) -> np.ndarray:
    """从每帧的四条边框取中位数颜色，作为背景色估计。"""
    samples = []
    for arr in frames:
        h, w = arr.shape[:2]
        b = max(1, min(border, h // 8, w // 8))
        samples.append(arr[:b].reshape(-1, 3))
        samples.append(arr[-b:].reshape(-1, 3))
        samples.append(arr[:, :b].reshape(-1, 3))
        samples.append(arr[:, -b:].reshape(-1, 3))
    stack = np.concatenate(samples, axis=0)
    return np.median(stack, axis=0)


def alpha_from_background(arr: np.ndarray, bg: np.ndarray, tol: float = 34.0,
                          soft: float = 46.0, spill: bool = True) -> np.ndarray:
    """按与背景色的距离算 alpha，并做绿色溢出抑制。"""
    diff = np.abs(arr.astype(np.int16) - bg.astype(np.int16)).mean(axis=2)
    alpha = np.clip((diff - tol) / max(1.0, soft) * 255.0, 0, 255).astype(np.uint8)
    out = arr.copy()
    if spill:
        # 背景是绿的：把明显偏绿的像素往红蓝的最大值压，去掉边缘绿边
        r, g, b = out[:, :, 0].astype(np.int16), out[:, :, 1].astype(np.int16), out[:, :, 2].astype(np.int16)
        limit = np.maximum(r, b)
        green_dominant = (g > limit) & (alpha < 250)
        g = np.where(green_dominant, limit, g)
        out[:, :, 1] = np.clip(g, 0, 255).astype(np.uint8)
    return alpha, out


def frames_to_rgba(paths: list[str], tol: float = 34.0, soft: float = 46.0,
                   use_detected_bg: bool = True,
                   mask_top: float = 0.0) -> list[Image.Image]:
    """读帧 → 抠背景 → 返回带透明通道的帧。

    mask_top: 把画面上方这个比例直接抹成透明（默认 0）。
    视频模型有时会把台词烧成字幕贴在顶部，抹掉它就不会被算进构图。
    """
    raws = [np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8) for p in paths]
    bg = detect_background(raws) if use_detected_bg else np.array([0, 200, 90])
    out = []
    for arr in raws:
        alpha, rgb = alpha_from_background(arr, bg, tol=tol, soft=soft)
        if mask_top > 0:
            cut = int(alpha.shape[0] * mask_top)
            if cut > 0:
                alpha[:cut, :] = 0
        rgba = np.dstack([rgb, alpha])
        out.append(Image.fromarray(rgba, mode="RGBA"))
    return out


def rgb_to_hsv_arrays(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """向量化 RGB->HSV（H 单位为度 0~360，S/V 为 0~1）。"""
    rgb = arr.astype(np.float32) / 255.0
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mx = np.max(rgb, axis=2)
    mn = np.min(rgb, axis=2)
    diff = mx - mn
    hue = np.zeros_like(mx)
    safe = diff > 1e-6
    # 分别算三个扇区，最后按"哪个通道是最大值"取用
    with np.errstate(invalid="ignore", divide="ignore"):
        hr = ((g - b) / np.where(safe, diff, 1.0)) % 6.0
        hg = ((b - r) / np.where(safe, diff, 1.0)) + 2.0
        hb = ((r - g) / np.where(safe, diff, 1.0)) + 4.0
    is_r = safe & (mx == r)
    is_g = safe & (mx == g) & ~is_r
    is_b = safe & (mx == b) & ~is_r & ~is_g
    hue = np.where(is_r, hr, np.where(is_g, hg, np.where(is_b, hb, 0.0))) * 60.0
    sat = np.where(mx > 1e-6, diff / np.where(mx > 1e-6, mx, 1.0), 0.0)
    return hue, sat, mx


def _hue_distance(hue: np.ndarray, target: float) -> np.ndarray:
    """色相环上的最短角距离（度）。"""
    delta = np.abs(hue - target) % 360.0
    return np.minimum(delta, 360.0 - delta)


def alpha_from_hue_screen(arr: np.ndarray, target_hue: float | None = None,
                          inner: float = 12.0, outer: float = 30.0,
                          min_sat: float = 0.10, contamination: float = 10.0
                          ) -> tuple[np.ndarray, np.ndarray]:
    """按**色相**抠幕布，并单独清掉角色身上的幕布「环境光污染」。

    为什么不能只按颜色距离或"绿偏"（实测数据，2026-09-18）：
      3D 手办风的模型把"绿幕"渲染成了**带明暗渐变的橄榄绿**——
      边框采样 RGB 从 (97,116,39) 到 (193,195,124)，绿偏 g-max(r,b) 只有 0~26。
      于是：
        · 按"和边框色的距离"抠 → 暗部抠不掉，脚下留绿渣；
        · 按"绿色超出红蓝"抠 → 阈值设 12 时背景透明率是 **0.0%**，整块幕布抠不动。
      但色相是稳的：幕布 74~80°，角色深蓝 214°、白色中性、金色 50° —— 分得干干净净。

    还需要第二层：模型的绿幕会把**环境绿光**打在白裤袜、白围裙这些中性色上
    （实测白裤袜变成带绿味的灰，g 比 r/b 高十几个），色相判据会把它们当角色留下，
    于是在深色桌面上显出一层脏绿。所以中性低饱和像素要再按"是否比红蓝偏绿"清一遍。

    target_hue: 幕布色相；None 表示自动从四条边框的中位色相取。
    inner/outer: 与幕布色相距离小于 inner 判为背景，大于 outer 判为角色，中间线性过渡。
    min_sat: 饱和度低于它的像素视为中性色（角色本体），交给 contamination 规则处理。
    contamination: 中性像素的 g-max(r,b) 超过它就算被幕布光污染 → 一并判为背景。
    """
    hue, sat, _ = rgb_to_hsv_arrays(arr)
    if target_hue is None:
        h, w = hue.shape
        b = max(1, min(6, h // 8, w // 8))
        border = np.concatenate([hue[:b].ravel(), hue[-b:].ravel(),
                                 hue[:, :b].ravel(), hue[:, -b:].ravel()])
        sat_border = np.concatenate([sat[:b].ravel(), sat[-b:].ravel(),
                                     sat[:, :b].ravel(), sat[:, -b:].ravel()])
        colored = border[sat_border > 0.08]
        target_hue = float(np.median(colored)) if len(colored) else 90.0
    dist = _hue_distance(hue, float(target_hue))
    keyed = np.clip((dist - inner) / max(1.0, outer - inner) * 255.0, 0, 255)

    # 中性像素（白围裙、白裤袜、眼睛高光）：本身不该被色相判据吃掉，
    # 但如果它明显比红蓝偏绿，就是幕布环境光污染，要一起清掉。
    rgb = arr.astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    green_bias = g - np.maximum(r, b)
    neutral = sat < min_sat
    dirty = green_bias > contamination
    alpha = np.where(neutral & ~dirty, 255.0,
                     np.where(neutral & dirty, 0.0, keyed)).astype(np.uint8)

    # 幕布色溢出抑制：还带幕布色相的边缘像素，把它的通道往中性拉
    out = arr.copy()
    keep = (dist < outer) & (alpha < 252)
    if keep.any():
        grey = out[keep].mean(axis=1, keepdims=True)
        out[keep] = (0.35 * out[keep].astype(np.float32)
                     + 0.65 * grey).astype(np.uint8)
    return alpha, out


def frames_to_rgba_hue(paths: list[str], target_hue: float | None = None,
                       inner: float = 12.0, outer: float = 30.0,
                       min_sat: float = 0.10, contamination: float = 10.0
                       ) -> list[Image.Image]:
    """读帧 → 色相抠像 → 透明帧（3D 手办风的橄榄绿渐变幕布用这条）。"""
    out = []
    for path in paths:
        arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
        alpha, rgb = alpha_from_hue_screen(arr, target_hue=target_hue, inner=inner,
                                           outer=outer, min_sat=min_sat,
                                           contamination=contamination)
        out.append(Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA"))
    return out


def _mask(frame: Image.Image, threshold: int = 24, skip_top: float = 0.0) -> Image.Image:
    """取不透明遮罩；skip_top 用来挖掉画面上方（视频模型常把台词烧成字幕）。"""
    mask = frame.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    if skip_top > 0:
        cut = int(frame.height * skip_top)
        if cut > 0:
            blank = Image.new("L", (frame.width, cut), 0)
            mask = mask.copy()
            mask.paste(blank, (0, 0))
    return mask


def detect_captions_temporal(frames: list[Image.Image], white: int = 200,
                             std_max: float = 12.0, min_ratio: float = 0.25
                             ) -> list[np.ndarray]:
    """用"时间方差"找出烧进画面的字幕，返回每帧的布尔遮罩。

    思路：字幕是**逐帧完全静止**的（同一个位置、同一个像素），而角色一直在动。
    所以对整段视频逐像素求标准差，标准差接近 0 的亮像素就是字幕。

    比只看"亮不亮""宽不宽"稳得多 —— 角色的白色荷叶边虽然也亮，
    但它每一帧都在动，时间方差不为 0。
    """
    if len(frames) < 4:
        return [np.zeros((f.height, f.width), dtype=bool) for f in frames]
    stack = np.stack([np.asarray(f.convert("RGB"), dtype=np.float32) for f in frames])
    std = stack.std(axis=0).mean(axis=2)                    # 每像素的时间标准差
    mean = stack.mean(axis=0)
    bright = ((mean[:, :, 0] > white) & (mean[:, :, 1] > white) & (mean[:, :, 2] > white))
    static = (std < std_max) & bright
    # 只保留"成行"的静止区域：一行里静止亮像素要够多，才像一行字
    width = frames[0].width
    rows_ok = static.sum(axis=1) >= max(8, int(width * 0.03))
    keep = np.zeros_like(static)
    for y, ok in enumerate(rows_ok):
        if ok:
            keep[y] = static[y]
    if keep.sum() < 40:
        return [np.zeros((f.height, f.width), dtype=bool) for f in frames]
    # 少数帧才出现的字幕：按帧统计，占比过半就认为整段都有
    ratio = (keep.any(axis=1)).sum()  # noqa: F841  (仅用于调试可读性)
    masks = []
    for frame in frames:
        arr = np.asarray(frame.convert("RGB"), dtype=np.float32)
        diff = np.abs(arr - mean).mean(axis=2)
        # 该帧在这一带确实出现了这些字（和均值接近）
        masks.append(keep & (diff < 90))
    return masks


def remove_captions(frames: list[Image.Image], white: int = 200,
                    std_max: float = 12.0) -> tuple[list[Image.Image], int]:
    """把烧进画面的字幕抹成透明，返回 (处理后的帧, 被抹掉的帧数)。"""
    masks = detect_captions_temporal(frames, white=white, std_max=std_max)
    out = []
    hit = 0
    for frame, mask in zip(frames, masks):
        if mask.any():
            arr = np.asarray(frame.convert("RGB"), dtype=np.uint8)
            alpha = np.asarray(frame.getchannel("A")).copy()
            alpha[mask] = 0
            out.append(Image.fromarray(np.dstack([arr, alpha]), mode="RGBA"))
            hit += 1
        else:
            out.append(frame)
    return out, hit


def union_bbox(frames: list[Image.Image], threshold: int = 24,
               skip_top: float = 0.0) -> tuple[int, int, int, int]:
    """所有帧不透明区域的并集包围盒（可忽略顶部一条，避开字幕）。"""
    box = None
    for frame in frames:
        b = _mask(frame, threshold, skip_top).getbbox()
        if not b:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    return box or (0, 0, frames[0].width, frames[0].height)


def anchor_of(frames: list[Image.Image], threshold: int = 24,
              skip_top: float = 0.0) -> tuple[float, float]:
    """取"锚点"：所有帧底部中心的中位数，用来消除整段视频的平移抖动。

    只对齐平移，不缩放 —— 这样蹦跳/摇摆这些动作本身会被保留下来。
    """
    xs, ys = [], []
    for frame in frames:
        b = _mask(frame, threshold, skip_top).getbbox()
        if b:
            xs.append((b[0] + b[2]) / 2)
            ys.append(b[3])
    if not xs:
        return frames[0].width / 2, frames[0].height / 2
    return float(np.median(xs)), float(np.median(ys))


def stabilize_and_crop(frames: list[Image.Image], target_height: int = 430,
                       pad: int = 6, skip_top: float = 0.0,
                       stabilize: bool = True) -> list[Image.Image]:
    """把每帧按各自底部中心对齐到同一个锚点，再统一裁切到接近正方的大小。

    skip_top: 量包围盒时忽略画面上方这个比例（默认 0），用于躲开字幕。

    stabilize=False：**不做逐帧重摆位**，直接用整段的并集包围盒裁一次。
    为什么要留这个开关：逐帧对齐的基准是"每帧自己的包围盒底边"，
    而包围盒会随动作变（蹦跳时脚离地、挥手时手臂外扩），于是
        * 蹦跳的竖直位移被当成"镜头漂移"抵消掉，动作幅度变小；
        * 包围盒本身的量化噪声（±1px）会变成逐帧抖动，看起来更"卡"。
    不重摆位时，只要源视频镜头是固定的（提示词里已锁死镜头），
    角色位置天然一致，裁一次就够，动作幅度和帧间连续性都最好。
    返回值里每帧尺寸一致，直接可以当桌宠动画帧。
    """
    w, h = frames[0].size

    def safe_box(frame: Image.Image) -> tuple[int, int, int, int]:
        """bbox，但压在画布范围内，避免裁切越界。"""
        return _mask(frame, skip_top=skip_top).getbbox() or (0, 0, w, h)

    if stabilize:
        ax, ay = anchor_of(frames, skip_top=skip_top)
        # 用"每帧相对锚点的偏移"重新摆位，削弱镜头漂移
        placed: list[Image.Image] = []
        for frame in frames:
            b = safe_box(frame)
            cx = (b[0] + b[2]) / 2
            by = b[3]
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            canvas.alpha_composite(frame, (int(round(ax - cx)), int(round(ay - by))))
            placed.append(canvas)
        # 平移量不大的话（<6px）就不动，免得把真动作也抹掉
        drift = max(abs(ax - (b[0] + b[2]) / 2) + abs(ay - b[3])
                    for b in (safe_box(f) for f in frames))
        if drift > 6:
            frames = placed

    box = union_bbox(frames, skip_top=skip_top)
    x0, y0, x1, y1 = box
    # 四周留点余量，别让角色贴着画布边缘
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    # 裁成正方形，锚点（底部中心）在裁切后位置保持一致
    side = max(x1 - x0, y1 - y0)
    cx = (x0 + x1) / 2
    bx0 = int(round(cx - side / 2))
    bx1 = bx0 + side
    by1 = int(round(y1))
    by0 = by1 - side
    # 贴边时整体回推，保证裁切窗口完全落在画布内（不足部分允许越界到透明区）
    if bx0 < 0:
        bx1 -= bx0
        bx0 = 0
    if bx1 > w:
        bx0 -= (bx1 - w)
        bx1 = w
    if by0 < 0:
        by1 -= by0
        by0 = 0
    if by1 > h:
        by0 -= (by1 - h)
        by1 = h
    cropped = []
    for frame in frames:
        tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        tile.alpha_composite(frame, (-bx0, -by0))
        cropped.append(tile)
    if target_height and cropped:
        ratio = target_height / cropped[0].height
        size = (max(8, int(cropped[0].width * ratio)), target_height)
        cropped = [f.resize(size, Image.LANCZOS) for f in cropped]
    return cropped


def despill(frames: list[Image.Image], strength: float = 0.85,
            tolerance: int = 0) -> list[Image.Image]:
    """去掉绿幕反射到角色身上的**环境绿光**（不是抠像残留，是渲染里就有的）。

    实测数据：3D 手办风的 MiniMax-H3 会把绿幕当环境光反射，
    白裤袜在源视频里就是 RGB(109,127,94)、g-max(r,b)=+18 —— 明显发绿。
    抠像管不了它：这些像素本来就该属于角色，抠掉会啃出缺口。只能压掉绿色偏移。

    做法和业界抠绿幕的 de-spill 一致：把 G 通道相对 R/B 均值的超出部分乘个系数，
    并保证 G 不低于 R/B 均值（否则会变成品红）：
        avg = (r + b) / 2
        if g > avg:  g = avg + (g - avg) * (1 - strength)

    strength=0 不处理；0.85 约把 +18 的绿偏压到 +2.7；1.0 完全中和。
    """
    factor = max(0.0, min(1.0, 1.0 - strength))
    out = []
    for frame in frames:
        has_alpha = "A" in frame.getbands()
        arr = np.asarray(frame.convert("RGB"), dtype=np.float32)
        alpha = np.asarray(frame.getchannel("A")) if has_alpha else None
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        avg = (r + b) / 2.0
        over = g > avg
        if over.any():
            g = np.where(over, avg + (g - avg) * factor, g)
            arr = np.dstack([r, g, b])
        rgb = np.clip(arr, 0, 255).astype(np.uint8)
        if has_alpha:
            out.append(Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA"))
        else:
            out.append(Image.fromarray(rgb, mode="RGB"))
    return out


def harden(frames: list[Image.Image], threshold: int = 64) -> list[Image.Image]:
    """alpha 阈值化：和桌宠本体的处理保持一致，避免色边。"""
    out = []
    for frame in frames:
        alpha = frame.getchannel("A").point(lambda v: 255 if v > threshold else 0)
        rgb = frame.convert("RGB")
        rgb.putalpha(alpha)
        out.append(rgb)
    return out


def trim_loop(frames: list[Image.Image], threshold: float = 1.2) -> list[Image.Image]:
    """如果首尾几乎一样，去掉尾巴上重复的帧，循环更顺。

    只删"和第一帧几乎相同"的连续尾帧，最多删掉一半。
    """
    if len(frames) < 6:
        return frames
    first = np.asarray(frames[0].convert("RGBA"), dtype=np.int16)
    cut = len(frames)
    limit = len(frames) // 2
    while cut > 2 and len(frames) - cut < limit:
        last = np.asarray(frames[cut - 1].convert("RGBA"), dtype=np.int16)
        if np.abs(last - first).mean() <= threshold:
            cut -= 1
        else:
            break
    return frames[:cut] if 2 <= cut < len(frames) else frames


# --------------------------------------------------------------------------- 打包

def quantize_frames(frames: list[Image.Image], colors: int = 256) -> list[Image.Image]:
    """把帧转成调色板 PNG（保留透明），文件能小一大截。

    注意：P 模式在 Pillow 里再做 resize 时，透明索引会被当成普通颜色参与
    重采样，导致透明区域渗出黑色实心像素。所以只有在"存完不再缩放"的
    场景才好用；桌宠需要在运行时按屏幕缩放，默认不开（--quantize 可强制）。
    """
    out = []
    for frame in frames:
        alpha = frame.getchannel("A").point(lambda v: 255 if v > 128 else 0).convert("1")
        pal = frame.convert("RGB").quantize(colors=colors - 1, method=Image.MEDIANCUT)
        pal.paste(255, alpha)
        palette = list(pal.getpalette() or [])
        if len(palette) < 256 * 3:
            palette = palette + [0] * (256 * 3 - len(palette))
        palette[255 * 3:255 * 3 + 3] = [0, 0, 0]
        pal.putpalette(palette)
        pal.info["transparency"] = 255
        out.append(pal)
    return out


def save_action(name: str, frames: list[Image.Image], fps: float = 12.0,
                loop: bool = True, action_dir: str | None = None,
                extra: dict | None = None, quantize: bool = False) -> str:
    """存成一个动作：帧 PNG + 动作清单 action.json，返回目录。"""
    action_dir = action_dir or os.path.join(ACTIONS_DIR, name)
    frames_dir = os.path.join(action_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for old in os.listdir(frames_dir):
        if old.endswith(".png"):
            os.remove(os.path.join(frames_dir, old))
    size = frames[0].size
    stored = quantize_frames(frames) if quantize else frames
    for i, frame in enumerate(stored):
        frame.save(os.path.join(frames_dir, f"{i:03d}.png"), optimize=True)
    manifest = {
        "name": name,
        "frames": len(frames),
        "fps": fps,
        "loop": loop,
        "size": [size[0], size[1]],
        "quantized": bool(quantize),
        "frames_dir": os.path.relpath(frames_dir, ROOT).replace("\\", "/"),
    }
    manifest.update(extra or {})
    with open(os.path.join(action_dir, "action.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return action_dir


def contact_sheet(frames: list[Image.Image], path: str, columns: int = 8,
                  background: tuple[int, int, int] = (32, 36, 48)) -> str:
    """把帧拼成一张图，方便肉眼检查抠像质量。"""
    if not frames:
        raise ValueError("没有帧")
    cols = max(1, min(columns, len(frames)))
    rows = (len(frames) + cols - 1) // cols
    w, h = frames[0].size
    sheet = Image.new("RGB", (cols * w + (cols + 1) * 8, rows * h + (rows + 1) * 8), background)
    for i, frame in enumerate(frames):
        x = 8 + (i % cols) * (w + 8)
        y = 8 + (i // cols) * (h + 8)
        sheet.paste(frame, (x, y), frame)
    sheet.save(path)
    return path


def preview_gif(frames: list[Image.Image], path: str, fps: float = 12.0,
                background: tuple[int, int, int] = (238, 238, 242)) -> str:
    """合成一个 GIF 预览（贴到浅色底上，模拟桌面观感）。

    所有帧共用第一帧的调色板，否则 Pillow 会因为各帧调色板不同而报错。
    """
    tiles = []
    for frame in frames:
        tile = Image.new("RGB", frame.size, background)
        tile.paste(frame, (0, 0), frame)
        tiles.append(tile)
    palette = tiles[0].quantize(colors=255, method=Image.MEDIANCUT)
    converted = [t.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for t in tiles]
    converted[0].save(path, save_all=True, append_images=converted[1:],
                      duration=int(round(1000.0 / max(1.0, fps))), loop=0, disposal=1)
    return path
