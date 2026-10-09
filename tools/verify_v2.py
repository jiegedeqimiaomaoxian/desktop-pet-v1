# -*- coding: utf-8 -*-
"""桌宠 v2 实测：帧间隔 / 点击响应 / 状态切换 / 视线跟随 / 拖拽物理 / 落地。

量的都是**用户真正会经历的那条路**：
  · 帧间隔   —— 直接盯 `player.draw` 的调用时间戳（不是估算，是实测）
  · 点击响应 —— 从 `on_click()` 到画面第一次变化
  · 视线     —— 用 `SetCursorPos` 真的把鼠标挪过去，看片段有没有换
  · 拖拽     —— 造真的按下/拖动/松开事件，看窗口跟不跟、掉不掉、落没落地

用法：
    python tools\\verify_v2.py               全部测
    python tools\\verify_v2.py --quick       只测帧间隔和点击响应
"""

from __future__ import annotations

import argparse
import ctypes
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pet import anim                       # noqa: E402
from pet import app as app_mod             # noqa: E402
import shot as shot_mod                    # noqa: E402

SHOTS = os.path.join(ROOT, "assets", "source", "shots")
GOOD_JITTER_MS = 8.0


# --------------------------------------------------------------------------- 事件替身

class FakeEvent:
    """假的鼠标事件（够 on_press/on_drag/on_release 用）。"""

    def __init__(self, x: int, y: int, x_root: int, y_root: int) -> None:
        self.x, self.y = x, y
        self.x_root, self.y_root = x_root, y_root


def pump(pet, seconds: float) -> None:
    end = time.perf_counter() + max(0.0, seconds)
    while time.perf_counter() < end:
        pet.root.update()
        time.sleep(0.002)


def wait_for(pet, predicate, timeout: float, label: str = "") -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return True
        pet.root.update()
        time.sleep(0.01)
    if label:
        print(f"    ⏱ 等超时：{label}")
    return False


# --------------------------------------------------------------------------- 各项实测

def measure_clip(pet, name: str, seconds: float = 2.9) -> dict:
    """播一个片段，量真实帧间隔。"""
    if not pet.cache.is_ready(name):
        return {"name": name, "skip": "没预热好"}
    clip = pet.clips[name]
    pet.player.cancel()
    pet.state = app_mod.State.IDLE
    if not pet.enter(app_mod.State.ACTING, name, loops=anim.FOREVER, fade=0):
        return {"name": name, "skip": "进不去"}

    stamps: list[float] = []
    last = [None]
    original = pet.player.draw

    def spy(photo, x, y):
        key = pet.canvas.itemcget(pet._body_item(), "image") if pet._body_item() else id(photo)
        tag = f"{key}@{round(x, 1)},{round(y, 1)}"
        if tag != last[0]:
            last[0] = tag
            stamps.append(time.perf_counter())
        return original(photo, x, y)

    pet.player.draw = spy
    try:
        pump(pet, seconds)
    finally:
        pet.player.draw = original

    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)

    if len(stamps) < 4:
        return {"name": name, "skip": f"只画出 {len(stamps)} 帧"}
    gaps = [(stamps[i] - stamps[i - 1]) * 1000.0 for i in range(1, len(stamps))]
    ideal = 1000.0 / clip.fps
    return {
        "name": name, "frames": len(clip.files), "fps": clip.fps, "drawn": len(stamps),
        "mean": statistics.fmean(gaps), "std": statistics.pstdev(gaps),
        "min": min(gaps), "max": max(gaps), "ideal": ideal,
        "stalls": sum(1 for g in gaps if g > ideal * 2),
        "gaps": gaps,
    }


def measure_click(pet, rounds: int = 4) -> dict:
    """真实点击路径：on_click() -> 画面第一次变化。"""
    lags = []
    for _ in range(rounds):
        pet.player.cancel()
        pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
        pet.clicks = 0
        pump(pet, 0.25)
        marks: list[float] = []
        original = pet.player.draw

        def spy(photo, x, y, _m=marks, _o=original):
            _m.append(time.perf_counter())
            return _o(photo, x, y)

        pet.player.draw = spy
        try:
            t0 = time.perf_counter()
            pet.on_click()
            pump(pet, 0.6)
        finally:
            pet.player.draw = original
        if marks:
            lags.append((marks[0] - t0) * 1000.0)
    return {"lags": lags, "mean": statistics.fmean(lags) if lags else None,
            "max": max(lags) if lags else None}


def test_states(pet) -> list[tuple[str, str, bool]]:
    """逐个状态切一遍：换没换、卡没卡。"""
    out = []
    plan = [("待机", app_mod.State.IDLE, "idle", anim.FOREVER),
            ("看向左", app_mod.State.IDLE, "gaze_left", anim.FOREVER),
            ("看向右", app_mod.State.IDLE, "gaze_right", anim.FOREVER),
            ("抬头", app_mod.State.IDLE, "gaze_up", anim.FOREVER),
            ("被抓", app_mod.State.HELD, "held", anim.FOREVER),
            ("下落", app_mod.State.FALLING, "falling", anim.FOREVER),
            ("睡着", app_mod.State.ASLEEP, "asleep", anim.FOREVER),
            ("开心", app_mod.State.EMOTE, "cheer", 1),
            ("害羞", app_mod.State.EMOTE, "shy", 1),
            ("吓一跳", app_mod.State.EMOTE, "gasp", 1),
            ("惊醒", app_mod.State.WAKING, "waking", 1),
            ("落地", app_mod.State.LANDING, "landing", 1)]
    for label, state, clip, loops in plan:
        if clip not in pet.clips:
            out.append((label, clip, None))
            continue
        if not pet.cache.is_ready(clip):
            out.append((label, clip, None))
            continue
        worst = [0.0]
        original = pet.player.draw
        last = [time.perf_counter()]

        def spy(photo, x, y, _w=worst, _l=last, _o=original):
            now = time.perf_counter()
            _w[0] = max(_w[0], (now - _l[0]) * 1000.0)
            _l[0] = now
            return _o(photo, x, y)

        pet.player.draw = spy
        try:
            ok = pet.enter(state, clip, loops=loops, fade=app_mod.XFADE)
            pump(pet, 1.2)
        finally:
            pet.player.draw = original
        # 下落/落地/惊醒是**有后续**的：落地 -> 回待机。所以不能只认"还在播那个片段"。
        expected = {app_mod.State.FALLING: (app_mod.State.LANDING, app_mod.State.IDLE),
                    app_mod.State.LANDING: (app_mod.State.IDLE,),
                    app_mod.State.WAKING: (app_mod.State.IDLE,)}.get(state, ())
        clip_ok = (pet.player.name == clip or pet.state == app_mod.State.IDLE
                   or pet.state in expected)
        out.append((label, clip, bool(ok and clip_ok), worst[0]))
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    return out


def test_gaze(pet) -> list[tuple[str, str, bool]]:
    """真的移动鼠标，看视线跟不跟。"""
    results = []
    user32 = ctypes.windll.user32
    origin = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(origin))

    # 先把她挪回屏幕中间再测：她要是停在屏幕边上，鼠标根本到不了那一侧，
    # 测出来的"没跟"是测试环境的问题，不是程序的问题（踩过这个坑）
    area = app_mod.work_area(pet.root)
    mid_x = int(area[0] + (area[2] - area[0]) / 2 - pet.body_origin[0] - pet.body_w / 2)
    pet.root.geometry(f"+{mid_x}+{pet.root.winfo_y()}")
    pet.root.update()
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    pet.gaze_target = "idle"
    pump(pet, 0.4)

    win_x, win_y = pet.root.winfo_x(), pet.root.winfo_y()
    head_x = win_x + pet.body_origin[0] + pet.body_w / 2
    head_y = win_y + pet.body_origin[1] + pet.floor_y - pet.content_h * 0.78

    for label, want, tx, ty in (
            ("鼠标在左边", "gaze_left", int(head_x - 300), int(head_y)),
            ("鼠标在右边", "gaze_right", int(head_x + 300), int(head_y)),
            ("鼠标在上方", "gaze_up", int(head_x), int(head_y - 300)),
            ("鼠标在正前", "idle", int(head_x), int(head_y + 200))):
        if not pet.cache.is_ready(want):
            results.append((label, want, None))
            continue
        # 先把视线复位，确保能看到"切换"这件事
        pet.enter(app_mod.State.IDLE, "idle" if want != "idle" else "gaze_left",
                  loops=anim.FOREVER, fade=0)
        pet.gaze_target = "idle" if want != "idle" else "gaze_left"
        pet.gaze_since = 0.0
        user32.SetCursorPos(max(0, tx), max(0, ty))
        pump(pet, 0.9)
        results.append((label, want, pet.player.name == want or pet.gaze_target == want))
    user32.SetCursorPos(origin.x, origin.y)
    return results


def test_physics(pet) -> list[tuple[str, str, bool]]:
    """造真的按下/拖动/松手事件，看窗口跟不跟、掉不掉、落没落地。"""
    out = []
    if not (pet.cache.is_ready("held") and pet.cache.is_ready("falling")):
        return [("拖拽", "held/falling", None), ("下落落地", "landing", None)]

    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    pump(pet, 0.2)

    start_x, start_y = pet.root.winfo_x(), pet.root.winfo_y()
    grab_x = start_x + int(pet.body_origin[0] + pet.body_w / 2)
    grab_y = start_y + int(pet.body_origin[1] + pet.floor_y - pet.content_h * 0.5)

    pet.on_press(FakeEvent(grab_x - start_x, grab_y - start_y, grab_x, grab_y))
    for i in range(1, 9):
        nx, ny = grab_x + i * 14, grab_y - i * 9
        pet.on_drag(FakeEvent(nx - pet.root.winfo_x(), ny - pet.root.winfo_y(), nx, ny))
        pump(pet, 0.03)
    held_ok = pet.state == app_mod.State.HELD
    moved = (pet.root.winfo_x(), pet.root.winfo_y()) != (start_x, start_y)
    out.append(("拖拽跟随", f"状态={pet.state.value} 位移={moved}", bool(held_ok and moved)))

    pet.on_release(FakeEvent(0, 0, grab_x + 112, grab_y - 72))
    pump(pet, 0.15)
    falling_ok = pet.state in (app_mod.State.FALLING, app_mod.State.LANDING)
    landed = wait_for(pet, lambda: pet.state in (app_mod.State.LANDING,
                                                 app_mod.State.IDLE), 8.0, "落地")
    ground = app_mod.work_area(pet.root)[3] - app_mod.BOTTOM_MARGIN
    feet = pet.root.winfo_y() + pet.body_origin[1] + pet.floor_y
    out.append(("松手下落", f"进入下落={falling_ok}", bool(falling_ok)))
    out.append(("落地", f"脚部 y={feet:.0f} 地面 {ground} 差 {abs(feet-ground):.0f}px",
                bool(landed and abs(feet - ground) <= 6)))
    pump(pet, 2.0)
    return out


def test_hit(pet) -> list[tuple[str, str, bool]]:
    """点击命中精度 + 切片段时脚底漂不漂。

    这是"定位准不准"的另一半 —— 位置对但点不中，用户一样觉得"点不准"。
    """
    out = []
    grid = getattr(pet, "_hit_grid", None)
    if not grid:
        return [("命中网格", "还没建好", None)]
    ox, oy = pet.body_origin
    step = app_mod.HIT_STEP

    cells = list(grid)
    sample_in = cells[::max(1, len(cells) // 200)][:200]
    inside_ok = sum(1 for gx, gy in sample_in
                    if pet.hit_body(int(ox + gx * step + step / 2),
                                    int(oy + gy * step + step / 2)))
    out.append((f"身上 {len(sample_in)} 点应命中", f"{inside_ok}/{len(sample_in)}",
                inside_ok == len(sample_in)))

    outside_bad = sampled = 0
    for gy in range(0, pet.body_h, step * 3):
        for gx in range(0, pet.body_w, step * 3):
            if (gx // step, gy // step) in grid:
                continue
            if sampled >= 200:
                break
            sampled += 1
            if pet.hit_body(int(ox + gx), int(oy + gy)):
                outside_bad += 1
        if sampled >= 200:
            break
    out.append((f"身外 {sampled} 点应不命中", f"误判 {outside_bad}", outside_bad == 0))

    bx0, by0, bx1, by1 = pet.bubble_box
    mid = (int((bx0 + bx1) / 2), int((by0 + by1) / 2))
    out.append(("气泡中心可点", f"({mid[0]}, {mid[1]})", bool(pet.hit_bubble(*mid))))

    # 切片段时"脚底那条线"在屏幕上不能动
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    pump(pet, 0.4)
    base = None
    drift = 0.0
    for name in ("idle", "gaze_left", "gaze_right", "act_wave", "cheer", "shy", "gasp"):
        if name not in pet.clips or not pet.cache.is_ready(name):
            continue
        pet.enter(app_mod.State.IDLE, name, loops=anim.FOREVER, fade=0)
        pump(pet, 0.35)
        foot = pet.root.winfo_y() + pet.body_origin[1] + pet.floor_y
        base = foot if base is None else base
        drift = max(drift, abs(foot - base))
    out.append(("切片段时脚底不漂", f"最大 {drift:.0f}px", drift <= 1))
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    return out


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="桌宠 v2 实测")
    ap.add_argument("--quick", action="store_true", help="只测帧间隔和点击响应")
    ap.add_argument("--seconds", type=float, default=2.9, help="每个片段观察多久")
    args = ap.parse_args()

    os.makedirs(SHOTS, exist_ok=True)
    pet = app_mod.Pet()
    print(f"[verify] 片段 {len(pet.clips)} 个  画布 {pet.body_w}x{pet.body_h}"
          f"  内容高 {pet.content_h}  地面线 {pet.floor_y}  色键 {pet.key_color}")
    print(f"[verify] 等待预热…")
    wait_for(pet, lambda: len(pet.cache.done) >= len(pet.clips), 300.0, "全部预热")
    print(f"[verify] 预热 {len(pet.cache.ready)} 就绪 / {len(pet.cache.done)} 热过 / {len(pet.clips)} 总数\n")

    # --- 1. 帧间隔 ---
    print("=" * 74)
    print("① 片段播放的帧间隔（实测）")
    print("=" * 74)
    print(f"{'片段':<12}{'帧数':>5}{'fps':>5}{'均':>8}{'标准差':>8}{'最大':>8}"
          f"{'长停顿':>7}  判定")
    rows, bad = [], []
    order = ["idle", "gaze_left", "gaze_right", "gaze_up", "held", "falling",
             "asleep", "cheer", "shy", "gasp", "waking", "landing"]
    order += [n for n in sorted(pet.clips) if n not in order]
    for name in order:
        if name not in pet.clips:
            continue
        r = measure_clip(pet, name, args.seconds)
        if r.get("skip"):
            print(f"{name:<12}  ⏭ {r['skip']}")
            continue
        rows.append(r)
        verdict = "✅ 稳" if (r["std"] <= GOOD_JITTER_MS and not r["stalls"]) else "⚠️ 抖"
        if verdict.endswith("抖"):
            bad.append(name)
        print(f"{name:<12}{r['frames']:>5}{r['fps']:>5.0f}{r['mean']:>8.1f}"
              f"{r['std']:>8.1f}{r['max']:>8.1f}{r['stalls']:>7}  {verdict}")
    if rows:
        print(f"\n  合计：{len(rows)-len(bad)}/{len(rows)} 个片段帧间隔稳定"
              f"｜平均 {statistics.fmean(r['mean'] for r in rows):.1f}ms"
              f"｜平均抖动 {statistics.fmean(r['std'] for r in rows):.1f}ms")

    # --- 2. 点击响应 ---
    print()
    print("=" * 74)
    print("② 真实点击响应（on_click -> 画面第一次变化）")
    print("=" * 74)
    click = measure_click(pet)
    if click["mean"] is not None:
        print(f"  平均 {click['mean']:.0f}ms  最差 {click['max']:.0f}ms"
              f"   样本 {[f'{v:.0f}' for v in click['lags']]} ms")
        print("  " + ("✅ 远低于 120ms 的感知阈值" if click["max"] < 120
                      else "⚠️ 超过 120ms 会觉得点下去没反应"))

    if args.quick:
        shot_path = os.path.join(SHOTS, "v2_verify.png")
        pet.root.update()
        shot_mod.grab_window(pet.root.winfo_id()).save(shot_path)
        print(f"\n[verify] 截图 -> {os.path.relpath(shot_path, ROOT)}")
        pet.quit_app()
        return 0 if not bad else 1

    # --- 3. 状态切换 ---
    print()
    print("=" * 74)
    print("③ 状态切换（每个状态切一次，看换没换、卡没卡）")
    print("=" * 74)
    for row in test_states(pet):
        label, clip, ok = row[0], row[1], row[2]
        worst = row[3] if len(row) > 3 else None
        if ok is None:
            print(f"  {label:<8}{clip:<12} ⏭ 素材还没生成")
        else:
            extra = (f"  切换最长间隔 {worst:.0f}ms（含过渡帧，理想 42ms）" if worst else "")
            print(f"  {label:<8}{clip:<12} {'✅' if ok else '❌'}{extra}")

    # --- 4. 视线跟随 ---
    print()
    print("=" * 74)
    print("④ 鼠标视线跟随（真的移动鼠标）")
    print("=" * 74)
    for label, want, ok in test_gaze(pet):
        if ok is None:
            print(f"  {label:<12} -> {want:<12} ⏭ 素材还没生成")
        else:
            print(f"  {label:<12} -> {want:<12} {'✅' if ok else '❌'}")

    # --- 5. 拖拽物理 ---
    print()
    print("=" * 74)
    print("⑤ 拖拽物理（真的造按下/拖动/松手事件）")
    print("=" * 74)
    for label, detail, ok in test_physics(pet):
        if ok is None:
            print(f"  {label:<10} ⏭ {detail} 素材还没生成")
        else:
            print(f"  {label:<10} {detail:<34} {'✅' if ok else '❌'}")

    # --- 6. 点击命中 + 定位稳定性 ---
    print()
    print("=" * 74)
    print("⑥ 点击命中精度 + 切片段时的定位稳定性")
    print("=" * 74)
    for label, detail, ok in test_hit(pet):
        if ok is None:
            print(f"  {label:<22} ⏭ {detail}")
        else:
            print(f"  {label:<22} {detail:<20} {'✅' if ok else '❌'}")

    # --- 7. 截图 ---
    print()
    print("=" * 74)
    print("⑦ 各状态截图")
    print("=" * 74)
    pet.player.cancel()
    pet.enter(app_mod.State.IDLE, "idle", loops=anim.FOREVER, fade=0)
    for label, clip, state in (("idle", "idle", app_mod.State.IDLE),
                               ("sleep", "asleep", app_mod.State.ASLEEP),
                               ("held", "held", app_mod.State.HELD),
                               ("cheer", "cheer", app_mod.State.EMOTE)):
        if clip not in pet.clips or not pet.cache.is_ready(clip):
            continue
        pet.enter(state, clip, loops=anim.FOREVER if state != app_mod.State.EMOTE else 1,
                  fade=0)
        pump(pet, 0.5)
        path = os.path.join(SHOTS, f"v2_{label}.png")
        shot_mod.grab_window(pet.root.winfo_id()).save(path)
        print(f"  {label:<8} -> {os.path.relpath(path, ROOT)}")

    pet.quit_app()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
