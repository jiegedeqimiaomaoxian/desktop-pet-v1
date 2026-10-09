# -*- coding: utf-8 -*-
"""假视频服务商：不花钱，用现有精灵直接合成本地"视频"。

用来在没有 API Key 时把整条管道（生成 → 拆帧 → 抠像 → 合成 → 打包）跑通，
也顺便当作动作参考：视频模型该生成什么，这里先给一个低保真版本。

实现方式：对精灵做形变（上下浮动 / 压扁回弹 / 旋转 / 分段弯曲），
再用 Pillow 存成 mp4（有 ffmpeg 时）或直接产出一帧帧 PNG。
"""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile

from PIL import Image

try:
    from providers import GeneratedVideo, ProviderInfo
except ImportError:                                    # 允许单独 import
    from .providers import GeneratedVideo, ProviderInfo


class MockProvider:
    info = ProviderInfo(
        name="mock",
        label="本地模拟（不调用 API）",
        models=["mock-bob", "mock-squat", "mock-sway", "mock-wave"],
        durations=(2.5,),
        resolutions=["720x1280"],
        note="用形变模拟动作，用来验证管道；不产生费用。",
    )

    #: 每个动作的形变参数，单位和其它动作文件保持一致
    MOTIONS = {
        "bob": {"desc": "原地轻轻上下浮动，像呼吸/漂浮"},
        "squat": {"desc": "蹲下再弹起，裙摆跟着抖一下"},
        "sway": {"desc": "身体左右轻摆，头发和尾巴跟着晃"},
        "wave": {"desc": "上半身左右倾斜，像挥手打招呼"},
    }

    def __init__(self, sprite: str | None = None, fps: float = 12.0,
                 size: tuple[int, int] = (720, 1280), duration: float = 2.5) -> None:
        self.sprite_path = sprite
        self.fps = fps
        self.size = size
        self.duration = duration

    # ---------------------------------------------------------------- 帧生成

    def render_frames(self, action: str, sprite: Image.Image | None = None,
                      size: tuple[int, int] | None = None,
                      screen: tuple[int, int, int] = (0, 200, 90),
                      fit: bool = True) -> list[Image.Image]:
        """产出合成好的帧（尺寸 = size 或 self.size）。

        background 直接铺成指定的幕布色，和"用视频模型时首帧的背景"保持一致，
        这样抠像环节走的是同一条代码路径。
        fit=True  ：把传入的图当成"角色"，先按画面比例缩放再摆位（默认）。
        fit=False ：传入的图已经是"摆好角色的首帧"，只做形变、不再缩放。
        """
        base = sprite if sprite is not None else Image.open(self.sprite_path).convert("RGBA")
        size = size or self.size
        count = max(2, int(round(self.duration * self.fps)))
        out = []
        for i in range(count):
            t = i / count                       # 0..1，首尾衔接成循环
            out.append(self._deform(base, action, t, size, screen, fit))
        return out

    def _deform(self, base: Image.Image, action: str, t: float,
                size: tuple[int, int], screen: tuple[int, int, int],
                fit: bool = True) -> Image.Image:
        w, h = size
        if fit:
            # 传入的是"角色"，先按画布高度缩放，再摆到幕布上
            scale = (h * 0.62) / base.height
            sprite = base.resize((max(1, int(base.width * scale)),
                                  max(1, int(base.height * scale))), Image.LANCZOS)
            anchor = None
        else:
            # 传入的已经是"摆好角色的首帧"：只把角色抠出来做形变，
            # 幕布保持原样，这样落点和真实生成时完全一致
            sprite = base.crop(base.getbbox() or (0, 0, w, h))
            anchor = (base.getbbox() or (0, 0, w, h))[:2]

        phase = t * 2 * math.pi
        dx = dy = 0.0
        scale_x = scale_y = 1.0
        angle = 0.0

        if action == "bob":
            dy = -0.035 * h * (0.5 - 0.5 * math.cos(phase))
            scale_y = 1.0 + 0.012 * math.sin(phase)
        elif action == "squat":
            k = 0.5 - 0.5 * math.cos(phase)          # 0->1->0
            scale_y = 1.0 - 0.09 * k
            scale_x = 1.0 + 0.06 * k
            dy = 0.05 * h * k
        elif action == "sway":
            dx = 0.05 * w * math.sin(phase)
            angle = 3.0 * math.sin(phase)
            dy = -0.01 * h * abs(math.sin(phase))
        elif action == "wave":
            angle = 7.0 * math.sin(phase)
            dx = 0.02 * w * math.sin(phase)
            scale_y = 1.0 + 0.01 * math.cos(phase)
        else:
            raise ValueError(f"mock 不支持的动作：{action}")

        if scale_x != 1.0 or scale_y != 1.0:
            sprite = sprite.resize((max(1, int(sprite.width * scale_x)),
                                    max(1, int(sprite.height * scale_y))), Image.LANCZOS)
        if angle:
            sprite = sprite.rotate(angle, resample=Image.BICUBIC, expand=True)

        canvas = Image.new("RGBA", size, tuple(screen) + (255,))
        sprite = sprite.convert("RGBA")
        if fit:
            # 自己摆位：脚大概落在 86% 高度
            x = (w - sprite.width) // 2 + int(dx)
            y = int(h * 0.86 - sprite.height * 0.5) + int(dy)
        else:
            # 以底边中心为锚点：下蹲/跳动时脚不动，左右摆动时绕中轴转
            x = anchor[0] + (base.width - sprite.width) // 2 + int(dx)
            y = anchor[1] + base.height - sprite.height + int(dy)
        canvas.alpha_composite(sprite, (max(-w, x), max(-h, y)))
        return canvas

    # ---------------------------------------------------------------- 对外接口

    def generate(self, prompt: str, image: bytes, duration: float = 0.0,
                 model: str | None = None, **extra) -> GeneratedVideo:
        """模拟一次"视频生成"。

        优先编码成 mp4（走真实的拆帧路径）；没有 ffmpeg 就直接产出一帧帧 PNG，
        让管道跳过视频解码也能继续。
        """
        action = (model or "mock-bob").replace("mock-", "")
        first = Image.open(io.BytesIO(image)).convert("RGBA")
        screen = extra.get("screen") or first.convert("RGB").getpixel((2, 2))
        frames = self.render_frames(action.split("-")[0], first, first.size, screen)
        workdir = tempfile.mkdtemp(prefix="petmock-")
        for i, frame in enumerate(frames):
            frame.convert("RGB").save(os.path.join(workdir, f"f{i:04d}.png"))
        mp4 = self._encode(workdir)
        if mp4:
            with open(mp4, "rb") as fh:
                data = fh.read()
            shutil.rmtree(workdir, ignore_errors=True)
            return GeneratedVideo(data=data, fmt="mp4", fps=self.fps,
                                  duration=len(frames) / self.fps,
                                  info={"provider": "mock", "action": action})
        # 没有 ffmpeg：返回一帧 PNG，并让 frames 目录留着给管道直接用
        buf = io.BytesIO()
        frames[0].save(buf, format="PNG")
        return GeneratedVideo(data=buf.getvalue(), fmt="png", fps=self.fps,
                              duration=len(frames) / self.fps,
                              info={"provider": "mock", "action": action,
                                    "frames_dir": workdir, "frames": len(frames)})

    def _encode(self, workdir: str) -> str | None:
        exe = _find_ffmpeg()
        if not exe:
            return None
        out = os.path.join(workdir, "out.mp4")
        cmd = [exe, "-y", "-loglevel", "error", "-framerate", str(self.fps),
               "-i", os.path.join(workdir, "f%04d.png"),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except Exception:
            return None
        return out if os.path.isfile(out) else None


def _find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
