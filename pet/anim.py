# -*- coding: utf-8 -*-
"""动画引擎：按**绝对时间轴**推帧 + 片段之间交叉淡入。

三条硬经验（都是踩出来的，别改回去）
------------------------------------
1. **帧号从时间轴反算**，不要"每画一帧就 after(1000/fps)"。
   后者每次回调的迟到都会累加，Tk 定时器本身又有粒度，结果帧间隔忽长忽短。
   反算之后迟到一次下一帧自己补回来，永远不漂。
2. **下一次唤醒对准"下一帧该出现的那一刻"**，不做固定间隔轮询。
3. **Windows 默认时钟中断是 15.6ms**，`after(42)` 实际 46.8ms 才醒。
   要 24fps 就得 `timeBeginPeriod(1)`（退出时还原）。
"""

from __future__ import annotations

import ctypes
import math
import os
import time

from PIL import Image

#: 唤醒的最小间隔（ms）—— 别用 0，Tk 会退化成忙等
MIN_DELAY_MS = 1

#: 循环片段想"一直播下去"就传这个
FOREVER = 0


# --------------------------------------------------------------------------- 定时精度

_RAISED = False


def raise_timer_resolution() -> bool:
    """把 Windows 定时器精度提到 1ms（幂等）。"""
    global _RAISED
    if _RAISED or os.name != "nt":
        return False
    try:
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
        _RAISED = True
        return True
    except Exception:
        return False


def lower_timer_resolution() -> None:
    """还原定时器精度（退出时调）。"""
    global _RAISED
    if not _RAISED:
        return
    try:
        ctypes.WinDLL("winmm").timeEndPeriod(1)
    except Exception:
        pass
    _RAISED = False


# --------------------------------------------------------------------------- 交叉淡入

def fade_over(base: Image.Image, top: Image.Image, t: float) -> Image.Image:
    """把 top 以 t（0~1）的不透明度叠在不透明的 base 之上。

    不用 `Image.blend`：blend 会线性混合两边的 alpha，两张半透明角色叠起来
    会变成"两个鬼影"（不重叠处各露一半、重叠处更实）。角色切换要的是
    "新图淡入到旧图上"，不是"两张图互相穿透"。
    """
    t = max(0.0, min(1.0, float(t)))
    out = base.copy()
    if t <= 0.0:
        return out
    layer = top.copy()
    layer.putalpha(layer.getchannel("A").point(lambda v: int(round(v * t))))
    out.alpha_composite(layer)
    return out


def fade_frames(base_img: Image.Image, base_pos: tuple[float, float],
                top_img: Image.Image, top_pos: tuple[float, float],
                steps: int) -> tuple[list[Image.Image], tuple[float, float]]:
    """生成 base → top 的过渡帧，返回 (帧列表, 联合画布原点)。

    两张图大小和落点都不一样，先算出并集画布，各自贴上去再混合。
    """
    x0 = min(base_pos[0], top_pos[0])
    y0 = min(base_pos[1], top_pos[1])
    x1 = max(base_pos[0] + base_img.width, top_pos[0] + top_img.width)
    y1 = max(base_pos[1] + base_img.height, top_pos[1] + top_img.height)
    w = max(1, int(math.ceil(x1 - x0)))
    h = max(1, int(math.ceil(y1 - y0)))

    def layer(img, pos):
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(img, (int(round(pos[0] - x0)), int(round(pos[1] - y0))))
        return canvas

    base = layer(base_img, base_pos)
    top = layer(top_img, top_pos)
    return [fade_over(base, top, (i + 1) / steps) for i in range(steps)], (x0, y0)


# --------------------------------------------------------------------------- 播放器

class Player:
    """一个片段的播放状态机（循环 / 一次性 / 过渡帧）。

    它只算"现在该显示哪张图、放在哪"，真正的绘制交给外部传进来的 `draw`。
    `root` 用来排下一次唤醒（Tk 的 after）。
    """

    def __init__(self, root, draw, photo_factory=None) -> None:
        self.root = root
        self.draw = draw                 # draw(photo, x, y)
        #: PIL 图 -> Tk 图。过渡帧**按需**转：一次转 5 张要 35ms，
        #: 全堆在点击那一刻就是肉眼可见的延迟；摊到 5 帧的播放时间里就没了。
        self.photo_factory = photo_factory or (lambda img: img)
        self.name: str | None = None
        self.frames: list = []
        self.origin = (0.0, 0.0)         # 片段帧的基准落点
        self.fps = 24.0
        self.loop = True
        self.infinite = True
        self.index = -1
        self.t0 = 0.0
        self.total = 0
        self.transition: list = []       # [(photo, (x, y))] 过渡帧
        self.on_done = None
        self.job = None
        self.started_at = 0.0

    # ---------------------------------------------------------------- 状态

    @property
    def active(self) -> bool:
        return self.name is not None or bool(self.transition)

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def current_image(self):
        """当前该显示的 PIL 图（做过渡起点用）；没有就返回 None。"""
        return getattr(self, "_last_pil", None)

    # ---------------------------------------------------------------- 播放

    def play(self, name: str, frames: list, origin: tuple[float, float], *,
             loop: bool, fps: float, loops: int = 1,
             transition: list | None = None, on_done=None,
             first_pil: Image.Image | None = None) -> None:
        """开始播一个片段。

        loops: 循环片段播几轮；`FOREVER`(0) = 一直播；一次性片段忽略它。
        transition: 已经生成好的过渡帧 [(photo, (x,y))]，先播它们再进正片。
        first_pil: 这个片段第一帧的 PIL 图（给"下一次切换"当过渡起点用）。
        """
        self.cancel()
        self.name = name
        self.frames = frames
        self.origin = origin
        self.fps = max(1.0, float(fps))
        self.loop = bool(loop)
        self.infinite = bool(loop) and int(loops) <= 0
        self.total = 0 if self.infinite else len(frames) * (max(1, int(loops)) if loop else 1)
        self.index = -1
        self.on_done = on_done
        self.transition = list(transition or [])
        self._last_pil = first_pil
        self.started_at = time.perf_counter()
        self.t0 = self.started_at
        raise_timer_resolution()
        self.tick()

    def cancel(self) -> None:
        """立刻停下（不发 on_done）。"""
        self._unschedule()
        self.name = None
        self.frames = []
        self.transition = []
        self.index = -1
        self.on_done = None

    def _unschedule(self) -> None:
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    # ---------------------------------------------------------------- 推帧

    def tick(self) -> None:
        self.job = None
        now = time.perf_counter()

        # ① 过渡帧先播完；播完那一刻才开始给正片计时
        if self.transition:
            item = self.transition.pop(0)
            if isinstance(item[0], Image.Image):        # 还没转成 Tk 图
                photo = self.photo_factory(item[0])
            else:
                photo = item[0]
            pos = item[1]
            self.draw(photo, pos[0], pos[1])
            self.job = self.root.after(max(MIN_DELAY_MS, int(round(1000.0 / self.fps))),
                                       self.tick)
            return

        if self.name is None:
            return
        index = int((now - self.t0) * self.fps)
        if not self.infinite and index >= self.total:
            self.finish()
            return
        if index != self.index:
            self.index = index
            self.draw(self.frames[index % len(self.frames)], self.origin[0], self.origin[1])

        # ② 下一次唤醒对准下一帧该出现的那一刻，误差不累积
        when = self.t0 + (index + 1) / self.fps
        delay = int(round((when - time.perf_counter()) * 1000.0))
        self.job = self.root.after(max(MIN_DELAY_MS, delay), self.tick)

    def finish(self) -> None:
        """一次性片段播完（或循环到轮数上限）。"""
        callback = self.on_done
        self.job = None
        self.name = None
        self.transition = []
        self.on_done = None
        if callback is not None:
            callback()
