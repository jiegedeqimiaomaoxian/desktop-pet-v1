# -*- coding: utf-8 -*-
"""桌宠主体：窗口 / 状态机 / 物理 / 视线 / 气泡。

状态机
------
    IDLE ──点击──► ACTING ──播完──► IDLE
     │  ▲
     │  └──WAKING──┐
     │             │
     ├──久无交互──► ASLEEP
     ├──偶尔卖萌──► EMOTE ──播完──► IDLE
     │
     └──按住拖动──► HELD ──松手──► FALLING ──触地──► LANDING ──播完──► IDLE

IDLE 里还会按鼠标位置在 `idle` / `gaze_left` / `gaze_right` / `gaze_up`
之间平滑切换 —— 这是"活着"和"贴纸"最大的区别之一。
"""

from __future__ import annotations

import ctypes
import math
import os
import queue
import random
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from enum import Enum
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

from . import anim, bubble as bubble_mod, clips as clips_mod, config as config_mod, net

# --------------------------------------------------------------------------- 常量

APP_TITLE = "深海小女仆 · DeepSeek 桌宠 2.0"
TRANSPARENT = "#0a1020"       # 透明色键（墨蓝，和角色配色不会撞）
EDGE_ALPHA_CUT = 64           # alpha 二值化阈值：缩放过之后边缘才不会有彩边

GAP = 6                       # 窗口边缘留白
TAIL = 13                     # 气泡小尾巴高度
HEAD_SIZE = 84                # 气泡里的小头像边长（逻辑像素）
BUBBLE_MAX_W = 250            # 气泡最大宽度（逻辑像素）
#: 气泡**预留**几行的高度。窗口高度按它算死，所以"换一句台词"不会改变窗口尺寸
#: —— 这正是"点击之后定位不准 + 卡顿"的根因：气泡行数变了 -> 窗口高度变了 ->
#: 透明色键分层窗口整个重组一次 + 窗口位置要重新补偿，一次点击里会发生两次。
BUBBLE_MAX_LINES = 4
BUBBLE_PAD_X, BUBBLE_PAD_Y = 15, 11
HIT_STEP = 4                  # 点击命中网格采样步长
#: 主循环间隔。视线/物理/头像这些 30~60Hz 就够；**动作播放不靠它** ——
#: Player 有自己独立的时间轴 after 链，所以调大这里不会影响 24fps 的流畅度。
TICK_MS = 16

XFADE = 6                     # 状态切换的交叉淡入帧数（6 帧 @24fps ≈ 0.25s）
GAZE_DEAD_X = 46              # 视线死区：横向超过它才转头（逻辑像素）
GAZE_DEAD_Y = 70              # 纵向（抬头）死区
GAZE_DWELL = 0.45             # 视线方向最短停留，避免在边界反复横跳

FOLLOW_K = 300.0              # 拖拽时窗口跟随的弹簧刚度
FOLLOW_C = 30.0               # 阻尼
SWAY_K = 220.0                # 身体摆动（钟摆感）的弹簧
SWAY_C = 13.0
SWAY_MAX = 26                 # 摆动最大偏移（Tk 像素）
GRAVITY = 3400.0              # 下落重力（Tk 像素/秒²）
FALL_MAX = 2600.0             # 下落速度上限
BOTTOM_MARGIN = 8             # 落地时离工作区底部留多少

IDLE_TEXT = "点我一下嘛～"
FETCH_TEXT = "正在帮你查余额…"
DEFAULT_LINES = ["点我一下嘛～"]

FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "Segoe UI")

FIELD_FALLBACK = {
    "currency": "CNY", "total_balance": "-", "granted_balance": "-",
    "topped_up_balance": "-", "is_available": "-", "count": "1",
}

#: 点击时随机播的片段（在 IDLE 里点）
CLICK_POOL = ("act_bob", "act_wave", "act_tilt", "act_spin",
              "act_squat", "act_nod", "act_jump", "act_sway")
#: 自己卖萌时随机播的片段
EMOTE_POOL = ("cheer", "shy", "act_tilt", "act_sway")


class State(str, Enum):
    IDLE = "idle"
    ACTING = "acting"
    HELD = "held"
    FALLING = "falling"
    LANDING = "landing"
    ASLEEP = "asleep"
    WAKING = "waking"
    EMOTE = "emote"


# --------------------------------------------------------------------------- 小工具

def log(message: str) -> None:
    try:
        print(message)
    except Exception:
        pass


def harden_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def harden_alpha(img: Image.Image, threshold: int = EDGE_ALPHA_CUT) -> Image.Image:
    """把 alpha 二值化。

    透明色键是按像素颜色挖洞的，半透明边缘会和色键混出一圈彩边；
    缩放（LANCZOS）也会把透明像素的黑色混进边缘。二值化之后边缘就干净了。
    """
    if threshold <= 0:
        return img
    alpha = img.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    out = img.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def key_color_is_safe(key_hex: str, img: Image.Image, min_gap: float = 12.0) -> bool:
    """确认透明色键和角色身上**真正画出来的**像素都离得够远。

    ⚠️ 必须先 `harden_alpha` 再判：缩放过（LANCZOS）的 RGBA 边缘会留下一圈
    alpha 很低、RGB 接近黑的像素。如果把它们也算进来，任何深色色键都会被判成
    "和角色太近" —— 实测就是这样，程序会傻乎乎地换成洋红色键，而洋红会让
    半透明的影子混出一圈刺眼的粉边。实际绘制前我们本来就会二值化 alpha，
    所以这里也按二值化之后的像素判，才是同一件事。
    """
    img = harden_alpha(img)
    key_hex = key_hex.lstrip("#")
    key = tuple(int(key_hex[i:i + 2], 16) for i in (0, 2, 4))
    rgb = img.convert("RGB")
    alpha = img.getchannel("A")
    px, ap = rgb.load(), alpha.load()
    for y in range(0, rgb.height, 2):
        for x in range(0, rgb.width, 2):
            if ap[x, y] > 0:
                r, g, b = px[x, y]
                if abs(r - key[0]) + abs(g - key[1]) + abs(b - key[2]) < min_gap:
                    return False
    return True


def _min_gap_to_pixels(key_hex: str, img: Image.Image) -> int:
    """这张图里**不透明像素**到色键的最小曼哈顿距离（越大越安全）。"""
    hard = harden_alpha(img)
    alpha = hard.getchannel("A")
    key = tuple(int(key_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    px, ap = hard.convert("RGB").load(), alpha.load()
    best = 1 << 30
    for y in range(0, hard.height, 2):
        for x in range(0, hard.width, 2):
            if ap[x, y] > 0:
                r, g, b = px[x, y]
                d = abs(r - key[0]) + abs(g - key[1]) + abs(b - key[2])
                if d < best:
                    best = d
                    if best == 0:
                        return 0
    return best if best < (1 << 30) else 999


#: 透明色键候选。要**暗**（半透明的影子混出来才是暗的，不会发艳），
#: 又要和角色配色离得远。角色是深蓝/白/粉/金的赛璐璐，没有绿色，
#: 所以深绿通常最安全；深蓝黑系反而常常撞上头发和尾巴的暗部渐变。
KEY_CANDIDATES = ("#001a10", "#071a0c", "#0a1020", "#001020", "#12001a",
                  "#1a0010", "#0a0a12", "#ff00ff", "#00ff00")


def pick_font() -> str:
    try:
        available = set(tkfont.families())
    except Exception:
        return "TkDefaultFont"
    for name in FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


def render_balance(template: str, fields: dict) -> str:
    """套用余额模板；缺字段或模板写错都给可读提示，不崩。"""
    data = dict(FIELD_FALLBACK)
    data.update({k: str(v) for k, v in (fields or {}).items()})
    try:
        return str(template).format_map(data)
    except KeyError as exc:
        return f"⚠️ 模板里的字段不存在：{exc}\n可用字段：{', '.join(sorted(FIELD_FALLBACK))}"
    except Exception as exc:
        return f"⚠️ 余额模板格式有误：{exc}"


def cursor_pos() -> tuple[int, int]:
    """全局鼠标位置（窗口没焦点、鼠标在窗口外也能拿到）。"""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    try:
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    except Exception:
        return (-9999, -9999)
    return int(pt.x), int(pt.y)


def enable_dpi_awareness() -> None:
    """让进程 DPI 感知。

    不做的话 Windows 会把窗口位图拉伸，高分屏上整个桌宠是糊的。
    必须在 `tk.Tk()` **之前**调用。

    ⚠️ 有个坑：这件事一旦由别的模块在 import 时顺手做了，Tk 报出来的
    屏幕尺寸和 DPI 就跟着变（1536x864 -> 1920x1080），布局会整体变一个比例。
    所以这里显式、且在最早的时机做，并让 `shot.py` 之类不再在 import 时改全局状态。
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def work_area(root: tk.Misc) -> tuple[int, int, int, int]:
    """屏幕工作区（排除任务栏）：(left, top, right, bottom)。"""
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    rect = RECT()
    try:
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


_LOCK = None


def claim_lock() -> str | None:
    """单实例锁：已经有一只在跑就返回 None。"""
    global _LOCK
    if hasattr(socket, "AF_UNIX"):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind("\0desktop_pet_v2_whale")
            _LOCK = sock
            return "unix"
        except OSError:
            return None
        except Exception:
            pass
    path = os.path.join(tempfile.gettempdir(), "desktop_pet_v2_whale.lock")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip() or 0)
        except Exception:
            pid = 0
        if pid and pid != os.getpid():
            try:
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return None
            except Exception:
                return None
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    return path


def release_lock(lock: str) -> None:
    global _LOCK
    if lock == "unix":
        if _LOCK is not None:
            try:
                _LOCK.close()
            except OSError:
                pass
            _LOCK = None
        return
    try:
        os.remove(lock)
    except OSError:
        pass


# --------------------------------------------------------------------------- 主体

class Pet:
    def __init__(self) -> None:
        self.cfg = config_mod.load()
        enable_dpi_awareness()          # 必须在 tk.Tk() 之前
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.topmost = bool(self.cfg.get("always_on_top", True))
        self.root.attributes("-topmost", self.topmost)

        self.dpr = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.font_family = pick_font()
        self.bubble_font = tkfont.Font(family=self.font_family,
                                       size=max(9, int(round(11 * self.dpr))), weight="bold")
        self.small_font = tkfont.Font(family=self.font_family,
                                      size=max(8, int(round(9 * self.dpr))))

        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # --- 素材 ---
        self.clips = clips_mod.load_library()
        missing = [n for n in clips_mod.REQUIRED if n not in self.clips]
        if missing:
            messagebox.showerror(APP_TITLE, "找不到素材片段：" + ", ".join(missing) +
                                 "\n\n请先运行：python tools\\generate_mmx_comfy.py "
                                 "--style pet --actions all")
            raise SystemExit(1)
        self.key_color = self._pick_key_color()

        # --- 画布几何（先量尺寸，再起预热）---
        # content_h = 角色内容的目标高度；body_w/body_h = 装得下所有片段的框
        self.content_h = self._target_body_h()
        self.body_w, self.body_h, self.floor_y = self._measure_canvas(self.content_h)
        self._layout_avatar()

        # --- 运行时状态 ---
        self.state = State.IDLE
        self.state_since = time.perf_counter()
        self.last_interaction = time.perf_counter()
        self.gaze_target = "idle"
        self.gaze_since = time.perf_counter()
        self.sway = 0.0                 # 身体摆动偏移（Tk 像素）
        self.sway_v = 0.0
        self.vx = 0.0                   # 窗口弹簧速度
        self.vy = 0.0
        self.fall_v = 0.0
        self.drag_target = (0.0, 0.0)
        self.drag_from = None
        self.drag_origin = (0.0, 0.0)
        self.moved = False
        self.ground_y = 0.0
        self.shadow_scale = 1.0

        self.clicks = 0
        self.active = False
        self.reset_job = None
        self.fetching = False
        self.results: queue.Queue = queue.Queue()
        self.current_text = IDLE_TEXT
        self.bubble_box = (0, 0, 0, 0)
        self.win_w = self.win_h = 0
        self.body_origin = (0.0, 0.0)
        self.placed = False
        self.last_z = 0.0

        self.lines, self.lines_note, self.action_lines = config_mod.load_lines(
            config_mod.text_path(self.cfg))
        self.lines_mtime = self._text_mtime()
        self.line_index = 0
        self.action_line_index = 0

        # --- 动画播放器 + 预热缓存 ---
        self.player = anim.Player(self.root, self._draw_body, self._make_photo)
        # 常驻套数默认 = 片段总数：这一版整套素材是"一个角色的不同状态"，
        # 少热一个就可能在切换时卡一下（要先花约 0.8s 重新预热）。
        # 内存账：56 帧 x 约 380x380 x 4B ≈ 32MB/片段，21 个片段约 680MB。
        # 嫌占内存就在 pet_config.json 里把 preload_keep 调到 6~8。
        keep = int(self.cfg.get("preload_keep") or 0) or len(self.clips)
        self.cache = clips_mod.ClipCache(keep=max(6, keep))
        self.avatar_pil: list = []
        self.avatar_index = 0      # 保留给调试用
        self.avatar_photo = None
        self.avatar_photos: list = []
        self.avatar_timeline: list = []
        self.shadows: dict[int, ImageTk.PhotoImage] = {}
        self._pose_cache: dict = {}
        self._hit_grid = None
        self._recent: list[str] = []
        self._last_emote = 0.0
        self._last_tick = time.perf_counter()
        self._avatar_t0 = time.perf_counter()
        self.body_display = None
        self._blank_photo = None

        self._build_window()
        self._start_warmer()
        self._bind()
        self.show_text(self._idle_hint(), speak=False, keep_active=False)
        self.root.after(30, self.tick)
        self.root.after(500, self._announce)

    # ------------------------------------------------------------------ 素材与几何

    def _target_body_h(self) -> int:
        """角色在屏幕上应该多高（画布像素）。

        ⚠️ **不要乘 dpr**。这里已经是"屏幕高度的百分之多少"，
        而屏幕尺寸本身就是物理像素（进程是 DPI 感知的）—— 再乘一次
        dpr 会在 125% / 150% 缩放的机器上把角色放大一倍多。
        上下限也按屏幕比例给，别写死像素，否则高 DPI 屏上比例会走样。
        """
        area = work_area(self.root)
        screen_h = area[3] - area[1]
        want = int(screen_h * 0.34)
        want = max(int(screen_h * 0.18), min(want, int(screen_h * 0.46)))
        want = int(want * float(self.cfg.get("scale", 1.0) or 1.0))
        return max(80, want)

    def _measure_canvas(self, content_target: int) -> tuple[int, int, int]:
        """量出身体区尺寸与地面线。

        ⚠️ `content_target` 是**角色内容的目标高度**，跟返回的身体区高度是两回事。
        以前这两个共用同一个 `self.body_h`，于是 `_measure_canvas` 一返回就把
        目标高度悄悄改掉了，所有缩放系数跟着漂、帧从身体区顶上冒出去 ——
        表现是"角色压在气泡上"，根因却在这儿，很难一眼看出来。

        必须按每个片段的锚点分别算：`floor` 锚点是**内容底边贴地面线**，
        帧从地面线往上下两边撑；`center` 锚点是整帧居中。

        返回 (身体区宽, 身体区高, 地面线 y)。
        """
        width = 0
        floor_need = 0.0                        # 地面线以上至少要留多少
        below_need = 0.0                        # 地面线以下至少要留多少
        center_need = 0.0                       # 悬空片段整帧至少要多高
        for clip in self.clips.values():
            box = clip.content_box()
            scale = content_target / max(1, box[3] - box[1]) * clip.size_fix
            with Image.open(clip.files[0]) as raw:
                fw, fh = raw.size
            fw = int(round(fw * scale))
            fh = int(round(fh * scale))
            width = max(width, fw)
            if clip.anchor == "floor":
                floor_need = max(floor_need, box[3] * scale)
                below_need = max(below_need, fh - box[3] * scale)
            else:
                center_need = max(center_need, float(fh))
        margin = max(2, int(round(4 * self.dpr)))
        floor = int(math.ceil(floor_need))
        height = int(math.ceil(max(floor + below_need, center_need))) + margin
        return max(40, width), height, floor

    def _clip_scale(self, clip) -> float:
        """这个片段的缩放系数（内容并集高度 -> content_h，含人工校准系数）。

        ⚠️ 只读 `content_box()`（有记忆化），**不要**调 `clip.scaled()` ——
        那会把 56 帧全缩一遍（~0.6s）。而缓存建好之后 PIL 那份就被释放了，
        于是每次状态切换都会重新缩一遍 → 主线程卡死。这个坑很隐蔽。
        """
        box = clip.content_box()
        return self.content_h / max(1, box[3] - box[1]) * clip.size_fix

    def _clip_origin(self, clip) -> tuple[float, float]:
        """算一个片段画在身体区里的落点（只需要 content_box，不做缩放）。

        水平：内容框**居中**。
        竖直：`floor` 锚点把内容底边贴在地面线上；`center` 锚点把内容居中
        （被抓/下落这两个姿势本来就不在地上，硬按脚对齐会把悬空感抹掉）。
        """
        box = clip.content_box()
        scale = self._clip_scale(clip)
        content_w = (box[2] - box[0]) * scale
        content_h = (box[3] - box[1]) * scale
        x = (self.body_w - content_w) / 2 - box[0] * scale
        if clip.anchor == "floor":
            y = self.floor_y - box[3] * scale
        else:
            y = (self.body_h - content_h) / 2 - box[1] * scale
        return (round(x, 1), round(y, 1))

    def _clip_size(self, clip) -> tuple[int, int]:
        """片段帧缩放后的尺寸（只读头一帧的文件头，不解码像素）。"""
        box = clip.content_box()
        scale = self._clip_scale(clip)
        with Image.open(clip.files[0]) as raw:
            w, h = raw.size
        return (max(1, int(round(w * scale))), max(1, int(round(h * scale))))

    def _build_clip(self, name: str):
        """后台线程用：读盘 + 缩放 + 算落点（不碰任何 Tk 对象）。"""
        clip = self.clips[name]
        frames, _ = clip.scaled(self.content_h)
        origin = self._clip_origin(clip)
        payload = [f.copy() for f in frames]
        clip.release_cache()          # 放掉 PIL 那份，像素的所有权交给 Tk
        return payload, origin

    def _make_photo(self, img: Image.Image) -> ImageTk.PhotoImage:
        """主线程用：PIL -> Tk（必须在主线程建）。"""
        return ImageTk.PhotoImage(harden_alpha(img))

    def _warm_order(self) -> list[str]:
        """预热顺序：最可能马上用到的排前面。"""
        order = ["idle", "gaze_left", "gaze_right", "gaze_up"]
        order += [n for n in CLICK_POOL if n in self.clips]
        order += ["held", "falling", "landing", "asleep", "waking"]
        order += [n for n in self.clips if n not in order]
        return [n for n in order if n in self.clips]

    def _start_warmer(self) -> None:
        self.cache.start(self._warm_order(), self._build_clip)
        threading.Thread(target=self._build_avatar, daemon=True,
                         name="avatar-builder").start()
        log(f"[pet] 素材 {len(self.clips)} 个片段，开始后台预热…")

    def rebuild_geometry(self) -> None:
        """大小倍率 / 屏幕变了：重新量画布、作废预热、重来一遍。"""
        self.content_h = self._target_body_h()
        self.body_w, self.body_h, self.floor_y = self._measure_canvas(self.content_h)
        self._layout_avatar()
        self._pose_cache.clear()
        self._hit_grid = None
        self.shadows.clear()
        self.cache.invalidate()
        self.player.cancel()
        self.cache.start(self._warm_order(), self._build_clip)
        threading.Thread(target=self._build_avatar, daemon=True,
                         name="avatar-builder").start()
        self.show_text(self.current_text, speak=False)
        log(f"[pet] 画布重建：角色 {self.body_w}x{self.body_h}(内容 {self.content_h})，素材重新预热中")

    def _build_avatar_timeline(self) -> None:
        """把 56 张头像压成"真正有变化的那些帧"。

        为什么要压：桌宠是 `-transparentcolor` 分层窗口，**每改一次画布
        Windows 就要把整个窗口重新合成一遍**（实测约 3.6ms / 484x656）。
        头像不眨眼的时候连续几十帧是一模一样的，逐帧 `itemconfigure` 等于
        白白让窗口重组几十次。压完之后每轮眨眼的画布更新从 24 次降到几次。

        结果是一串 `(photo, 起始秒)`，按时间取即可。
        """
        photos = self.avatar_photos
        if not photos:
            self.avatar_timeline = []
            return
        fps = 24.0
        steps = [(0.0, photos[0])]
        previous = self.avatar_pil[0]
        import numpy as np
        prev_arr = np.asarray(previous.convert("RGBA"), dtype=np.int16)
        for i in range(1, len(photos)):
            arr = np.asarray(self.avatar_pil[i].convert("RGBA"), dtype=np.int16)
            changed = int((np.abs(arr - prev_arr).max(axis=2) > 24).sum())
            if changed > 12:                      # 小于十来像素的变化肉眼看不见
                steps.append((i / fps, photos[i]))
            prev_arr = arr
        self.avatar_timeline = steps
        if len(steps) < len(photos):
            log(f"[pet] 气泡头像：{len(photos)} 帧里有 {len(photos) - len(steps)} 帧"
                f"和上一帧一样，已合并（少刷 {len(photos) - len(steps)} 次画布）")
        else:
            log(f"[pet] 气泡头像：{len(photos)} 帧都在动（呼吸带动头部），逐帧播放")

    def _avatar_step(self, elapsed: float):
        if not self.avatar_timeline:
            return None
        duration = len(self.avatar_photos) / 24.0
        t = elapsed % duration
        chosen = self.avatar_timeline[0][1]
        for start, photo in self.avatar_timeline:
            if start <= t:
                chosen = photo
            else:
                break
        return chosen

    def _layout_avatar(self) -> None:
        self.avatar_size = max(24, int(round(HEAD_SIZE * self.dpr)))

    def _build_avatar(self) -> None:
        """后台线程：从 idle 片段裁出头部做气泡头像，并顺手建好点击命中网格。

        两件事都靠"把 idle 的 56 帧读一遍"，所以合并到同一个线程里做，
        省一次全量读盘；也避免把缩放开销丢到主线程（点一下要等的那种卡）。
        """
        clip = self.clips.get("idle")
        if clip is None:
            return
        try:
            frames = [clip.open_frame(p) for p in clip.files]
            box = bubble_mod.head_box(clip, frames[0])
            self.avatar_pil = bubble_mod.make_avatar(frames, box, self.avatar_size)
            log(f"[pet] 气泡头像就绪（{len(self.avatar_pil)} 帧，取自 idle）")
        except Exception as exc:
            log(f"[pet] 头像生成失败（用静态的）：{exc}")
            self.avatar_pil = []
        try:
            self._hit_grid = self._build_hit_grid(clip)
            log(f"[pet] 点击命中网格就绪（{len(self._hit_grid)} 格）")
        except Exception as exc:
            log(f"[pet] 命中网格生成失败：{exc}")

    def _pick_key_color(self) -> str:
        """挑一个不撞角色的透明色键，并把窗口/画布设成它。

        为什么不能写死：角色身上有一大片从深蓝渐变到接近纯黑的暗部
        （实测最暗到 RGB(0,0,0)）。写死的深色键很容易正好落在渐变上，
        Tk 的 `-transparentcolor` 是**精确匹配**，撞上就是把角色挖出一串洞。
        所以这里拿真实素材试一遍候选，选"离所有不透明像素最远"的那个。
        """
        probes = []
        for name in ("idle", "act_wave", "gaze_left"):
            clip = self.clips.get(name)
            if clip is None:
                continue
            img = clip.open_frame(clip.files[len(clip.files) // 3])
            img.thumbnail((200, 200), Image.LANCZOS)
            probes.append(img)
        if not probes:
            return TRANSPARENT

        scored = []
        for hexc in KEY_CANDIDATES:
            gap = min(_min_gap_to_pixels(hexc, img) for img in probes)
            if gap < 12:
                continue
            r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
            scored.append((0.299 * r + 0.587 * g + 0.114 * b, gap, hexc))
        if not scored:
            scored = [(999, 0, "#ff00ff")]          # 兜底：洋红
            log("[pet] ⚠️ 没有找到理想的透明色键，退回洋红（影子边缘可能发紫）")
        scored.sort()                                # 先暗，再谈距离
        chosen = scored[0][2]
        if chosen != TRANSPARENT:
            log(f"[pet] 透明色键 {TRANSPARENT} -> {chosen}"
                f"（离角色最近的不透明像素 {scored[0][1]} 单位）")
            self.root.configure(bg=chosen)
            self.canvas.configure(bg=chosen)
            try:
                self.root.attributes("-transparentcolor", chosen)
            except tk.TclError:
                pass
        return chosen

    # ------------------------------------------------------------------ 窗口布局

    def _build_window(self) -> None:
        self.bubble_wrap = BUBBLE_MAX_W
        self.reserve_lines = self._compute_reserve_lines()
        self.shadows = {}
        geom = self._layout(self.current_text)
        self._apply_window(geom)
        self.win_w, self.win_h = geom["window"]
        log(f"[pet] 气泡预留 {self.reserve_lines} 行；窗口固定 "
            f"{self.win_w}x{self.win_h}（换台词不会改尺寸）")

    def _compute_reserve_lines(self) -> int:
        """气泡要**预留**几行的高度。

        做法：把"这只宠物这辈子可能显示的最长文本"都拿来折一遍取最大值 ——
        开场提示、正在查余额、余额文案（用偏长的数字试）、最长的一句台词、
        每个动作专属段落里最长的一句。预留够了下拉，窗口高度就永远不用变。

        为什么要这么较真：桌宠是 `-transparentcolor` 分层窗口，
        **每改一次窗口尺寸 Windows 就要把整个窗口重新合成一遍**，
        而且还要挪窗口位置去补偿"脚不动"。实测点一下会发生 2 次尺寸变化，
        首帧间隔飙到 367ms —— 用户看到的就是"点一下，角色跳一下还卡一下"。
        """
        samples = [self._idle_hint(), "正在帮你查余额…"]
        try:
            samples.append(render_balance(
                self.cfg.get("balance_template", ""),
                {"total_balance": "8888.88", "currency": "CNY",
                 "granted_balance": "8888.88", "topped_up_balance": "8888.88"}))
        except Exception:
            pass
        if self.lines:
            samples.append(max(self.lines, key=len))
        for pool in (self.action_lines or {}).values():
            if pool:
                samples.append(max(pool, key=len))
        width = self.bubble_wrap * self.dpr
        count = max(len(bubble_mod.wrap_text(t, self.bubble_font, width))
                    for t in samples if t)
        return max(2, min(6, count))

    def _layout(self, text: str) -> dict:
        """算气泡与窗口尺寸。

        ⚠️ **窗口尺寸是"算死"的常量，不随文字变** —— 这是这一版最关键的一条。

        宽度按"最大气泡宽度"算死，高度按 `reserve_lines` 行算死，
        气泡框的**底边固定在同一个 y** 上（文字少就往上收，像真的对话框）。
        换多少句台词，窗口几何一毫米都不动，角色也就一动不动。

        全部用画布像素（Tk canvas 坐标），不要再乘 dpr。
        """
        dpr = self.dpr
        pad_x, pad_y = BUBBLE_PAD_X * dpr, BUBBLE_PAD_Y * dpr
        gap, tail = GAP * dpr, TAIL * dpr
        lines = bubble_mod.wrap_text(text, self.bubble_font, self.bubble_wrap * dpr)
        line_h = self.bubble_font.metrics("linespace")
        avatar = self.avatar_size

        box_w = max(HEAD_SIZE * dpr * 0.7,
                    min(max((self.bubble_font.measure(l) for l in lines), default=10),
                        self.bubble_wrap * dpr) + pad_x * 2) + avatar + 10 * dpr
        box_h = max(avatar + 8 * dpr, len(lines) * line_h + pad_y * 2)

        reserve_w = self.bubble_wrap * dpr + pad_x * 2 + avatar + 10 * dpr
        reserve_h = max(avatar + 8 * dpr, self.reserve_lines * line_h + pad_y * 2)

        win_w = int(max(self.body_w + gap * 2, reserve_w + gap * 2))
        # 气泡底边固定在预留区底部 —— 尾巴永远指着同一个地方
        box_bottom = gap + max(reserve_h, box_h)
        win_h = int(box_bottom + tail + self.body_h + gap)
        return {
            "lines": lines, "line_h": line_h,
            "box": ((win_w - box_w) / 2, box_bottom - box_h, box_w, box_h),
            "body": ((win_w - self.body_w) / 2, box_bottom + tail),
            "window": (win_w, win_h),
        }

    def _apply_window(self, geom: dict) -> None:
        """套用窗口尺寸；尺寸没变就**不调 geometry()**（每次调用都会重排分层窗口）。

        尺寸现在是**常量**（气泡按预留行数算死），所以正常情况下这里只在启动
        那一次真正调 `geometry()`，之后换多少句台词都不会重排窗口 ——
        "点击后定位不准 + 卡顿"的根因就在这儿。
        """
        old_w, old_h = self.win_w, self.win_h
        new_w, new_h = geom["window"]
        if not self.placed:
            self.placed = True
            x, y = self._start_position(geom)
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if new_w != old_w or new_h != old_h:
                # 只在"真的换了尺寸"时补偿（比如改了大小倍率）。
                # 水平也要补偿：body_x = (win_w - body_w)/2，窗口变宽角色会跟着右移。
                x -= (new_w - old_w) // 2
                y -= (new_h - old_h)
        area = work_area(self.root)
        # 水平按**角色中心**夹，不按窗口边。
        # 窗口比角色宽（身体区要给所有片段留位置），按窗口夹的话右边能拖到
        # x=1860、角色中心跑到 2102 —— 整个人挂在屏幕外，看着就是"定位不准"，
        # 而且再也点不到她。实测就是这么翻车的。
        center = geom["body"][0] + self.body_w / 2
        x = int(min(max(area[0] - center, x), area[2] - center))
        # 竖直方向按**角色**夹，不按窗口夹：
        # 窗口比角色高（气泡在上、脚下方还有一圈透明留白），如果按
        # "整个窗口必须留在工作区内"来夹，她想站到屏幕底部就会被顶起来
        # 一一实测被顶高 83px，看着就是"悬在半空、影子缩成一半"。
        # 允许窗口底部伸到屏幕外（那一圈本来就是透明的），只要脚不穿到地面以下。
        y = min(max(area[1], y), max(area[1], int(self.ground_window_y(geom))))
        moved = (new_w != old_w or new_h != old_h
                 or x != self.root.winfo_x() or y != self.root.winfo_y())
        self.win_w, self.win_h = new_w, new_h
        if new_w != old_w or new_h != old_h:
            self.canvas.configure(width=new_w, height=new_h)
        if moved:
            self.root.geometry(f"{new_w}x{new_h}+{x}+{y}")

    def ground_window_y(self, geom: dict | None = None) -> float:
        """角色**站在地面上**时，窗口应该在的 y（屏幕坐标）。

        注意"地面"是按**脚**算的，不是按窗口底边 —— 身体区比角色高
        （要给"被抓/下落"的悬空姿势留地方），用窗口底边当地面会让她永远悬在半空。
        """
        body_y = geom["body"][1] if geom else self.body_origin[1]
        area = work_area(self.root)
        return area[3] - BOTTOM_MARGIN - (body_y + self.floor_y)

    def _start_position(self, geom: dict) -> tuple[int, int]:
        """首次出现的位置：配置里记着就用记着的，否则**站在地面上**（右下角）。

        以前默认是"窗口底边离屏幕底 60px"，可落地逻辑算的是"脚踩在屏幕底"，
        两者差了 150 多像素 —— 结果一启动她就悬在半空、影子缩到一半大，
        看着就是"位置不对"。现在起始位置直接对齐落地线。
        """
        pos = self.cfg.get("pos")
        area = work_area(self.root)
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            return int(pos[0]), int(pos[1])
        return (int(area[2] - geom["window"][0] - 40 * self.dpr),
                int(self.ground_window_y(geom)))

    # ------------------------------------------------------------------ 绘制

    def _draw_body(self, photo, x, y) -> None:
        """播放器回调：把当前帧画到角色位置。

        ⚠️ **约定：(x, y) 一律是绝对画布坐标**，这里不再做任何换算。

        这里踩过一个很隐蔽的坑：正片帧的落点是"相对身体区"的（`_clip_origin`
        算出来的），而交叉淡入的过渡帧是 `fade_frames()` 给的**绝对**画布坐标。
        如果这里统一给两者都加上 `body_origin`，正片帧是对的、过渡帧就被加了
        两次 —— 表现为**一点击，角色先往下跳 175px（正好等于 body_origin[1]）、
        持续 0.25 秒，然后弹回原位**。

        更坑的是：验证脚本当时把"帧号 < 0 的过渡帧"当噪声过滤掉了，
        于是这条 bug 在数据里完全看不见，只能靠肉眼发现。
        现在改成"谁给坐标谁负责换算"：`enter()` 把相对落点转成绝对值再交给
        播放器，播放器和这里全程只用绝对坐标。
        """
        item = self._body_item()
        if item is None:
            return
        self.canvas.itemconfigure(item, image=photo)
        self.canvas.coords(item, x + self.sway, y)
        self.body_display = (photo, x, y)

    def _body_item(self):
        items = self.canvas.find_withtag("body")
        return items[0] if items else None

    def _avatar_item(self):
        items = self.canvas.find_withtag("avatar")
        return items[0] if items else None

    def show_text(self, text: str, speak: bool = True,
                  keep_active: bool | None = None) -> None:
        """重画气泡 + 角色（角色那张图会被原样贴回来，不会闪一下静态图）。"""
        if keep_active is not None:
            self.active = keep_active
        self.current_text = text
        geom = self._layout(text)
        # 记住当前画面上那张图，重建画布之后要贴回去
        prev = getattr(self, "body_display", None)

        self._apply_window(geom)
        dpr = self.dpr
        lines = geom["lines"]
        line_h = geom["line_h"]
        box_x, box_y, box_w, box_h = geom["box"]
        self.bubble_box = (box_x, box_y, box_x + box_w, box_y + box_h)

        self.canvas.delete("all")
        self.canvas.create_polygon(
            bubble_mod.round_rect_points(box_x, box_y, box_x + box_w, box_y + box_h, 16 * dpr),
            smooth=True, fill=bubble_mod.BUBBLE_BG, outline=bubble_mod.BUBBLE_LINE, width=2)

        tail_x = self.win_w / 2
        self.canvas.create_polygon(
            tail_x - 9 * dpr, box_y + box_h - 2, tail_x + 9 * dpr, box_y + box_h - 2,
            tail_x, box_y + box_h + TAIL * dpr,
            fill=bubble_mod.BUBBLE_BG, outline=bubble_mod.BUBBLE_LINE, width=2)
        self.canvas.create_line(tail_x - 7 * dpr, box_y + box_h - 1, tail_x + 7 * dpr,
                                box_y + box_h - 1, fill=bubble_mod.BUBBLE_BG, width=3)

        # 小头像（会眨眼，和角色同一套素材）
        tx = box_x + 9 * dpr
        if self.avatar_photo is not None:
            head_y = box_y + max(4 * dpr, (box_h - self.avatar_size) / 2)
            self.canvas.create_image(tx, head_y, image=self.avatar_photo, anchor="nw",
                                     tags="avatar")
            tx += self.avatar_size + 9 * dpr
        ty = box_y + (box_h - len(lines) * line_h) / 2
        for i, line in enumerate(lines):
            self.canvas.create_text(tx, ty + i * line_h, text=line, anchor="nw",
                                    fill=bubble_mod.BUBBLE_TEXT, font=self.bubble_font)

        # 身体区：影子 + 角色
        new_body = (geom["body"][0], geom["body"][1])
        old_body = self.body_origin
        self.body_origin = new_body
        shift = (new_body[0] - old_body[0], new_body[1] - old_body[1])
        if shift[0] or shift[1]:
            # 窗口因为气泡行数变化而长高/变矮时，角色（含正在播的动作帧、
            # 以及还没播完的过渡帧）跟着挪同样的量 —— 屏幕上看起来纹丝不动。
            # 现在窗口尺寸是常量、shift 正常恒为 0，这段只在"改大小倍率"时才会走到。
            if prev is not None:
                self.body_display = (prev[0], prev[1] + shift[0], prev[2] + shift[1])
                prev = self.body_display
            if self.player.transition:
                self.player.transition = [
                    (img, (pos[0] + shift[0], pos[1] + shift[1]))
                    for img, pos in self.player.transition]
            if self.player.name is not None:
                self.player.origin = (self.player.origin[0] + shift[0],
                                      self.player.origin[1] + shift[1])
        self._draw_shadow()
        if prev is not None:
            self.canvas.create_image(prev[1] + self.sway, prev[2], image=prev[0],
                                     anchor="nw", tags="body")
        else:
            self.canvas.create_image(0, 0, image=self._blank(), anchor="nw", tags="body")
        self.keep_front()

    def _blank(self) -> ImageTk.PhotoImage:
        if getattr(self, "_blank_photo", None) is None:
            img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
            self._blank_photo = ImageTk.PhotoImage(img)
        return self._blank_photo

    def _shadow_photo(self, width: int) -> ImageTk.PhotoImage:
        key = max(20, int(width))
        if key not in self.shadows:
            img = bubble_mod.soft_shadow(key, int(key * 0.26),
                                         alpha=int(80 * self.shadow_scale))
            self.shadows[key] = ImageTk.PhotoImage(img)
        return self.shadows[key]

    def _draw_shadow(self) -> None:
        """脚下投影：离地越高越小越淡（被抓起来的时候尤其明显）。"""
        if not self.cfg.get("shadow", True):
            return
        base_w = max(20, int(self.body_w * 0.62))
        w = max(16, int(base_w * self.shadow_scale))
        self.canvas.create_image(self.body_origin[0] + self.body_w / 2,
                                 self.body_origin[1] + self.floor_y + 4 * self.dpr,
                                 image=self._shadow_photo(w), anchor="s", tags="shadow")

    # ------------------------------------------------------------------ 状态机

    def _pose(self, name: str | None, index: int = 0):
        """某个片段某一帧的 (PIL 图, 画布落点)，用来做过渡的起点/终点。

        ⚠️ 只读**一帧**、只缩**一帧**，并且结果进小缓存。过渡在每次状态切换时
        都要拿起点和终点各一次，如果这里顺手把整段缩一遍（~0.6s），
        点一下就要等半秒 —— v1 踩过。
        """
        if name is None or name not in self.clips:
            return None
        clip = self.clips[name]
        pos = index % max(1, len(clip.files))
        key = (name, pos)
        hit = self._pose_cache.get(key)
        if hit is not None:
            return hit
        img = clip.open_frame(clip.files[pos])
        scale = self._clip_scale(clip)
        size = (max(1, int(round(img.width * scale))),
                max(1, int(round(img.height * scale))))
        img = img.resize(size, Image.LANCZOS)
        rel = self._clip_origin(clip)
        # 返回到**画布坐标**：过渡帧、起点/终点都在画布坐标系里比对
        pose = (img, (self.body_origin[0] + rel[0], self.body_origin[1] + rel[1]))
        if len(self._pose_cache) > 48:
            self._pose_cache.clear()
        self._pose_cache[key] = pose
        return pose

    def _current_pose(self):
        """现在画面上真正显示的是哪一帧（做交叉淡入的起点）。

        必须取**当前帧号**，不能图省事用第 0 帧 —— 从第 30 帧淡回第 0 帧
        会看到角色先"跳"回去再淡出。
        """
        if self.player.name is not None:
            index = max(0, self.player.index)
            return self._pose(self.player.name, index)
        return None

    def enter(self, state: State, clip_name: str, *, loops: int = 1,
              on_done=None, fade: int = XFADE) -> bool:
        """切到某个状态并播对应片段（带交叉淡入）。"""
        entry = self.cache.get(clip_name)
        if entry is None:
            # 还没热好：排队 + 这次先不切（宁可保持现状，也不要卡一下）
            self.cache.request([clip_name])
            return False
        frames, rel_origin = entry
        clip = self.clips[clip_name]
        # 缓存里存的是"相对身体区"的落点，这里转成**绝对画布坐标**再交给播放器。
        # 过渡帧本来就是绝对坐标，两者必须是同一个坐标系 ——
        # 不然过渡帧会被加两次 body_origin，一点击角色就往下跳 175px。
        origin = (self.body_origin[0] + rel_origin[0],
                  self.body_origin[1] + rel_origin[1])
        target = self._pose(clip_name, 0)
        transition = []
        if fade > 0 and target is not None:
            source = self._current_pose()
            if source is not None:
                try:
                    # 只做像素合成，**不**在这里转 Tk 图 —— 5 张 PhotoImage 要 35ms，
                    # 全堆在点击那一刻就是肉眼可见的延迟。交给 Player 按需转。
                    pil_frames, box = anim.fade_frames(source[0], source[1],
                                                       target[0], target[1], fade)
                    transition = [(img, box) for img in pil_frames]
                except Exception as exc:
                    log(f"[pet] 过渡生成失败（直接硬切）：{exc}")
                    transition = []
        self.cache.playing = clip_name
        self.player.play(clip_name, frames, origin, loop=clip.loop, fps=clip.fps,
                         loops=loops if clip.loop else 1, transition=transition,
                         on_done=on_done, first_pil=target[0] if target else None)
        self.state = state
        self.state_since = time.perf_counter()
        return True

    def _pick(self, pool) -> str | None:
        ready = [n for n in pool if self.cache.is_ready(n)]
        if not ready:
            self.cache.request(list(pool))
            return None
        avoid = getattr(self, "_recent", [])
        fresh = [n for n in ready if n not in avoid]
        return random.choice(fresh or ready)

    # ------------------------------------------------------------------ 交互

    def _bind(self) -> None:
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_menu)
        self.root.bind("<Escape>", lambda e: self.quit_app())
        self.canvas.focus_set()

    def hit_body(self, x: int, y: int) -> bool:
        """点到的位置是不是角色本体（透明处不算）。"""
        ox, oy = self.body_origin
        sx, sy = int(x - ox), int(y - oy)
        if sx < 0 or sy < 0 or sx >= self.body_w or sy >= self.body_h:
            return False
        grid = getattr(self, "_hit_grid", None)
        if grid is None:
            # 网格还在后台建（启动后头一两秒）：这段期间宁可"点哪儿都算"，
            # 也别让用户点了没反应
            return True
        return (sx // HIT_STEP, sy // HIT_STEP) in grid

    def _build_hit_grid(self, clip) -> set:
        """用待机片段的中段帧做一张稀疏命中网格（比逐像素扫快得多）。

        注意网格的坐标是**身体区坐标系**（已经加上落点），因为点击事件给的是
        画布坐标。
        """
        try:
            img = clip.open_frame(clip.files[len(clip.files) // 3])
            alpha = img.getchannel("A")
            scale = self._clip_scale(clip)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                             Image.LANCZOS)
            ox, oy = self._clip_origin(clip)
            alpha = img.getchannel("A")
            ap = alpha.load()
            grid: set = set()
            for y in range(0, alpha.height, HIT_STEP):
                for x in range(0, alpha.width, HIT_STEP):
                    if ap[x, y] > 40:
                        grid.add((int((x + ox) // HIT_STEP), int((y + oy) // HIT_STEP)))
            return grid
        except Exception as exc:
            log(f"[pet] 命中网格生成失败：{exc}")
            return set()

    def hit_bubble(self, x: int, y: int) -> bool:
        bx0, by0, bx1, by1 = self.bubble_box
        return bx0 - 4 <= x <= bx1 + 4 and by0 - 4 <= y <= by1 + 18

    def on_press(self, event) -> None:
        self.drag_from = (event.x_root, event.y_root)
        self.moved = False

    def on_drag(self, event) -> None:
        if not self.drag_from:
            return
        sx, sy = self.drag_from
        dx, dy = event.x_root - sx, event.y_root - sy
        if abs(dx) + abs(dy) > 5:
            if not self.moved:
                self.moved = True
                self._begin_hold()
        if not self.moved:
            return
        self.interact()
        new_x = self.root.winfo_x() + (event.x_root - self._last_motion[0])
        new_y = self.root.winfo_y() + (event.y_root - self._last_motion[1])
        self._last_motion = (event.x_root, event.y_root)
        # 身体摆动：拖得越快，摆得越开（钟摆感），弹簧把它拉回来
        self.sway_v += (event.x_root - sx) * 0.06
        area = work_area(self.root)
        new_x = min(max(area[0] - self.win_w // 3, new_x), area[2] - 60)
        new_y = min(max(area[1], new_y), area[3] - 40)
        self.root.geometry(f"+{int(new_x)}+{int(new_y)}")

    def on_release(self, event) -> None:
        was_drag = self.moved
        self.drag_from = None
        self.moved = False
        if was_drag:
            self._release_hold()
        elif self.hit_body(event.x, event.y) or self.hit_bubble(event.x, event.y):
            self.on_click()

    def _begin_hold(self) -> None:
        if not self.cache.is_ready("held"):
            self.cache.request(["held", "falling", "landing"])
        self._last_motion = cursor_pos()
        self.enter(State.HELD, "held", loops=anim.FOREVER, fade=XFADE)

    def _release_hold(self) -> None:
        if not self.cfg.get("physics", True):
            # 关了物理：松手就站住，不往下掉
            self.sway_v = 0.0
            self.enter(State.IDLE, "idle", loops=anim.FOREVER, fade=3)
            return
        self.fall_v = max(160.0, abs(self.sway_v) * 2.5)
        if not self.enter(State.FALLING, "falling", loops=anim.FOREVER, fade=3):
            self.enter(State.IDLE, "idle", loops=anim.FOREVER, fade=3)

    def on_menu(self, event) -> None:
        menu = tk.Menu(self.root, tearoff=0, font=self.small_font)
        menu.add_command(label="🔄 刷新余额", command=lambda: self.on_click(force_balance=True))
        menu.add_command(label="💬 换一句话", command=self.next_line)
        menu.add_command(label="🎬 随便做个动作", command=self.random_action)
        menu.add_command(label="😴 让她睡一会儿", command=self.sleep_now)
        menu.add_command(label="📄 编辑话语文本", command=self.open_text_file)
        menu.add_separator()
        menu.add_command(label="⚙️ 设置…", command=self.open_settings)
        menu.add_command(label="🛠️ 直接编辑配置文件", command=self.open_config_file)
        menu.add_checkbutton(label="📌 窗口置顶", command=self.toggle_topmost,
                             variable=tk.BooleanVar(value=self.topmost))
        menu.add_command(label="♻️ 清零点击次数", command=self.reset_clicks)
        menu.add_separator()
        menu.add_command(label="❌ 退出", command=self.quit_app)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------ 点击逻辑

    def interact(self) -> None:
        self.last_interaction = time.perf_counter()

    def on_click(self, force_balance: bool = False) -> None:
        if self.fetching:
            return
        self._reload_lines()
        self.interact()
        self._schedule_reset()

        if self.state == State.ASLEEP:
            self.enter(State.WAKING, "waking", fade=2,
                       on_done=lambda: self.enter(State.IDLE, "idle", loops=anim.FOREVER))
            self.show_text("啊！我没睡，我醒着呢。")
            self.clicks = 0
            return
        if self.state in (State.WAKING, State.LANDING):
            return

        first = force_balance or self.clicks == 0
        self.clicks += 1
        self.active = True
        if first:
            self.clicks = 1
            self._play_click_action()
            self._fetch_balance()
        else:
            self._play_click_action()
            self.next_line(schedule=False)

    def _play_click_action(self) -> None:
        if self.state in (State.HELD, State.FALLING):
            return
        name = self._pick(CLICK_POOL)
        if name is None:
            return
        self._recent = (getattr(self, "_recent", []) + [name])[-3:]
        self.enter(State.ACTING, name,
                   on_done=lambda: self.enter(State.IDLE, "idle", loops=anim.FOREVER))

    def random_action(self) -> None:
        self.interact()
        self._play_click_action()

    def sleep_now(self) -> None:
        self.enter(State.ASLEEP, "asleep", loops=anim.FOREVER)
        self.show_text("呼……好困。", speak=False)

    def next_line(self, schedule: bool = True) -> None:
        self._reload_lines()
        if schedule:
            self.interact()
            self.clicks += 1
            self._schedule_reset()
        self.show_text(self._pick_line())

    def _pick_line(self) -> str:
        """优先说"当前动作专属"的台词，这样台词和动作对得上。"""
        name = self.player.name
        if name and name in self.action_lines:
            pool = self.action_lines[name]
            line = pool[self.action_line_index % len(pool)]
            self.action_line_index += 1
            return line
        pool = self.lines or list(DEFAULT_LINES)
        line = pool[self.line_index % len(pool)]
        self.line_index += 1
        return line

    def _idle_hint(self) -> str:
        first = self.lines[0] if self.lines and self.lines != DEFAULT_LINES else "点我一下嘛～"
        note = self.lines_note or f"共 {len(self.lines)} 句台词"
        return f"{first}\n（{note}，先点我看余额）"

    # ------------------------------------------------------------------ 计时器

    def _schedule_reset(self) -> None:
        seconds = float(self.cfg.get("click_reset_seconds", 10) or 0)
        if seconds <= 0:
            return
        if self.reset_job:
            try:
                self.root.after_cancel(self.reset_job)
            except Exception:
                pass
        self.reset_job = self.root.after(int(seconds * 1000), self._idle_reset)

    def _idle_reset(self) -> None:
        self.clicks = 0
        self.active = False
        self.reset_job = None

    def reset_clicks(self) -> None:
        self.clicks = 0
        self.active = False
        self.show_text(self._idle_hint(), speak=False, keep_active=False)

    def _text_mtime(self) -> float:
        try:
            return os.path.getmtime(config_mod.text_path(self.cfg))
        except OSError:
            return 0.0

    def _reload_lines(self) -> None:
        mtime = self._text_mtime()
        if mtime and mtime != self.lines_mtime:
            self.lines, self.lines_note, self.action_lines = config_mod.load_lines(
                config_mod.text_path(self.cfg))
            self.lines_mtime = mtime

    # ------------------------------------------------------------------ 余额

    def _fetch_balance(self) -> None:
        self.show_text(FETCH_TEXT)
        self.fetching = True
        key, source = net.resolve_key(self.cfg)
        threading.Thread(target=self._balance_worker, args=(key,), daemon=True).start()

    def _balance_worker(self, key: str) -> None:
        try:
            ok, message, fields = net.fetch_balance(key)
        except Exception as exc:
            ok, message, fields = False, f"❌ 查询出错：{exc}", {}
        self.results.put(("balance", ok, message, fields))

    def _show_balance(self, ok: bool, message: str, fields: dict) -> None:
        self.fetching = False
        if ok:
            self.show_text(render_balance(self.cfg.get("balance_template", ""), fields))
            if self.state == State.IDLE and self.cache.is_ready("cheer"):
                self.enter(State.EMOTE, "cheer",
                           on_done=lambda: self.enter(State.IDLE, "idle",
                                                      loops=anim.FOREVER))
        else:
            self.show_text(message)
            if self.state == State.IDLE and self.cache.is_ready("gasp"):
                self.enter(State.EMOTE, "gasp",
                           on_done=lambda: self.enter(State.IDLE, "idle",
                                                      loops=anim.FOREVER))

    # ------------------------------------------------------------------ 视线 / 物理

    def _gaze_step(self) -> None:
        if self.state != State.IDLE or not self.cfg.get("gaze", True):
            return
        mx, my = cursor_pos()
        if mx < -9000:
            return
        head_x = self.root.winfo_x() + self.body_origin[0] + self.body_w / 2
        head_y = self.root.winfo_y() + self.body_origin[1] + self.floor_y - self.content_h * 0.78
        dx = mx - head_x
        dy = my - head_y
        dead_x = GAZE_DEAD_X * self.dpr
        dead_y = GAZE_DEAD_Y * self.dpr
        if abs(dx) > dead_x:
            want = "gaze_left" if dx < 0 else "gaze_right"
        elif dy < -dead_y:
            want = "gaze_up"
        else:
            want = "idle"
        if want == self.gaze_target:
            return
        now = time.perf_counter()
        if now - self.gaze_since < GAZE_DWELL:
            return
        if not self.cache.is_ready(want):
            self.cache.request([want])
            return
        if self.enter(State.IDLE, want, loops=anim.FOREVER, fade=5):
            self.gaze_target = want
            self.gaze_since = now

    def _physics_step(self, dt: float) -> None:
        # 身体摆动（钟摆）：弹簧回中
        if abs(self.sway) > 0.01 or abs(self.sway_v) > 0.01:
            self.sway_v += (-SWAY_K * self.sway - SWAY_C * self.sway_v) * dt
            self.sway = max(-SWAY_MAX, min(SWAY_MAX, self.sway + self.sway_v * dt))

        # 地面按**脚的位置**算，不按窗口底边 ——
        # 身体区比角色高（要给"被抓/下落"的悬空姿势留地方），
        # 用窗口底边当地面会让角色永远悬在半空。
        ground = self.ground_window_y()

        if self.state == State.FALLING:
            self.fall_v = min(FALL_MAX, self.fall_v + GRAVITY * dt)
            y = self.root.winfo_y() + self.fall_v * dt
            if y >= ground:
                self.root.geometry(f"+{self.root.winfo_x()}+{int(ground)}")
                self.fall_v = 0.0
                self.enter(State.LANDING, "landing",
                           on_done=lambda: self.enter(State.IDLE, "idle",
                                                      loops=anim.FOREVER))
            else:
                self.root.geometry(f"+{self.root.winfo_x()}+{int(y)}")

        # 影子随高度变化
        height = max(0.0, ground - self.root.winfo_y())
        target = max(0.25, 1.0 - height / (260.0 * self.dpr))
        if abs(target - self.shadow_scale) > 0.02:
            self.shadow_scale = target
            self.shadows.clear()
            self.canvas.delete("shadow")
            self._draw_shadow()
            self.canvas.tag_lower("shadow")

    def _auto_step(self) -> None:
        if self.state not in (State.IDLE, State.EMOTE):
            return
        idle_for = time.perf_counter() - self.last_interaction
        sleep_after = float(self.cfg.get("auto_sleep_seconds", 90) or 0)
        emote_after = float(self.cfg.get("auto_emote_seconds", 45) or 0)
        if sleep_after and idle_for > sleep_after and self.state == State.IDLE:
            if self.enter(State.ASLEEP, "asleep", loops=anim.FOREVER):
                self.show_text("呼……好困。", speak=False)
        elif (emote_after and idle_for > emote_after and self.state == State.IDLE
              and time.perf_counter() - getattr(self, "_last_emote", 0) > emote_after):
            name = self._pick(EMOTE_POOL)
            if name:
                self._last_emote = time.perf_counter()
                self.enter(State.EMOTE, name,
                           on_done=lambda: self.enter(State.IDLE, "idle",
                                                      loops=anim.FOREVER))

    # ------------------------------------------------------------------ 主循环

    def keep_front(self) -> None:
        now = time.perf_counter()
        if now - self.last_z > 20:
            self.last_z = now
            try:
                self.root.lift()
                if self.topmost:
                    self.root.attributes("-topmost", True)
            except tk.TclError:
                pass

    def tick(self) -> None:
        # 1) 网络线程的结果
        while True:
            try:
                kind, ok, message, fields = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "balance":
                self._show_balance(ok, message, fields)
            elif kind == "test":
                self._on_test_result(ok, message, fields)

        # 2) 预热缓存：每轮只转几帧
        self.cache.pump(self._make_photo)

        # 3) 头像动画（和 idle 同步眨眼）
        if getattr(self, "avatar_pil", None) and self.avatar_photo is None:
            # 一次把 56 张头像全转好：头像才 84x84，56 张一共 1.6MB，
            # 但每帧现转一张（~7ms × 24fps）会白吃掉一大截单核 CPU。
            self.avatar_photos = [ImageTk.PhotoImage(p) for p in self.avatar_pil]
            self.avatar_photo = self.avatar_photos[0]
            self._build_avatar_timeline()
            self._avatar_t0 = time.perf_counter()
            self.show_text(self.current_text, speak=False)   # 头像到位了，重画一次
        if self.avatar_timeline and self.player.name != "idle":
            # 只在"没在放 idle"时自己转，避免两套节奏打架
            photo = self._avatar_step(time.perf_counter() - self._avatar_t0)
            if photo is not None and photo is not self.avatar_photo:
                self.avatar_photo = photo
                item = self._avatar_item()
                if item is not None:
                    self.canvas.itemconfigure(item, image=photo)

        # 4) 状态机 / 视线 / 物理
        dt = min(0.1, max(0.0, time.perf_counter() - getattr(self, "_last_tick",
                                                            time.perf_counter())))
        self._last_tick = time.perf_counter()
        # 兜底：万一画面上什么都没在播（预热还没好、或刚被作废），
        # 等 idle 热好就补上，不会留下一片空白
        if not self.player.active and self.state == State.IDLE and \
                self.cache.is_ready("idle"):
            self.enter(State.IDLE, "idle", loops=anim.FOREVER, fade=0)
        self._gaze_step()
        self._physics_step(dt)
        self._auto_step()

        self.keep_front()
        self.root.after(TICK_MS, self.tick)

    # ------------------------------------------------------------------ 菜单动作

    def toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.cfg["always_on_top"] = self.topmost
        try:
            self.root.attributes("-topmost", self.topmost)
        except tk.TclError:
            pass
        self._save_cfg()

    def open_text_file(self) -> None:
        self._open_path(config_mod.text_path(self.cfg), config_mod.DEFAULT_TEXT and
                        "# 一行一句，# 开头是注释\n点我一下嘛～\n")

    def open_config_file(self) -> None:
        self._open_path(config_mod.CONFIG_PATH, None)

    def _open_path(self, path: str, seed: str | None) -> None:
        if not os.path.isfile(path) and seed is not None:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(seed)
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"无法创建文件：\n{exc}")
                return
        try:
            os.startfile(path)          # noqa: S606 (Windows)
        except Exception:
            messagebox.showinfo(APP_TITLE, f"文件位置：\n{path}")

    def open_settings(self) -> None:
        from .settings_win import SettingsDialog
        SettingsDialog(self)

    def _on_test_result(self, ok: bool, message: str, fields: dict) -> None:
        label = getattr(self, "test_label", None)
        if label is None:
            return
        try:
            if ok:
                label.configure(text="✅ 连接成功：" +
                                     render_balance("{total_balance} {currency}", fields),
                                fg="#1b7a3d")
            else:
                label.configure(text="⚠️ " + message.replace("\n", " "), fg="#b02a2a")
        except tk.TclError:
            pass

    def _announce(self) -> None:
        if not str(self.cfg.get("api_key", "")).startswith("sk-") and \
                not net.resolve_key(self.cfg)[0]:
            self.show_text("第一次用的话，右键我 → 设置，\n填上 DeepSeek API Key 就能查余额啦～",
                           speak=False, keep_active=False)

    def _save_cfg(self) -> None:
        try:
            config_mod.save(self.cfg)
        except Exception as exc:
            log(f"[config] 保存失败：{exc}")

    def quit_app(self) -> None:
        self.cfg["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        self._save_cfg()
        self.cache.shut()
        anim.lower_timer_resolution()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
