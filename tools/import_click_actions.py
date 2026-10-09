# -*- coding: utf-8 -*-
"""把 v1 已经生成好的 9 个点击动作搬进 v2，改名为 `act_*`。

为什么不重新生成：它们本来就是**同一个参考图 + 同一个 seed**（20240918）
出的，和 v2 新生成的待机/视线/被抓是同一批画风。重新跑一遍要多花 30 分钟，
出来还是几乎一样的东西。

搬过来只做两件事：改目录名、改 `action.json` 里的 `name` / `frames_dir`。
帧图一个字节都不动。

用法：
    python tools\\import_click_actions.py [--from ..\\desktop-pet\\assets\\actions]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SRC = os.path.join(os.path.dirname(ROOT), "desktop-pet", "assets", "actions")
DEST = os.path.join(ROOT, "assets", "actions")

#: v1 的前缀 → v2 的片段名
PAIRS = [
    ("2dh_bob", "act_bob"), ("2dh_wave", "act_wave"), ("2dh_tilt", "act_tilt"),
    ("2dh_spin", "act_spin"), ("2dh_squat", "act_squat"), ("2dh_nod", "act_nod"),
    ("2dh_jump", "act_jump"), ("2dh_sway", "act_sway"), ("2dh_sleep", "act_doze"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="把 v1 的点击动作搬进 v2")
    ap.add_argument("--from", dest="src", default=DEFAULT_SRC, help="v1 的 assets/actions")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print(f"找不到来源目录：{args.src}")
        return 2

    ok, missing = [], []
    for src_name, dst_name in PAIRS:
        src_dir = os.path.join(args.src, src_name)
        src_manifest = os.path.join(src_dir, "action.json")
        if not os.path.isfile(src_manifest):
            missing.append(src_name)
            continue

        with open(src_manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        dst_dir = os.path.join(DEST, dst_name)
        dst_frames = os.path.join(dst_dir, "frames")
        if os.path.isdir(dst_frames):
            shutil.rmtree(dst_frames)
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copytree(os.path.join(src_dir, "frames"), dst_frames)

        data["name"] = dst_name
        data["frames_dir"] = f"assets/actions/{dst_name}/frames"
        data["imported_from"] = src_name
        with open(os.path.join(dst_dir, "action.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

        # 预览 GIF 也一起搬（改名）
        gif_src = os.path.join(os.path.dirname(args.src), "source", "action_preview",
                               f"{src_name}.gif")
        if os.path.isfile(gif_src):
            gif_dst = os.path.join(os.path.dirname(args.src), "source", "action_preview",
                                   f"{dst_name}.gif")
            shutil.copyfile(gif_src, gif_dst)

        n = len([f for f in os.listdir(dst_frames) if f.endswith(".png")])
        ok.append((dst_name, n, data.get("title", "")))
        print(f"  {src_name:12} -> {dst_name:12} {n:>3} 帧  {data.get('title', '')}")

    print(f"\n搬过来 {len(ok)} 个" + (f"，没找到 {missing}" if missing else ""))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
