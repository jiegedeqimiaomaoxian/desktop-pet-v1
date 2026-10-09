# -*- coding: utf-8 -*-
"""截正在运行的桌宠窗口 —— 用**屏幕 DC** 抓，拿到的是真实合成结果。

为什么不 Use PrintWindow：桌宠是分层窗口（`-transparentcolor`），
PrintWindow 抓到的是"窗口自己的画布"，透明处是**黑色**，
看起来像角色贴在一块黑板上，没法判断桌面上的真实观感。
从屏幕 DC 抓就是用户眼睛看到的东西（包括背后的桌面）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import time

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.join(ROOT, "assets", "source", "shots")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

#: ⚠️ 不要在 import 时调 SetProcessDPIAware()。
#: 那样会让"顺手 import 了本模块"的进程（比如 verify_v2.py）在创建 Tk 之前
#: 就变成 DPI 感知，屏幕尺寸从 1536x864 变成 1920x1080，桌宠布局整体差一个比例。
#: 谁需要谁在**自己启动时**显式调；验证脚本里由 Pet 自己负责。
_DPI_READY = False


def ensure_dpi_aware() -> None:
    global _DPI_READY
    if _DPI_READY:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    _DPI_READY = True


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG), ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD), ("biClrImportant", ctypes.wintypes.DWORD),
    ]


def grab_rect(x: int, y: int, w: int, h: int) -> Image.Image:
    """从屏幕 DC 抓一块矩形（真实合成像素）。"""
    ensure_dpi_aware()          # 不感知 DPI 的话拿到的是被缩放过的虚拟坐标，会截歪
    screen = user32.GetDC(0)
    memdc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(memdc, bmp)
    gdi32.BitBlt(memdc, 0, 0, w, h, screen, x, y, 0x00CC0020)      # SRCCOPY
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(0, screen)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def find_window(title_part: str = "深海小女仆") -> int | None:
    """按标题找窗口（桌宠没有标题栏，但窗口文本还在）。"""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        if title_part in buff.value:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def grab_window(hwnd: int, margin: int = 24) -> Image.Image:
    """抓窗口四周留一点边（能看到角色和桌面的对比）。"""
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    x = max(0, rect.left - margin)
    y = max(0, rect.top - margin)
    w = (rect.right - rect.left) + margin * 2
    h = (rect.bottom - rect.top) + margin * 2
    return grab_rect(x, y, w, h)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    # 必须赶在**任何**窗口/坐标 API 之前调，否则 GetWindowRect 给的是
    # 被系统缩放过的虚拟坐标（1920 宽的屏会报成 1536），截出来就是歪的、缺一块
    ensure_dpi_aware()
    title = sys.argv[1] if len(sys.argv) > 1 else "深海小女仆"
    name = sys.argv[2] if len(sys.argv) > 2 else "live"
    hwnd = find_window(title)
    if not hwnd:
        print(f"没找到标题含「{title}」的可见窗口")
        return 1
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    img = grab_window(hwnd)
    path = os.path.join(OUT, f"{name}.png")
    img.save(path)
    print(f"窗口 {rect.left},{rect.top} {rect.right-rect.left}x{rect.bottom-rect.top}"
          f"  ->  {os.path.relpath(path, ROOT)}  ({img.width}x{img.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
