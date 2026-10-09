# -*- coding: utf-8 -*-
"""检查视频拆帧 / 生成视频所需的外部条件。"""
import importlib
import shutil
import sys

MODULES = [
    "PIL", "numpy", "requests",
    "imageio", "imageio_ffmpeg", "av", "cv2",
    "fal_client", "replicate", "openai",
]

print("=== Python 环境 ===")
print("  python:", sys.version.split()[0], sys.executable)
for name in MODULES:
    try:
        mod = importlib.import_module(name)
        print(f"  OK   {name:16} {getattr(mod, '__version__', '')}")
    except Exception as exc:
        print(f"  --   {name:16} 未安装 ({type(exc).__name__})")

print("=== 外部程序 ===")
for exe in ("ffmpeg", "ffprobe"):
    path = shutil.which(exe)
    print(f"  {exe:8} {path or 'NOT FOUND'}")
