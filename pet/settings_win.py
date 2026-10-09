# -*- coding: utf-8 -*-
"""设置窗口：API Key / 台词文件 / 余额文案 / 行为开关 / 大小。"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog

from . import config as config_mod
from . import net

BG = "#f4f5fb"
HINT = "#5a6180"


class SettingsDialog:
    def __init__(self, pet) -> None:
        self.pet = pet
        self.pet.test_label = None
        self.win = tk.Toplevel(pet.root)
        self.win.title("设置 · 深海小女仆 2.0")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.small = pet.small_font
        self.rows = 0
        body = tk.Frame(self.win, bg=BG, padx=14, pady=14)
        body.pack(fill="both", expand=True)
        self.body = body

        # --- API Key ---
        self._label("DeepSeek API Key")
        self.key_var = tk.StringVar(value=str(pet.cfg.get("api_key", "")))
        tk.Entry(body, textvariable=self.key_var, width=48, show="•").grid(
            row=self._next(), column=0, columnspan=2, sticky="we")
        env_note = ""
        for name in net.ENV_KEYS:
            if (os.environ.get(name) or "").strip():
                env_note = f"（已检测到环境变量 {name}，会优先使用它）"
                break
        self._hint("在 platform.deepseek.com 生成；留空则用环境变量 DEEPSEEK_API_KEY"
                   + env_note, pady=(2, 10))

        # --- 台词文件 ---
        self._label("话语文本文件（一行一句，# 开头是注释）")
        self.text_var = tk.StringVar(value=str(pet.cfg.get("text_file", "dialogue.txt")))
        picker = tk.Frame(body, bg=BG)
        picker.grid(row=self._next(), column=0, columnspan=2, sticky="we")
        tk.Entry(picker, textvariable=self.text_var, width=38).pack(
            side="left", fill="x", expand=True)
        for text, cmd in (("浏览…", self.browse_text),
                          ("编辑", lambda: self.pet.open_text_file())):
            tk.Button(picker, text=text, command=cmd, font=self.small).pack(
                side="left", padx=(6, 0))
        self._hint("相对路径按程序目录解析。改完保存即可生效，不用重启。", pady=(2, 10))

        # --- 余额模板 ---
        self._label("余额显示文案（可用字段见下）")
        self.tpl = tk.Text(body, width=52, height=4, font=self.small, wrap="word")
        self.tpl.insert("1.0", str(pet.cfg.get("balance_template", "")))
        self.tpl.grid(row=self._next(), column=0, columnspan=2, sticky="we")
        self._hint("{total_balance} {granted_balance} {topped_up_balance} {currency} "
                   "{is_available} {count}", pady=(2, 10))

        # --- 行为开关 ---
        self._label("行为")
        opts = tk.Frame(body, bg=BG)
        opts.grid(row=self._next(), column=0, columnspan=2, sticky="we")
        self.gaze_var = tk.BooleanVar(value=bool(pet.cfg.get("gaze", True)))
        self.physics_var = tk.BooleanVar(value=bool(pet.cfg.get("physics", True)))
        self.shadow_var = tk.BooleanVar(value=bool(pet.cfg.get("shadow", True)))
        self.top_var = tk.BooleanVar(value=bool(pet.cfg.get("always_on_top", True)))
        for var, text in ((self.gaze_var, "视线跟随鼠标"),
                          (self.physics_var, "拖拽物理"),
                          (self.shadow_var, "脚下投影"),
                          (self.top_var, "窗口置顶")):
            tk.Checkbutton(opts, text=text, variable=var, bg=BG, font=self.small,
                           activebackground=BG).pack(side="left", padx=(0, 10))

        nums = tk.Frame(body, bg=BG)
        nums.grid(row=self._next(), column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.reset_var = self._number(nums, "点击计数清零（秒）",
                                      pet.cfg.get("click_reset_seconds", 10))
        self.sleep_var = self._number(nums, "多久没事就睡着（秒，0=不睡）",
                                      pet.cfg.get("auto_sleep_seconds", 90))
        self.scale_var = self._number(nums, "大小倍率", pet.cfg.get("scale", 1.0))

        # --- 测试 + 按钮 ---
        self.test_label = tk.Label(body, text="", bg=BG, fg="#1b7a3d", font=self.small,
                                   wraplength=430, justify="left")
        self.test_label.grid(row=self._next(), column=0, columnspan=2, sticky="w",
                             pady=(10, 0))
        pet.test_label = self.test_label

        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=self._next(), column=0, columnspan=2, sticky="e", pady=(12, 0))
        for text, cmd, width in (("测试连接", self.test_connection, 0),
                                 ("保存", self.save, 8), ("取消", self.close, 8)):
            tk.Button(buttons, text=text, font=self.small, command=cmd,
                      width=width or 0).pack(side="left", padx=4)

        body.columnconfigure(0, weight=1)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        self.win.geometry(f"+{max(0, (self.win.winfo_screenwidth() - w) // 2)}"
                          f"+{max(0, (self.win.winfo_screenheight() - h) // 3)}")
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 小工具

    def _next(self) -> int:
        self.rows += 1
        return self.rows - 1

    def _label(self, text: str) -> None:
        tk.Label(self.body, text=text, bg=BG, font=self.small, anchor="w").grid(
            row=self._next(), column=0, sticky="w", pady=(0, 2))

    def _hint(self, text: str, pady=(2, 10)) -> None:
        tk.Label(self.body, text=text, bg=BG, fg=HINT, font=self.small, anchor="w",
                 wraplength=430, justify="left").grid(
            row=self._next(), column=0, columnspan=2, sticky="w", pady=pady)

    def _number(self, parent, label: str, value) -> tk.StringVar:
        tk.Label(parent, text=label, bg=BG, font=self.small).pack(side="left")
        var = tk.StringVar(value=str(value))
        tk.Entry(parent, textvariable=var, width=5).pack(side="left", padx=(5, 14))
        return var

    def browse_text(self) -> None:
        path = filedialog.askopenfilename(
            title="选择话语文本文件", initialdir=config_mod.ROOT,
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.text_var.set(path)

    # ------------------------------------------------------------------ 动作

    def collect(self) -> dict:
        cfg = dict(self.pet.cfg)
        cfg["api_key"] = self.key_var.get().strip()
        cfg["text_file"] = self.text_var.get().strip() or "dialogue.txt"
        cfg["balance_template"] = self.tpl.get("1.0", "end").rstrip("\n")
        cfg["gaze"] = bool(self.gaze_var.get())
        cfg["physics"] = bool(self.physics_var.get())
        cfg["shadow"] = bool(self.shadow_var.get())
        cfg["always_on_top"] = bool(self.top_var.get())
        for key, var, lo, hi, default in (
                ("click_reset_seconds", self.reset_var, 0.0, 600.0, 10.0),
                ("auto_sleep_seconds", self.sleep_var, 0.0, 3600.0, 90.0),
                ("scale", self.scale_var, 0.5, 2.0, 1.0)):
            try:
                cfg[key] = min(hi, max(lo, float(var.get())))
            except ValueError:
                cfg[key] = default
        return cfg

    def test_connection(self) -> None:
        cfg = self.collect()
        key = cfg["api_key"] or net.resolve_key(cfg)[0]
        if not key:
            self.test_label.configure(text="⚠️ 还没有填 API Key", fg="#b02a2a")
            return
        self.test_label.configure(text="正在测试…", fg=HINT)

        def worker() -> None:
            ok, message, fields = net.fetch_balance(key)
            self.pet.results.put(("test", ok, message, fields))

        threading.Thread(target=worker, daemon=True).start()

    def save(self) -> None:
        cfg = self.collect()
        old_scale = float(self.pet.cfg.get("scale", 1.0) or 1.0)
        self.pet.cfg = cfg
        self.pet._save_cfg()
        self.pet.topmost = bool(cfg["always_on_top"])
        try:
            self.pet.root.attributes("-topmost", self.pet.topmost)
        except tk.TclError:
            pass
        self.pet.lines, self.pet.lines_note, self.pet.action_lines = config_mod.load_lines(
            config_mod.text_path(cfg))
        self.pet.lines_mtime = self.pet._text_mtime()
        if abs(float(cfg["scale"]) - old_scale) > 1e-6:
            self.pet.rebuild_geometry()          # 大小变了要重新量画布、重热素材
        self.pet.clicks = 0
        self.pet.show_text("设置已保存～", speak=False)
        self.close()

    def close(self) -> None:
        self.pet.test_label = None
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
