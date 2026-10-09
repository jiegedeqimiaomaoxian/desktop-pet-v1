# -*- coding: utf-8 -*-
"""修掉 `tempfile.mkdtemp` 在 Windows 上的老毛病（本仓库的固定坑）。

症状：
    `PermissionError: [Errno 13] Permission denied: '...\\Temp\\dsh-xxxx\\petvideo-xxxx\\input.mp4'`

根因（实测确认，2026-09-18）：
    `tempfile.mkdtemp` 用 `mode=0o700` 建目录。Windows 上这会被翻译成一条
    **限制性 ACL**（只有 owner 有全权），叠在 DSH 沙箱身份上之后，连创建者自己
    往里面写文件都被拒。同理 `TemporaryDirectory` 清理时还会放大成 WinError 5。
    本机 MiniMax-H3 那套也踩过同一个坑（见该技能的 `tools/mmx_tempfix.py`）。

修法：
    1. 把临时根目录指到**工作区内**（`assets/source/_tmp`），避开沙箱 Temp 的老 ACL；
    2. 用「普通权限 `os.makedirs` + 唯一名字」替换 `mkdtemp`，不再产生 0o700 ACL。

两种用法：
    A. 进程内：`import mmx_tempfix` 即可（改的是 tempfile 本身）
    B. 自动注入：把本文件所在目录放进 PYTHONPATH，`sitecustomize.py` 会拉起它
"""

from __future__ import annotations

import os
import tempfile
import uuid

#: 临时根目录：工作区内的 _tmp（保证当前沙箱身份可写）
_HERE = os.path.dirname(os.path.abspath(__file__))
_TMP_ROOT = os.path.join(os.path.dirname(_HERE), "assets", "source", "_tmp")


def _ensure_tmp_root() -> str:
    try:
        os.makedirs(_TMP_ROOT, exist_ok=True)
    except Exception:
        return tempfile.gettempdir()
    return _TMP_ROOT


def patch() -> str:
    """替换 tempfile.mkdtemp / gettempdir，返回实际使用的临时根目录。"""
    root = _ensure_tmp_root()
    tempfile.tempdir = root

    _original_mkdtemp = tempfile.mkdtemp

    def mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
        base = dir or tempfile.tempdir or root
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            base = root
            os.makedirs(base, exist_ok=True)
        for _ in range(50):
            candidate = os.path.join(base, f"{prefix}{uuid.uuid4().hex[:8]}{suffix}")
            try:
                os.makedirs(candidate)          # 普通权限，不带 0o700 ACL
                return candidate
            except FileExistsError:
                continue
            except PermissionError:
                # 连这里都写不进就退回原生实现，至少报错位置一致
                return _original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        raise FileExistsError(f"在 {base} 下连续 50 次都没建出唯一临时目录")

    tempfile.mkdtemp = mkdtemp        # type: ignore[assignment]
    return root


PATCHED_ROOT = patch()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"临时根目录 -> {PATCHED_ROOT}")
    probe = tempfile.mkdtemp(prefix="selftest-")
    target = os.path.join(probe, "write_probe.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("ok")
    print(f"建目录 OK: {probe}")
    print(f"写文件 OK: {target} ({os.path.getsize(target)} B)")
    os.remove(target)
    os.rmdir(probe)
    print("自检通过：mkdtemp + 写入 + 清理都正常")
