# -*- coding: utf-8 -*-
"""诊断"点击之后定位不准 / 卡顿"。

量的两件事：
  定位  —— 角色**身体**（内容包围盒，不是那张带透明留白的方图）在**屏幕**上的
           四条边。用户看到的是这个；按帧的左上角量会被"每个片段的留白不一样"
           干扰，量出来的位移是假的。
  卡顿  —— 真实帧间隔 + 点击过程中每一次几何变化 + on_click 各阶段耗时。

用法：
    python tools\\diagnose_click.py
    python tools\\diagnose_click.py --rounds 5
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pet import anim                      # noqa: E402
from pet import app as app_mod            # noqa: E402


def pump(pet, seconds: float) -> None:
    end = time.perf_counter() + max(0.0, seconds)
    while time.perf_counter() < end:
        pet.root.update()
        time.sleep(0.002)


def content_screen_box(pet):
    """角色**身体**在屏幕上的包围盒 (x0, y0, x1, y1)。

    帧是带透明留白的方图，各片段留白不同；直接量帧的左上角会得出假的位移。
    这里按当前片段的内容包围盒换算成屏幕坐标 —— 才是用户看到的位置。
    """
    if pet.body_display is None or pet.player.name is None:
        return None
    clip = pet.clips.get(pet.player.name)
    if clip is None:
        return None
    _, cx, cy = pet.body_display            # 帧左上角的画布坐标
    scale = pet._clip_scale(clip)
    bx0, by0, bx1, by1 = clip.content_box()
    wx, wy = pet.root.winfo_x(), pet.root.winfo_y()
    return (wx + cx + bx0 * scale, wy + cy + by0 * scale,
            wx + cx + bx1 * scale, wy + cy + by1 * scale)


class _BIH(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG), ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD), ("biClrImportant", ctypes.wintypes.DWORD),
    ]


def grab_window_lum(hwnd: int):
    """抓窗口自己的画布亮度（透明处是**黑**，角色和气泡是亮的）。"""
    import numpy as np
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)
    info = _BIH()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].astype(int).sum(axis=2)


def character_box(pet):
    """从**真实截图像素**里量角色（气泡以下、非黑的像素）。

    这是唯一能抓住"过渡帧画错位置"的量法：按播放器回调里的坐标量，
    正片帧和过渡帧用的是两套坐标系，两边各自看都自洽 ——
    只有看屏幕上的像素，才发现角色在过渡那 0.25 秒里往下跳了 175px。
    """
    import numpy as np
    lum = grab_window_lum(pet.root.winfo_id())
    # 从**身体区顶端**往下量：气泡（和它的小尾巴）在那之上，不排除掉会把
    # 气泡的亮像素也当成角色，量出来的包围盒永远是整个窗口。
    top = int(pet.body_origin[1]) + 2
    band = lum[top:, :]
    mask = band > 60
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return (int(cols[0]), int(rows[0]) + top, int(cols[-1]), int(rows[-1]) + top)


def trace_screen(pet, seconds: float = 0.9, hz: float = 12.0) -> tuple:
    """点一次，用截图盯着**屏幕上**角色的位置变化。"""
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    pet.clicks = 0
    pump(pet, 0.5)
    base = character_box(pet)
    samples = []
    pet.on_click()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pet.root.update()
        box = character_box(pet)
        if box:
            samples.append((time.perf_counter(), box))
        time.sleep(1.0 / hz)
    return base, samples


def main() -> int:
    ap = argparse.ArgumentParser(description="诊断点击后的定位与卡顿")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--screen", action="store_true",
                    help="额外做一次「截图轨迹」：点一次，用真截图盯住角色的位置")
    args = ap.parse_args()

    pet = app_mod.Pet()
    print("[diag] 等待预热…")
    end = time.perf_counter() + 300
    while time.perf_counter() < end and len(pet.cache.done) < len(pet.clips):
        pet.root.update()
        time.sleep(0.004)
    print(f"[diag] 预热 {len(pet.cache.ready)}/{len(pet.clips)}"
          f"  画布 {pet.body_w}x{pet.body_h}  窗口 {pet.win_w}x{pet.win_h}\n")

    geo_log: list[tuple[float, str]] = []
    orig_apply = pet._apply_window

    def apply_spy(geom):
        before = (pet.win_w, pet.win_h, pet.body_origin)
        t = time.perf_counter()
        orig_apply(geom)
        after = (pet.win_w, pet.win_h, pet.body_origin)
        if before != after:
            geo_log.append((t, f"窗口 {before[0]}x{before[1]} -> {after[0]}x{after[1]}"
                               f"   body_y {before[2][1]:.1f} -> {after[2][1]:.1f}"
                               f"   body_x {before[2][0]:.1f} -> {after[2][0]:.1f}"))

    pet._apply_window = apply_spy

    for r in range(args.rounds):
        pet.player.cancel()
        pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
        pet.clicks = 0
        pump(pet, 0.7)

        base = content_screen_box(pet)
        geo_log.clear()
        frames: list[tuple[float, tuple]] = []
        orig_draw = pet.player.draw

        def draw_spy(photo, x, y, _f=frames, _o=orig_draw):
            r_ = _o(photo, x, y)
            # 只统计**正片**帧。过渡帧是一张"两个片段的并集画布"，
            # 落点和片段自己的内容框对不上，拿它算位置会得出假的位移。
            if pet.player.index >= 0:
                _f.append((time.perf_counter(), content_screen_box(pet)))
            return r_

        pet.player.draw = draw_spy
        try:
            pet.on_click()
            pump(pet, 3.4)
        finally:
            pet.player.draw = orig_draw

        if base is None or not frames:
            print(f"[{r+1}] 没采到数据")
            continue
        boxes = [b for _, b in frames if b]
        gaps = [(frames[i][0] - frames[i - 1][0]) * 1000.0 for i in range(1, len(frames))]
        cx0 = (base[0] + base[2]) / 2
        cy1 = base[3]
        dxs = [((b[0] + b[2]) / 2 - cx0) for b in boxes]
        dys = [(b[3] - cy1) for b in boxes]
        print(f"[{r+1}] 点击前身体：中线x={cx0:.0f}  底边y={cy1:.0f}  "
              f"宽={base[2]-base[0]:.0f} 高={base[3]-base[1]:.0f}")
        print(f"     点击后：中线偏移 {min(dxs):+.0f} ~ {max(dxs):+.0f}px"
              f"（极差 {max(dxs)-min(dxs):.0f}）   "
              f"底边偏移 {min(dys):+.0f} ~ {max(dys):+.0f}px"
              f"（极差 {max(dys)-min(dys):.0f}）")
        print(f"     帧数 {len(frames)}  间隔 均{statistics.fmean(gaps):.1f}ms "
              f"标准差{statistics.pstdev(gaps):.1f}ms 最长{max(gaps):.0f}ms "
              f"（>2×理想的有 {sum(1 for g in gaps if g > 83)} 次）")
        if geo_log:
            print(f"     点击过程中 {len(geo_log)} 次几何变化：")
            for i, (t, text) in enumerate(geo_log):
                delta = ((t - geo_log[i - 1][0]) if i else (t - frames[0][0])) * 1000
                print(f"       +{delta:6.0f}ms  {text}")
        else:
            print("     点击过程中没有几何变化")

    # --- on_click 各阶段耗时 ---
    # --- 截图轨迹（唯一能抓住"过渡帧画错位置"的量法）---
    if args.screen:
        print("\n" + "=" * 70)
        print("截图轨迹：点一次，用真截图盯住角色的位置（含过渡帧）")
        print("=" * 70)
        base, samples = trace_screen(pet)
        if not base or len(samples) < 4:
            print("  没采到足够样本")
        else:
            by0, by1 = base[1], base[3]
            dys = [b[1] - by0 for _, b in samples]
            dh = [(b[3] - b[1]) - (by1 - by0) for _, b in samples]
            t0 = samples[0][0]
            print(f"  基准：顶边 y={by0}  底边 y={by1}  高={by1-by0}"
                  f"  （窗口内坐标，气泡以下）")
            print(f"  采样 {len(samples)} 次：顶边偏移 {min(dys):+d} ~ {max(dys):+d}px"
                  f"（极差 {max(dys)-min(dys)}）   高度变化 {min(dh):+d} ~ {max(dh):+d}px")
            worst = max(range(len(dys)), key=lambda i: abs(dys[i]))
            print(f"  最大偏移出现在 +{(samples[worst][0]-t0)*1000:.0f}ms："
                  f"顶边 {dys[worst]:+d}px")
            print("  " + ("✅ 点击过程中角色没有上下跳"
                          if max(dys) - min(dys) <= 8 else
                          "❌ 角色跳了（很可能是过渡帧的坐标系不一致）"))

    # --- on_click 各阶段耗时 ---
    print("\n" + "=" * 70)
    print("on_click 各阶段耗时")
    print("=" * 70)
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    pet.clicks = 0
    pump(pet, 0.5)

    marks: list[tuple[str, float]] = []
    originals = {}

    def wrap(obj, name, tag):
        originals[(obj, name)] = getattr(obj, name)

        def spy(*a, **kw):
            t = time.perf_counter()
            r = originals[(obj, name)](*a, **kw)
            marks.append((tag, (time.perf_counter() - t) * 1000))
            return r
        setattr(obj, name, spy)

    wrap(pet, "_play_click_action", "进入动作（含过渡帧合成）")
    wrap(pet, "_fetch_balance", "发起余额查询")
    wrap(pet, "show_text", "重画气泡 + 窗口几何")
    wrap(pet, "_pose", "读一帧 + 缩放（过渡用）")
    t0 = time.perf_counter()
    pet.on_click()
    total = (time.perf_counter() - t0) * 1000
    for obj, name in originals:
        setattr(obj, name, originals[(obj, name)])
    for tag, ms in marks:
        print(f"  {ms:8.1f} ms   {tag}")
    print(f"  {total:8.1f} ms   on_click 总计（同步部分）")

    pet.quit_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
