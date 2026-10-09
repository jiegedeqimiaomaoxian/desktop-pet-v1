# -*- coding: utf-8 -*-
"""视频拆帧与编码（把模型返回的视频变成一帧帧图片）。

按下列顺序找 ffmpeg，找到就能用：
  1. 环境变量 FFMPEG / IMAGEIO_FFMPEG_EXE
  2. pip 装的 imageio-ffmpeg（自带一份二进制）
  3. 系统 PATH 里的 ffmpeg
  4. 常见安装位置（scoop / winget / chocolatey / 手动解压目录）

没有 ffmpeg 时会给出明确的安装提示，而不是抛一堆看不懂的错。
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

CANDIDATE_GLOBS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "ffmpeg.exe"),
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    os.path.expanduser(r"~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe"),
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\*\ffmpeg.exe"),
    os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
]

INSTALL_HINT = (
    "需要 ffmpeg 才能把视频拆成帧。任选一种方式装好再重试：\n"
    "  1) python tools\\setup_ffmpeg.py          （推荐，从 npm 镜像下载，几十秒）\n"
    "  2) winget install Gyan.FFmpeg            （装完重开终端）\n"
    "  3) 手动下载 https://www.gyan.dev/ffmpeg/builds/ 解压后把 bin 加进 PATH\n"
    "  4) 已经有 ffmpeg 的话，设环境变量 FFMPEG=<ffmpeg.exe 路径>"
)


class FrameError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    for env in ("FFMPEG", "IMAGEIO_FFMPEG_EXE"):
        path = os.environ.get(env)
        if path and os.path.isfile(path):
            return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for pattern in CANDIDATE_GLOBS:
        for hit in glob.glob(pattern):
            if os.path.isfile(hit):
                return hit
    return None


def require_ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise FrameError(INSTALL_HINT)
    return exe


def probe(video_path: str) -> dict:
    """读视频信息：帧率、尺寸、时长、帧数。失败时返回空字典（不影响拆帧）。"""
    exe = find_ffmpeg()
    if not exe:
        return {}
    probe_exe = exe.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if os.path.isfile(probe_exe):
        try:
            out = subprocess.run(
                [probe_exe, "-v", "error", "-select_streams", "v:0", "-show_streams",
                 "-show_format", "-of", "json", video_path],
                check=True, capture_output=True, text=True).stdout
            data = json.loads(out)
            stream = (data.get("streams") or [{}])[0]
            num, _, den = (stream.get("r_frame_rate") or "30/1").partition("/")
            fps = float(num) / float(den or 1)
            return {
                "fps": fps,
                "width": stream.get("width"),
                "height": stream.get("height"),
                "duration": float(data.get("format", {}).get("duration") or 0.0),
                "frames": int(stream.get("nb_frames") or 0),
            }
        except Exception:
            pass
    # 退路：让 ffmpeg 自己报参数
    try:
        out = subprocess.run([exe, "-i", video_path], capture_output=True, text=True).stderr
        info = {}
        match = re.search(r"(\d+(?:\.\d+)?) fps", out)
        if match:
            info["fps"] = float(match.group(1))
        match = re.search(r"(\d{2,5})x(\d{2,5})", out)
        if match:
            info["width"], info["height"] = int(match.group(1)), int(match.group(2))
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
        if match:
            info["duration"] = (int(match.group(1)) * 3600 + int(match.group(2)) * 60
                                + float(match.group(3)))
        return info
    except Exception:
        return {}


def extract_frames(video_path: str, fps: float = 12.0, max_frames: int = 96,
                    out_dir: str | None = None) -> list[str]:
    """按目标帧率抽帧，返回按顺序排列的 PNG 路径。"""
    exe = require_ffmpeg()
    out_dir = out_dir or tempfile.mkdtemp(prefix="petframes-")
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "f%04d.png")
    cmd = [exe, "-y", "-loglevel", "error", "-i", video_path,
           "-vf", f"fps={fps}", "-frames:v", str(max_frames), pattern]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise FrameError(f"ffmpeg 抽帧失败：{exc.stderr.decode('utf-8', 'replace')[:400]}") from None
    frames = sorted(glob.glob(os.path.join(out_dir, "f*.png")))
    if not frames:
        raise FrameError("ffmpeg 没有抽出任何帧，检查一下视频文件是否正常")
    return frames


def load_frames(data: bytes, fmt: str = "mp4", fps: float = 12.0, max_frames: int = 96) -> tuple:
    """把视频字节变成帧文件列表；返回 (帧路径列表, 临时目录, 视频信息)。

    如果拿到的其实是图片（png/jpg），就直接当单帧处理。
    """
    tmpdir = tempfile.mkdtemp(prefix="petvideo-")
    ext = "." + (fmt or "mp4").lstrip(".")
    path = os.path.join(tmpdir, "input" + ext)
    with open(path, "wb") as fh:
        fh.write(data)
    if ext.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return [path], tmpdir, {"fps": fps, "frames": 1}
    info = probe(path)
    frames = extract_frames(path, fps=fps, max_frames=max_frames,
                            out_dir=os.path.join(tmpdir, "frames"))
    info["frames"] = len(frames)
    return frames, tmpdir, info


if __name__ == "__main__":
    print("ffmpeg:", find_ffmpeg() or "没找到")
    print(INSTALL_HINT)
