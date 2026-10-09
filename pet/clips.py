# -*- coding: utf-8 -*-
"""素材库：加载 / 缩放 / 对齐 / 后台预热。

和 v1 最大的不同
----------------
v1 的对齐基准是 `pet_body.png`（从三视图裁出来的静态精灵），而动作帧是模型
重新演绎的 —— **两者不是同一个角色**（发型长度、月牙发饰大小、体型都不一样）。
这一版待机本身也是模型出的（`idle` 片段），所以基准就是 `idle`：
整套素材同源，切换时不会有"换了一个人"的感觉。

对齐方式（两种锚点）
--------------------
* `floor`  —— 脚踩在地上：内容底边贴在"地面线"上（待机/动作/睡着/落地…）
* `center` —— 悬空：内容中心贴在身体区中心（被拎起来/下落）

被抓和下落如果也按脚对齐，悬空的姿势会被硬拉回地面，看着就假了。
"""

from __future__ import annotations

import json
import os
import threading
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 素材目录沿用生成管道的 `assets/actions`（管道是"工作流"，不改它），
#: 但在桌宠这边语义是"片段库"：每个片段一个目录，里面是 frames/*.png + action.json
CLIPS_DIR = os.path.join(ROOT, "assets", "actions")
#: 人工校准层：每个片段该放大/缩小多少倍（`tools/tune_sizes.py` 生成）
SIZE_FIX_PATH = os.path.join(ROOT, "assets", "size_fix.json")

#: 用 `center` 锚点的片段（角色本来就不在地上）
CENTERED = {"held", "falling"}

#: 核心片段：缺了它们程序起不来
REQUIRED = ("idle",)


class Clip:
    """一个片段：帧文件 + 播放参数。"""

    def __init__(self, name: str, data: dict, frames_dir: str,
                 size_fix: float = 1.0) -> None:
        self.name = name
        self.data = data
        self.frames_dir = frames_dir
        self.fps = float(data.get("fps") or 24.0)
        self.loop = bool(data.get("loop"))
        self.title = str(data.get("title") or name)
        self.desc = str(data.get("desc") or "")
        self.anchor = "center" if name in CENTERED else "floor"
        #: 模型在姿势差异大的片段里会把角色画小（实测 held 只有 74%、falling 68%）。
        #: 这个系数是人工校准层，用来把她拉回一致的大小 —— 见 tools/tune_sizes.py
        self.size_fix = max(0.2, min(3.0, float(size_fix or 1.0)))
        self.files = sorted(
            (os.path.join(frames_dir, f) for f in os.listdir(frames_dir)
             if f.lower().endswith(".png"))) if os.path.isdir(frames_dir) else []
        self._box: tuple[int, int, int, int] | None = None
        self._cache: dict[int, tuple[list[Image.Image], float]] = {}

    # ------------------------------------------------------------------ 基础

    @staticmethod
    def open_frame(path: str) -> Image.Image:
        """读一帧成 RGBA（调色板 PNG 要还原 alpha，否则会丢透明）。"""
        with Image.open(path) as raw:
            if raw.mode == "P":
                img = Image.new("RGBA", raw.size, (0, 0, 0, 0))
                img.paste(raw.convert("RGBA"), (0, 0))
                return img
            return raw.convert("RGBA")

    def content_box(self, threshold: int = 24, sample: int = 4
                    ) -> tuple[int, int, int, int]:
        """整段所有帧不透明区域的并集包围盒。

        用并集（不是单帧）当缩放基准 —— 各帧按同一个框缩放，
        动作本身（蹦跳、挥手）才不会被裁掉。

        `sample=4` 表示只量每 4 帧取 1 帧。56 帧的 608x1088 素材全量要 ~0.2s，
        21 个片段就是 4 秒的启动等待；等距抽 14 帧算出来的并集几乎一样
        （循环动画的极值总会被采到），启动快 4 倍。这个框只用来**缩放和对齐**，
        不拿来裁图，略微偏小一点没有影响。

        记忆化：播放途中重算就是一次可见的卡顿（v1 在动作结束那一下踩过，
        实测 400~530ms）。
        """
        if self._box is not None:
            return self._box
        step = max(1, int(sample))
        paths = self.files[::step]
        if self.files and self.files[-1] not in paths:
            paths = paths + [self.files[-1]]        # 尾帧常常是极值，别漏
        box = None
        for path in paths:
            img = self.open_frame(path)
            alpha = np.asarray(img.getchannel("A"))
            rows = np.where((alpha > threshold).any(axis=1))[0]
            cols = np.where((alpha > threshold).any(axis=0))[0]
            if len(rows) == 0 or len(cols) == 0:
                continue
            cur = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
            box = cur if box is None else (min(box[0], cur[0]), min(box[1], cur[1]),
                                           max(box[2], cur[2]), max(box[3], cur[3]))
        if box is None:
            img = self.open_frame(self.files[0])
            box = (0, 0, img.width, img.height)
        self._box = box
        return box

    def scaled(self, target_content_h: int) -> tuple[list[Image.Image], float]:
        """按"内容并集高度"缩放到目标高度（再乘人工校准系数），结果记忆化。"""
        if target_content_h in self._cache:
            return self._cache[target_content_h]
        box = self.content_box()
        content_h = max(1, box[3] - box[1])
        scale = max(0.01, target_content_h / content_h) * self.size_fix
        out = []
        for path in self.files:
            img = self.open_frame(path)
            size = (max(1, int(round(img.width * scale))),
                    max(1, int(round(img.height * scale))))
            out.append(img.resize(size, Image.LANCZOS))
        self._cache[target_content_h] = (out, scale)
        return out, scale

    def release_cache(self) -> None:
        """放掉缩放后的帧（最占内存的那一份）。包围盒只有 4 个整数，留着。"""
        self._cache.clear()

    def __repr__(self) -> str:
        return (f"<Clip {self.name} {len(self.files)}帧 {self.fps:g}fps "
                f"{'loop' if self.loop else 'once'} {self.anchor}>")


def load_library(path: str | None = None) -> dict[str, Clip]:
    """扫 `assets/actions/*/action.json`，返回 {名字: Clip}。"""
    fixes: dict = {}
    if os.path.isfile(SIZE_FIX_PATH):
        try:
            with open(SIZE_FIX_PATH, "r", encoding="utf-8") as fh:
                fixes = json.load(fh) or {}
        except Exception as exc:
            print(f"[clips] size_fix.json 读取失败（按 1.0 处理）：{exc}")

    lib: dict[str, Clip] = {}
    if not os.path.isdir(CLIPS_DIR):
        return lib
    for name in sorted(os.listdir(CLIPS_DIR)):
        manifest = os.path.join(CLIPS_DIR, name, "action.json")
        if not os.path.isfile(manifest):
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception as exc:
            print(f"[clips] {name}/action.json 读取失败：{exc}")
            continue
        rel = data.get("frames_dir") or f"assets/actions/{name}/frames"
        frames_dir = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        clip = Clip(name, data, frames_dir, size_fix=fixes.get(name, 1.0))
        if clip.files:
            lib[name] = clip
    return lib


# --------------------------------------------------------------------------- 预热

class ClipCache:
    """后台预热 + LRU。

    为什么需要：一帧要读盘 + LANCZOS 缩放，56 帧 ≈ 0.6s，再加建 Tk 对象 ≈ 0.7s。
    放在点击那一刻做就是"点下去卡一秒"。这里拆成三段：
        ① 后台线程：读盘 + 缩放（纯 PIL/numpy，不碰 Tk）
        ② 主线程 tick：每轮只把几帧转成 PhotoImage（Tk 对象必须主线程建）
        ③ 播放时：直接取缓存，零等待
    """

    def __init__(self, keep: int = 8, batch: int = 6) -> None:
        self.keep = keep
        self.batch = batch
        self.ready: dict[str, tuple[list, tuple[int, int]]] = {}
        self.order: list[str] = []
        self.loading: dict[str, dict] = {}
        self.pending: set[str] = set()
        self.done: set[str] = set()          # "热过一次"（≠ 还在缓存里）
        self.priority: list[str] = []
        self.names: list[str] = []
        self.queue = None                    # queue.Queue，由 start() 建
        self.thread = None
        self.stop = False
        self.build = None                    # 回调：把 Clip 变成 (PIL帧, 偏移)
        self.playing: str | None = None      # 正在播的片段不能被 LRU 淘汰

    # ---------------------------------------------------------------- 生命周期

    def start(self, names: list[str], build) -> None:
        """`build(clip) -> (list[PIL], offset)` 由调用方提供（它知道画布尺寸）。"""
        import queue
        self.build = build
        self.queue = queue.Queue()
        self.names = list(names)
        self.stop = False
        self.thread = threading.Thread(target=self._worker, daemon=True,
                                       name="clip-warmer")
        self.thread.start()

    def shut(self) -> None:
        self.stop = True

    def invalidate(self) -> None:
        """画布尺寸/缩放变了：全部作废，重热。"""
        self.ready.clear()
        self.order.clear()
        self.loading.clear()
        self.pending.clear()
        self.done.clear()
        self.priority.clear()

    # ---------------------------------------------------------------- 后台线程

    def _busy(self) -> set:
        """"正在处理或已经好了"的集合 —— 这三个里面任意一个都不该重做。"""
        return set(self.ready) | set(self.pending) | set(self.loading)

    def _next(self) -> str | None:
        busy = self._busy()
        pri = [n for n in self.priority if n not in busy]
        order = pri + [n for n in self.names if n not in pri]
        for name in order:
            if name in busy:
                continue
            # 已经热过、只是被 LRU 淘汰的，先不重热（否则后台会无限空转，
            # 把主线程的推帧挤得一顿一顿 —— v1 踩过这个坑）
            if name in self.done and name not in pri:
                continue
            return name
        return None

    def _worker(self) -> None:
        while not self.stop:
            name = self._next()
            if name is None:
                time.sleep(0.2)
                continue
            self.pending.add(name)
            try:
                payload, offset = self.build(name)
                self.queue.put((name, payload, offset))
            except Exception as exc:
                self.pending.discard(name)
                print(f"[clips] 预热 {name} 失败：{exc}")
                time.sleep(0.2)

    # ---------------------------------------------------------------- 主线程

    def pump(self, make_photo, budget_ms: float = 10.0) -> None:
        """把后台送来的 PIL 帧转成 Tk 对象。

        **按时间预算**转，不是每轮固定几张：一张 `ImageTk.PhotoImage` 实测约 14ms，
        固定"每轮 6 张"就是每轮 84ms —— 预热那 20 秒里主循环会被拖到 10Hz，
        待机动画、视线、物理跟着一起卡。改成"最多占用约 10ms"之后，
        每轮大约转 1 张，主循环还能维持 ~25ms 一轮：预热慢一点，但全程不卡。
        """
        import queue
        if self.queue is None:
            return
        while True:
            try:
                name, payload, offset = self.queue.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(name)
            self.loading[name] = {"pil": payload, "i": 0, "photos": [], "offset": offset}

        deadline = time.perf_counter() + budget_ms / 1000.0
        for name, job in list(self.loading.items()):
            pil = job["pil"]
            while job["i"] < len(pil):
                job["photos"].append(make_photo(pil[job["i"]]))
                job["i"] += 1
                if time.perf_counter() >= deadline:
                    break
            if job["i"] >= len(pil):
                self.ready[name] = (job["photos"], job["offset"])
                self.order.append(name)
                del self.loading[name]
                self.done.add(name)
                if name in self.priority:
                    self.priority = [n for n in self.priority if n != name]
                self._trim()
            if time.perf_counter() >= deadline:
                break

    def _trim(self) -> None:
        while len(self.order) > self.keep:
            name = self.order.pop(0)
            if name == self.playing:
                self.order.append(name)
                if len(self.order) <= self.keep:
                    break
                continue
            self.ready.pop(name, None)

    # ---------------------------------------------------------------- 取用

    def promote(self, name: str) -> None:
        if name in self.order:
            self.order.remove(name)
        self.order.append(name)

    def get(self, name: str):
        return self.ready.get(name)

    def is_ready(self, name: str) -> bool:
        return name in self.ready

    def request(self, names: list[str]) -> None:
        """把某些片段提到预热队列最前面（点了但还没热好时用）。

        ⚠️ 必须先把"已经在处理/已经好了"的滤掉。
        视线跟随逻辑每一帧都会喊一句"我要 gaze_left"，如果不过滤，
        后台就会**一遍遍重建同一个正在载入的片段**，而主线程收到重复的
        payload 会把载入进度重置回 0 —— 结果是这个片段永远热不完、
        后台线程也永远在空转。实测：21 个片段跑 60 秒只热好 8 个，
        而且主循环被拖到 33Hz，帧间隔标准差从 1ms 涨到 9ms。
        """
        busy = self._busy()
        fresh = [n for n in names if n in self.names and n not in busy]
        if not fresh:
            return
        self.priority = fresh + [n for n in self.priority if n not in fresh]
