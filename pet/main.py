# -*- coding: utf-8 -*-
"""入口。

    python pet\\main.py           带控制台（方便看报错）
    双击 启动桌宠.vbs             无黑框（推荐）
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):                     # 允许 `python pet\main.py` 直接跑
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "pet"

from . import anim                                # noqa: E402
from .app import Pet, claim_lock, harden_console, log, release_lock  # noqa: E402


def main() -> None:
    harden_console()
    lock = claim_lock()
    if lock is None:
        log("已经有一只小女仆在桌面上了～")
        return
    try:
        pet = Pet()
        pet.root.mainloop()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\n出错了，按回车关闭…")
        except Exception:
            pass
    finally:
        anim.lower_timer_resolution()
        release_lock(lock)


if __name__ == "__main__":
    main()
