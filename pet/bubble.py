# -*- coding: utf-8 -*-
"""气泡：折行、排版、圆角框 + 会眨眼的小头像。

头像为什么能动
--------------
头像是从 `idle` 片段里裁头部区域做的小动画 —— 也就是说**气泡里那张脸和
画面上的角色是同一套素材**，待机时眨眼，气泡里的头像也跟着眨。
人工做的桌宠基本都有这个细节；一张静止的头像一眼就能看出是凑的。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

#: 行首不允许出现的标点（避免孤零零跑到下一行开头）
NO_LINE_START = set("，。、；：？！）】》」』”’…％%.,;:?!)]}")

BUBBLE_BG = "#f7f8ff"
BUBBLE_LINE = "#3a4a8c"
BUBBLE_TEXT = "#1f2a52"

HEAD_RATIO = 0.55        # 从内容框顶部往下取多少当作"头部"
HEAD_PAD = 0.06          # 头部方框比这个再宽一点，别贴着头发


def wrap_text(text: str, font, max_px: int) -> list[str]:
    """按像素宽度折行。

    CJK 排版惯例：行尾标点可以溢出一点点，不要把它挤到下一行开头。
    """
    out: list[str] = []
    for raw in str(text).split("\n"):
        if not raw:
            out.append("")
            continue
        line = ""
        for ch in raw:
            if font.measure(line + ch) <= max_px or not line:
                line += ch
            elif ch in NO_LINE_START:
                out.append(line + ch)
                line = ""
            else:
                out.append(line)
                line = ch
        if line or not out:
            out.append(line)
    return out


def head_box(clip, frame: Image.Image) -> tuple[int, int, int, int]:
    """头部裁剪框（用于生成气泡头像）。"""
    x0, y0, x1, y1 = clip.content_box()
    content_h = max(1, y1 - y0)
    side = int(round(content_h * HEAD_RATIO * (1 + HEAD_PAD * 2)))
    cx = (x0 + x1) / 2
    bx0 = int(round(cx - side / 2))
    bx1 = bx0 + side
    by0 = max(0, y0 - int(round(content_h * HEAD_PAD)))
    by1 = by0 + side
    return (max(0, bx0), max(0, by0),
            min(frame.width, bx1), min(frame.height, by1))


def make_avatar(frames: list[Image.Image], box: tuple[int, int, int, int],
                size: int) -> list[Image.Image]:
    """把一串帧裁成头像并缩放到 size（返回 RGBA，带透明）。"""
    out = []
    for img in frames:
        tile = img.crop(box)
        scale = size / max(1, tile.height)
        tile = tile.resize((max(1, int(round(tile.width * scale))), size), Image.LANCZOS)
        out.append(tile)
    return out


def round_rect_points(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    """给 canvas.create_polygon(smooth=True) 用的圆角矩形顶点。"""
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
        x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


def soft_shadow(width: int, height: int | None = None, alpha: int = 80) -> Image.Image:
    """脚下投影：中心实、边缘渐隐的椭圆（RGBA）。"""
    w = max(20, int(width))
    h = max(8, int(height if height is not None else w * 0.26))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    steps = 16
    for i in range(steps, 0, -1):
        k = i / steps
        box = [w / 2 - w / 2 * k, h / 2 - h / 2 * k, w / 2 + w / 2 * k, h / 2 + h / 2 * k]
        draw.ellipse(box, fill=(24, 30, 66, int(alpha * (1 - k) ** 1.5)))
    return img
