# -*- coding: utf-8 -*-
"""找一个可用的 ffmpeg：本机已有就用，没有就从 npm 镜像下（快）。

用法：
    python tools/setup_ffmpeg.py            # 直接装
    python tools/setup_ffmpeg.py --check    # 只检查

会优先使用 tools/bin/ffmpeg.exe，其次系统 PATH。
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import sys
import tarfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(HERE, "bin")

# npm 镜像里打包好的 ffmpeg 二进制（@ffmpeg-installer 系列）
SOURCES = [
    ("npmmirror @ffmpeg-installer/win32-x64",
     "https://registry.npmmirror.com/@ffmpeg-installer/win32-x64/-/win32-x64-4.1.0.tgz",
     "package/ffmpeg.exe"),
    ("npmmirror ffmpeg-static",
     "https://registry.npmmirror.com/ffmpeg-static/-/ffmpeg-static-5.2.0.tgz",
     "package/ffmpeg.exe"),
]


def find_local() -> str | None:
    """先找已经装好的。"""
    for env in ("FFMPEG", "IMAGEIO_FFMPEG_EXE"):
        path = os.environ.get(env)
        if path and os.path.isfile(path):
            return path
    local = os.path.join(BIN_DIR, "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    for name in ("ffmpeg", "ffmpeg.exe"):
        path = shutil.which(name)
        if path:
            return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def download(url: str, timeout: float = 600.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        started = time.time()
        last = 0.0
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            buf.write(chunk)
            done = buf.tell()
            elapsed = time.time() - started
            if elapsed - last > 5:
                last = elapsed
                pct = f"{done / total * 100:5.1f}%" if total else "  ?  "
                print(f"    {pct}  {done / 1e6:6.1f} MB  {done / elapsed / 1e6:5.2f} MB/s")
        return buf.getvalue()


def install() -> str:
    os.makedirs(BIN_DIR, exist_ok=True)
    target = os.path.join(BIN_DIR, "ffmpeg.exe")
    for label, url, member in SOURCES:
        print(f"[ffmpeg] 尝试 {label}")
        try:
            data = download(url)
            print(f"[ffmpeg] 下载完成 {len(data) / 1e6:.1f} MB，解包…")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                names = tar.getnames()
                hit = member if member in names else next(
                    (n for n in names if n.endswith("ffmpeg.exe") or n.endswith("/ffmpeg")), None)
                if not hit:
                    print(f"[ffmpeg] 包里没找到 ffmpeg 可执行文件：{names[:8]}")
                    continue
                extracted = tar.extractfile(hit)
                if extracted is None:
                    continue
                with open(target, "wb") as fh:
                    shutil.copyfileobj(extracted, fh)
            os.chmod(target, os.stat(target).st_mode | stat.S_IEXEC)
            print(f"[ffmpeg] 已安装到 {target}")
            return target
        except Exception as exc:
            print(f"[ffmpeg] {label} 失败：{type(exc).__name__}: {exc}")
    raise SystemExit(
        "自动安装失败。可以手动装一个 ffmpeg 后重试：\n"
        "  · winget install Gyan.FFmpeg\n"
        "  · 或下载 https://www.gyan.dev/ffmpeg/builds/ 解压，把 bin 加进 PATH\n"
        "  · 或设置环境变量 FFMPEG=<ffmpeg.exe 路径>")


def main() -> int:
    check_only = "--check" in sys.argv
    found = find_local()
    if found:
        print(f"[ffmpeg] 已有：{found}")
        os.system(f'"{found}" -version >nul 2>&1')
        return 0
    print("[ffmpeg] 本机没有找到 ffmpeg")
    if check_only:
        return 1
    path = install()
    os.system(f'"{path}" -version')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
