# -*- coding: utf-8 -*-
"""视频生成服务商适配层。

统一接口：给一张首帧图 + 提示词 + 时长 -> 拿到视频字节。
只用标准库（urllib），不依赖各家 SDK，Key 从 apikey.txt / 环境变量读。

支持：
  fal       —— fal.ai 队列 API（可灵 / Seedance / Veo 等模型都挂在上面）
  replicate —— Replicate predictions API
  openai    —— OpenAI Sora 视频接口
  mock      —— 本地假视频：把首帧做形变，用来离线跑通整条管道
  file      —— 直接用一个现成的视频/图片序列文件代替 API（省钱调试用）
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import keyfile

USER_AGENT = "DesktopPetVideo/1.0"


class ProviderError(RuntimeError):
    """调用视频服务失败（网络、鉴权、参数、超时都归这里）。"""


@dataclass
class GeneratedVideo:
    data: bytes                       # 视频文件字节
    fmt: str = "mp4"                  # 容器格式
    fps: float = 30.0                 # 期望帧率（拆帧时用）
    duration: float = 0.0
    info: dict = field(default_factory=dict)


@dataclass
class ProviderInfo:
    name: str
    label: str
    models: list[str]
    durations: tuple[float, ...]
    resolutions: list[str]
    note: str = ""


# --------------------------------------------------------------------------- HTTP

def http_json(url: str, payload: dict | None = None, headers: dict | None = None,
              method: str | None = None, timeout: float = 60.0) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    head = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        head["Content-Type"] = "application/json"
    head.update(headers or {})
    request = urllib.request.Request(url, data=body, headers=head,
                                     method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise ProviderError(f"HTTP {exc.code} {url}\n{detail}") from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"连不上 {url}：{exc.reason}") from None
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise ProviderError(f"{url} 返回的不是 JSON：{raw[:200]!r}") from None


def http_bytes(url: str, headers: dict | None = None, timeout: float = 300.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"下载视频失败 HTTP {exc.code}：{url}") from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"下载视频失败：{exc.reason}") from None


def poll(step, *, timeout: float = 900.0, interval: float = 5.0, label: str = "生成中"):
    """轮询直到 step() 返回非 None，用来等异步任务。"""
    started = time.time()
    last = 0.0
    while True:
        result = step()
        if result is not None:
            return result
        waited = time.time() - started
        if waited > timeout:
            raise ProviderError(f"{label}超时（{timeout / 60:.0f} 分钟）")
        if waited - last >= 15:
            last = waited
            print(f"    …{label} {waited:.0f}s")
        time.sleep(interval)


# --------------------------------------------------------------------------- fal.ai

class FalProvider:
    info = ProviderInfo(
        name="fal",
        label="fal.ai（可灵 / Seedance / Veo 等）",
        models=[
            "fal-ai/kling-video/v3/pro/image-to-video",
            "fal-ai/kling-video/v3/standard/image-to-video",
            "fal-ai/kling-video/v2.6/pro/image-to-video",
            "fal-ai/bytedance/seedance/v1/pro/image-to-video",
            "fal-ai/veo3.1/fast/image-to-video",
        ],
        durations=(5.0, 10.0, 15.0),
        resolutions=["720p", "1080p"],
        note="按秒计费，可灵约 $0.029/秒；提交后用队列接口轮询结果。",
    )
    base = "https://queue.fal.run"

    def __init__(self, key: str) -> None:
        if not key:
            raise ProviderError("没有找到 fal 的 Key（apikey.txt 里写 FAL_KEY=... ）")
        self.key = key

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Key {self.key}"}

    def generate(self, prompt: str, image: bytes, duration: float = 5.0,
                 model: str | None = None, resolution: str = "720p",
                 image_name: str = "frame.png", timeout: float = 900.0,
                 **extra) -> GeneratedVideo:
        import base64
        model = model or self.info.models[0]
        payload = {
            "prompt": prompt,
            "image_url": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
            "duration": str(int(duration)),
            "aspect_ratio": "9:16",
        }
        if "seedance" in model or "veo" in model:
            payload["resolution"] = resolution
        payload.update(extra)
        submitted = http_json(f"{self.base}/{model}", payload, self.headers, timeout=120)
        status_url = submitted.get("status_url")
        response_url = submitted.get("response_url")
        if not status_url or not response_url:
            raise ProviderError(f"fal 提交返回异常：{submitted}")

        def step():
            state = http_json(status_url, None, self.headers, timeout=60)
            status = (state.get("status") or "").upper()
            if status in ("IN_QUEUE", "IN_PROGRESS", ""):
                return None
            if status != "COMPLETED":
                raise ProviderError(f"fal 任务失败：{status} {state}")
            return http_json(response_url, None, self.headers, timeout=120)

        result = poll(step, timeout=timeout, label="fal 生成")
        return self._unpack(result, duration, model)

    def _unpack(self, result: dict, duration: float, model: str) -> GeneratedVideo:
        video = result.get("video") or {}
        url = video.get("url") or result.get("video_url")
        if not url:
            raise ProviderError(f"fal 结果里没有视频地址：{list(result)[:10]}")
        data = http_bytes(url)
        return GeneratedVideo(data=data, fmt=_fmt_of(url), fps=30.0, duration=duration,
                              info={"provider": "fal", "model": model, "url": url})


# --------------------------------------------------------------------------- Replicate

class ReplicateProvider:
    info = ProviderInfo(
        name="replicate",
        label="Replicate",
        models=[
            "kwaivgi/kling-v3-pro",
            "kwaivgi/kling-v2.5-turbo-pro",
            "bytedance/seedance-1-pro",
        ],
        durations=(5.0, 10.0),
        resolutions=["720p", "1080p"],
        note="predictions API，模型名按 Replicate 上的实际页面填写。",
    )
    base = "https://api.replicate.com/v1"

    def __init__(self, key: str) -> None:
        if not key:
            raise ProviderError("没有找到 Replicate 的 Token（apikey.txt 里写 "
                                "REPLICATE_API_TOKEN=... ）")
        self.key = key

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Prefer": "wait=60"}

    def generate(self, prompt: str, image: bytes, duration: float = 5.0,
                 model: str | None = None, resolution: str = "720p",
                 image_name: str = "frame.png", timeout: float = 900.0,
                 owner: str | None = None, **extra) -> GeneratedVideo:
        import base64
        model = model or self.info.models[0]
        if "/" in model and not owner:
            owner, model = model.split("/", 1)
        payload = {
            "input": {
                "prompt": prompt,
                "start_image": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
                "duration": int(duration) if float(duration).is_integer() else duration,
                "aspect_ratio": "9:16",
                **extra,
            }
        }
        url = f"{self.base}/models/{owner}/{model}/predictions"
        created = http_json(url, payload, self.headers, timeout=120)
        poll_url = (created.get("urls") or {}).get("get")
        if not poll_url:
            raise ProviderError(f"Replicate 返回异常：{created}")

        def step():
            state = http_json(poll_url, None, self.headers, timeout=60)
            status = state.get("status")
            if status in ("starting", "processing", None):
                return None
            if status != "succeeded":
                raise ProviderError(f"Replicate 任务失败：{status} {state.get('error')}")
            return state

        state = poll(step, timeout=timeout, label="Replicate 生成")
        output = state.get("output")
        url_out = output[0] if isinstance(output, list) and output else output
        if not isinstance(url_out, str):
            raise ProviderError(f"Replicate 输出无法识别：{output!r}")
        return GeneratedVideo(data=http_bytes(url_out), fmt=_fmt_of(url_out),
                              fps=30.0, duration=duration,
                              info={"provider": "replicate", "model": f"{owner}/{model}",
                                    "url": url_out})


# --------------------------------------------------------------------------- OpenAI Sora

class OpenAIProvider:
    info = ProviderInfo(
        name="openai",
        label="OpenAI Sora",
        models=["sora-2", "sora-2-pro"],
        durations=(4.0, 8.0, 12.0),
        resolutions=["720x1280"],
        note="需要 OPENAI_API_KEY，且账号已开通视频权限。",
    )
    base = "https://api.openai.com/v1"

    def __init__(self, key: str) -> None:
        if not key:
            raise ProviderError("没有找到 OpenAI 的 Key（apikey.txt 里写 OPENAI_API_KEY=... ）")
        self.key = key

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    def generate(self, prompt: str, image: bytes, duration: float = 4.0,
                 model: str | None = None, resolution: str = "720x1280",
                 image_name: str = "frame.png", timeout: float = 900.0,
                 **extra) -> GeneratedVideo:
        model = model or self.info.models[0]
        boundary = "----DesktopPetBoundary7d1a"
        fields = {"model": model, "prompt": prompt,
                  "size": resolution, "seconds": str(int(duration))}
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                         f"{value}\r\n".encode("utf-8"))
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"input_reference\";"
                     f" filename=\"{image_name}\"\r\nContent-Type: image/png\r\n\r\n".encode("utf-8"))
        parts.append(image)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        request = urllib.request.Request(
            f"{self.base}/videos", data=body,
            headers={**self.headers, "Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": USER_AGENT},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                created = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"OpenAI 提交失败 HTTP {exc.code}："
                                f"{exc.read().decode('utf-8', 'replace')[:400]}") from None
        video_id = created.get("id")
        if not video_id:
            raise ProviderError(f"OpenAI 返回异常：{created}")

        def step():
            state = http_json(f"{self.base}/videos/{video_id}", None, self.headers)
            status = state.get("status")
            if status in ("queued", "in_progress", None):
                return None
            if status not in ("completed", "succeeded"):
                raise ProviderError(f"OpenAI 任务失败：{state}")
            return state

        poll(step, timeout=timeout, label="Sora 生成")
        data = http_bytes(f"{self.base}/videos/{video_id}/content", self.headers)
        return GeneratedVideo(data=data, fmt="mp4", fps=30.0, duration=duration,
                              info={"provider": "openai", "model": model, "id": video_id})


# --------------------------------------------------------------------------- 省钱模式

class FileProvider:
    """不调用任何 API：直接用一个现成的视频文件（或抽好的帧目录）当结果。

    用来在你还没开通 API 时先把整条管道跑通；也方便手工挑选满意的片段。
    """
    info = ProviderInfo(name="file", label="本地视频文件", models=["(你的文件)"],
                        durations=(0.0,), resolutions=[], note="不消耗任何额度")

    def __init__(self, path: str = "") -> None:
        self.path = path

    def generate(self, prompt: str, image: bytes, duration: float = 5.0,
                 model: str | None = None, **extra) -> GeneratedVideo:
        import os
        path = model or self.path
        if not path or not os.path.isfile(path):
            raise ProviderError(f"没有找到本地视频文件：{path!r}（用 --video 指定）")
        with open(path, "rb") as fh:
            data = fh.read()
        return GeneratedVideo(data=data, fmt=_fmt_of(path), fps=float(extra.get("fps", 30.0)),
                              info={"provider": "file", "path": path})


# --------------------------------------------------------------------------- 本机 MiniMax

class MiniMaxLocalProvider:
    """本机的 MiniMax-H3（本地 Gradio 服务，不花钱、不出网）。

    走 MiniMax-H3/tools/mmx.py 客户端：把首帧图和提示词交给它，
    它出带音频的 mp4，再交给下游管道抠像。
    """

    info = ProviderInfo(
        name="mmx-local",
        label="本机 MiniMax-H3（本地服务，免费）",
        models=["MiniMax-H3"],
        durations=(2.3, 3.0, 5.0),
        resolutions=["480x832", "640x960", "720x1280", "832x480"],
        note="靠命令行调 tools/mmx.py；首次生成要加载 18G 模型，约 3~5 分钟。",
    )
    MAX_DIR = r"F:\deepseek工作区\MiniMax-H3"

    def __init__(self, size: str = "480x832", frames: int = 56, steps: int = 4,
                 seed: int = -1, no_upscale: bool = False) -> None:
        self.size = size
        self.frames = frames
        self.steps = steps
        self.seed = seed
        self.no_upscale = no_upscale
        self.mmx_py = os.path.join(self.MAX_DIR, "tools", "mmx.py")
        if not os.path.isfile(self.mmx_py):
            raise ProviderError(f"找不到本机 MiniMax 客户端：{self.mmx_py}")

    def generate(self, prompt: str, image: bytes, duration: float = 0.0,
                 model: str | None = None, resolution: str = "", **extra) -> GeneratedVideo:
        import subprocess
        import tempfile
        size = resolution if resolution and "x" in resolution else self.size
        workdir = tempfile.mkdtemp(prefix="mmx-")
        image_path = os.path.join(workdir, "first.png")
        prompt_path = os.path.join(workdir, "prompt.txt")
        with open(image_path, "wb") as fh:
            fh.write(image)
        with open(prompt_path, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        cmd = [sys.executable, self.mmx_py, "gen",
               "--prompt-file", prompt_path, "--first", image_path,
               "--size", size, "--frames", str(self.frames),
               "--steps", str(self.steps), "--seed", str(self.seed)]
        if self.no_upscale:
            cmd.append("--no-upscale")
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=2400, env=env)
        path = ""
        for line in reversed((result.stdout or "").splitlines()):
            if line.startswith("VIDEO:"):
                path = line[6:].strip()
                break
        if not path or not os.path.isfile(path):
            detail = (result.stderr or result.stdout or "")[-600:]
            raise ProviderError(f"本机 MiniMax 没出片：{detail}")
        with open(path, "rb") as fh:
            data = fh.read()
        return GeneratedVideo(data=data, fmt="mp4", fps=24.0,
                              duration=self.frames / 24.0,
                              info={"provider": "mmx-local", "path": path, "size": size})


# --------------------------------------------------------------------------- 注册表

def get_provider(name: str, keys: dict[str, str] | None = None, **kwargs):
    """按名字构造服务商实例；多余的 kwargs 会被自动丢掉。"""
    name = (name or "mock").lower()
    keys = keys if keys is not None else keyfile.load_keys()

    def build(cls, *args):
        import inspect
        accepted = set(inspect.signature(cls.__init__).parameters) - {"self"}
        return cls(*args, **{k: v for k, v in kwargs.items() if k in accepted})

    if name == "mock":
        from mock_provider import MockProvider
        return build(MockProvider)
    if name == "file":
        return build(FileProvider)
    if name in ("mmx-local", "mmx"):
        return build(MiniMaxLocalProvider)
    if name == "fal":
        return FalProvider(keyfile.key_for("fal", keys))
    if name == "replicate":
        return ReplicateProvider(keyfile.key_for("replicate", keys))
    if name == "openai":
        return OpenAIProvider(keyfile.key_for("openai", keys))
    raise ProviderError(f"不认识的服务商：{name}"
                        f"（可选 fal / replicate / openai / mmx-local / file / mock）")


def list_fal_models(keyword: str = "image-to-video", key: str = "") -> list[tuple[str, str]]:
    """从 fal 的模型清单里找可用的图生视频模型，避免模型 ID 写错。"""
    key = key or keyfile.key_for("fal")
    if not key:
        raise ProviderError("没有找到 fal 的 Key")
    data = http_json("https://fal.ai/api/models?keywords=" + urllib.parse.quote(keyword),
                     None, {"Authorization": f"Key {key}"}, timeout=60)
    items = data.get("items") if isinstance(data, dict) else data
    out: list[tuple[str, str]] = []
    for item in items or []:
        model_id = item.get("id") or item.get("endpointId") or ""
        if model_id and "image-to-video" in model_id:
            out.append((model_id, item.get("title") or item.get("displayName") or ""))
    return sorted(out)


def _fmt_of(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".mp4", ".webm", ".mov", ".gif", ".png", ".jpg"):
        if path.endswith(ext):
            return ext.lstrip(".")
    return "mp4"
