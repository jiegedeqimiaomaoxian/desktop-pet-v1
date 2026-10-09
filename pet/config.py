# -*- coding: utf-8 -*-
"""配置与台词本。

配置放 `pet_config.json`（首次运行自动生成）；台词放 `dialogue.txt`。
两者都支持"改完保存即生效"，不用重启。
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "pet_config.json")
DEFAULT_TEXT = "dialogue.txt"

DEFAULTS: dict = {
    "api_key": "",
    "text_file": DEFAULT_TEXT,
    "balance_template": "💰 DeepSeek 余额\n总额 {total_balance} {currency}\n"
                        "赠送 {granted_balance}｜充值 {topped_up_balance}",
    "click_reset_seconds": 10.0,      # 多久没点就把"第几次点击"清零
    "always_on_top": True,
    "scale": 1.0,                     # 角色大小倍率
    "pos": None,                      # 上次停留的位置
    # --- 行为开关（都能在设置窗口里改） ---
    "gaze": True,                     # 鼠标视线跟随
    "physics": True,                  # 拖拽弹簧 + 松手掉落
    "auto_sleep_seconds": 90.0,       # 多久没交互就睡着（0 = 不睡）
    "auto_emote_seconds": 45.0,       # 多久自己卖个萌（0 = 不卖）
    "shadow": True,                   # 脚下投影
    #: 常驻内存的片段套数。0 = 全部常驻（默认，切换零等待）。
    #: 内存账：一个片段 56 帧 x 约 380x380 x 4B ≈ 32MB，21 个片段约 680MB。
    #: 想省内存就调到 6~8：代价是偶尔要用到没常驻的片段时，会先保持当前
    #: 姿势约 0.8 秒（后台重新预热），随后再切过去。
    "preload_keep": 0,
}

DEFAULT_LINES = ["点我一下嘛～"]


def load() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh) or {})
        except Exception as exc:
            print(f"[config] 读取失败，用默认值：{exc}")
    return cfg


def save(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def text_path(cfg: dict) -> str:
    raw = str(cfg.get("text_file") or DEFAULT_TEXT)
    return raw if os.path.isabs(raw) else os.path.join(ROOT, raw)


def load_lines(path: str) -> tuple[list[str], str, dict[str, list[str]]]:
    """读台词本，返回 (通用台词, 提示信息, {动作名: 该动作专属台词})。

    用 `[动作名]` 单独一行开一段，播到那个动作时就优先说那一段 ——
    这样台词和动作是对得上的。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return list(DEFAULT_LINES), "文件不存在", {}
    except Exception as exc:
        return list(DEFAULT_LINES), f"读取失败：{exc}", {}

    general: list[str] = []
    sections: dict[str, list[str]] = {}
    current = ""
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("[") and text.endswith("]") and len(text) > 2:
            current = text[1:-1].strip().lower()
            sections.setdefault(current, [])
            continue
        (sections[current] if current else general).append(text)

    if not general and not sections:
        return list(DEFAULT_LINES), "文件里没有可用的话语", {}
    return (general or list(DEFAULT_LINES)), "", sections
