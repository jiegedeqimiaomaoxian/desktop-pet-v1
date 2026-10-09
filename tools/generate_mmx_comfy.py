# -*- coding: utf-8 -*-
"""用「minimax h3（New）」的 ComfyUI MiniMax-H3 生成 **3D 手办风** 桌宠动作素材。

为什么走 ComfyUI 而不是原来的 Gradio 版（tools/generate_mmx.py）：
  1. Gradio 那条路的「上传参考图」在 DSH 沙箱里被跨进程 ACL 卡死（见
     `TODO-继续这里.md`），ComfyUI 的 `/upload/image` 直接写进它自己的 `input/`，
     没有临时目录那一层，绕开了这个限制。
  2. ComfyUI 有 **ref2v（参考图生视频）** 节点，能把角色三视图当设计锚，
     形象比文生视频准得多，也是"3D 手办化"能成立的前提。
  3. 顺带能复用用户自用工作流的参数（分辨率/步数/LoRA/采样器）。

流程（每个动作重复一遍）：
    1. 把角色三视图上传到 ComfyUI input/
    2. 提交 ref2v API 工作流（3D 结构化英文提示词，见 action_presets_3d.py）
    3. 轮询 history 拿到成片
    4. 交给 generate_actions.py --provider file 做 抠绿幕 → 稳定裁切 → 打包 → 预览
    5. 刷新动作清单

用法：
    python tools\\generate_mmx_comfy.py --actions bob --dry-run
    python tools\\generate_mmx_comfy.py --actions bob
    python tools\\generate_mmx_comfy.py --actions all --seed 20240918
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import action_presets_3d as presets_3d                  # noqa: E402
import action_presets_2dcute as presets_2dcute          # noqa: E402
import action_presets_pet as presets_pet                # noqa: E402
import generate_actions as ga                              # noqa: E402
import tempfix                                             # noqa: E402  (修 Windows mkdtemp 权限坑)

#: 可选的画风套装：CLI --style 选一个。
#: preset_set 用**不带前缀的基础方案**，前缀由 --prefix 通过 --preset-prefix 传下去 ——
#: 这样同一套提示词可以出好几批素材（2d_ / 2dh_ …）而互不覆盖。
STYLES = {
    "3d": {"presets": presets_3d, "prefix": "3d_", "preset_set": "3d"},
    "2dcute": {"presets": presets_2dcute, "prefix": "2d_", "preset_set": "2dcute"},
    #: 桌宠 v2：不加前缀（整个项目只有这一套画风，待机和动作必须同源）
    "pet": {"presets": presets_pet, "prefix": "", "preset_set": "pet"},
}

ga.log(f"[temp] 临时目录 -> {tempfix.PATCHED_ROOT}")

BASE = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8188")
CLIENT_ID = str(uuid.uuid4())

#: ComfyUI 安装位置（= F:\deepseek工作区\minimax h3（New））
COMFY_ROOT = r"F:\DeepSeek Work Part\minimax h3（New）"
COMFY_INPUT = os.path.join(COMFY_ROOT, "ComfyUI", "input")
COMFY_OUTPUT = os.path.join(COMFY_ROOT, "ComfyUI", "output")

#: 模型（与用户自用工作流 `自用minimax h3工作流（改自黑鹤001大佬）.json` 逐字一致）
#:   node 20 UNETLoader  -> h3\minimax_h3_fl2va_pruned_int8_convrot.safetensors
#:   node 18 CLIPLoader  -> qwen3vl_32b_minimax_h3_int8_convrot.safetensors
#:   node 21 LoraLoader  -> minimax h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_...bf16
UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP_NAME = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
VAE_VIDEO = "minimax_h3_video_vae_fp16.safetensors"
VAE_AUDIO = "minimax_h3_audio_vae_fp32.safetensors"
LORA = "minimax_h3\\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"

REF_IMAGE = "pet_charsheet.png"
CACHE_DIR = os.path.join(ROOT, "assets", "source", "video_cache")
PROMPT_DIR = os.path.join(ROOT, "assets", "source", "prompts")   # --style 决定子目录

#: 用户工作流 node 8 `ResolutionSelector` = 9:16 / 0.4MP / 倍数 32 → 608x1088
DEFAULT_SIZE = "608x1088"
DEFAULT_STEPS = 4
#: 视频模型固定 24fps 出片
NATIVE_FPS = 24


def snap_frames(seconds: float, fps: int = NATIVE_FPS) -> int:
    """复刻用户工作流 node 40 `ComfyMathExpression` 的"秒数 → 帧数"吸附公式：

        max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17

    MiniMax-H3 的帧数必须落在 17k+5 网格上（5/22/39/56/73/…），
    所以这里把目标帧数向上吸附到最近的合法值。2.33s → 56 帧。
    """
    raw = max(5, int(round(seconds * fps)))
    return raw + (5 - (raw % 17)) % 17


# --------------------------------------------------------------------------- HTTP

def _req(path: str, payload=None, timeout: float = 30.0):
    url = BASE + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:1500]}") from None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return raw


def service_ok() -> bool:
    try:
        stats = _req("/system_stats", timeout=6)
        dev = (stats.get("devices") or [{}])[0]
        ga.log(f"[comfy] 服务在线：{dev.get('name')} "
               f"显存空闲 {dev.get('vram_free', 0) / 2**30:.1f}G")
        return True
    except Exception as exc:
        ga.log(f"[comfy] 服务不在线（{exc}）——先双击 "
               f"'minimax h3（New）\\启动ComfyUI（修复版）.bat'")
        return False


# --------------------------------------------------------------------------- 上传

def upload_reference(sheet_path: str, name: str = REF_IMAGE) -> str:
    """把角色图 POST 到 ComfyUI 的 /upload/image，返回它在 input/ 下的文件名。

    注意：ComfyUI 把上传文件写进**它自己的** ComfyUI/input/，不存在 Gradio 那种
    "临时目录跨进程 ACL"问题 —— 这正是换到 ComfyUI 的原因。
    """
    boundary = "----dshtool" + uuid.uuid4().hex
    with open(sheet_path, "rb") as fh:
        blob = fh.read()
    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="image"; filename="%s"\r\n'
                 % name.encode())
    parts.append(b"Content-Type: image/png\r\n\r\n")
    parts.append(blob)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        BASE + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8", "replace"))
    saved = out.get("name") or name
    ga.log(f"[comfy] 参考图已上传：input/{saved}（{len(blob) / 1e3:.0f} KB）")
    return saved


# --------------------------------------------------------------------------- 工作流

def build(prompt: str, ref_name: str, width: int, height: int, length: int,
          steps: int, seed: int, prefix: str) -> dict:
    """ref2v API 工作流（节点号沿用用户自用工作流，方便对照）。"""
    return {
        "1": {"class_type": "SaveVideo",
              "inputs": {"video": ["3", 0], "filename_prefix": prefix,
                         "format": "auto", "codec": "auto"}},
        "3": {"class_type": "CreateVideo",
              "inputs": {"images": ["5", 0], "audio": ["4", 0], "fps": 24}},
        "4": {"class_type": "VAEDecodeAudio",
              "inputs": {"samples": ["7", 0], "vae": ["19", 0]}},
        "5": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["26", 0]}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo",
              "inputs": {"clip": ["18", 0], "vae": ["26", 0], "audio_vae": ["19", 0],
                         "ref_images.ref_image_0": ["24", 0],
                         "prompt": prompt,
                         "width": width, "height": height, "length": length,
                         "ref_image_size": "match"}},
        "7": {"class_type": "SamplerCustomAdvanced",
              "inputs": {"noise": ["11", 0], "guider": ["14", 0], "sampler": ["10", 0],
                         "sigmas": ["13", 0], "latent_image": ["6", 1]}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "13": {"class_type": "BasicScheduler",
               "inputs": {"model": ["20", 0], "scheduler": "simple",
                          "steps": steps, "denoise": 1.0}},
        "14": {"class_type": "BasicGuider",
               "inputs": {"model": ["21", 0], "conditioning": ["6", 0]}},
        "18": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": CLIP_NAME, "type": "minimax", "device": "default"}},
        "19": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_AUDIO}},
        "20": {"class_type": "UNETLoader",
               "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "21": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["22", 0], "lora_name": LORA, "strength_model": 1.0}},
        "22": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
               "inputs": {"model": ["20", 0]}},
        "24": {"class_type": "LoadImage",
               "inputs": {"image": ref_name, "upload": "image"}},
        "26": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_VIDEO}},
    }


def generate_video(key: str, prompt: str, ref_name: str, args) -> str:
    """提交 ref2v 并等出片，返回本地缓存 mp4。key 是带前缀的动作名。"""
    cache = os.path.join(CACHE_DIR, f"{key}.mp4")
    if os.path.isfile(cache) and not args.force:
        ga.log(f"  [{key}] 命中视频缓存 {os.path.relpath(cache, ROOT)}")
        return cache
    os.makedirs(CACHE_DIR, exist_ok=True)
    seed = args.seed if args.seed >= 0 else int.from_bytes(os.urandom(6), "big") % 2**48
    width, height = (int(v) for v in args.size.lower().split("x"))
    workflow = build(prompt, ref_name, width, height, args.length, args.steps, seed,
                     f"video/pet3d_{key}")
    ga.log(f"  [{key}] 提交 ComfyUI（{args.size} / {args.length} 帧 = "
           f"{args.length / 24:.2f}s / {args.steps} 步 / seed={seed}）…")
    started = time.time()
    reply = _req("/prompt", {"prompt": workflow, "client_id": CLIENT_ID})
    if "prompt_id" not in reply:
        raise RuntimeError("提交被拒：" + json.dumps(reply, ensure_ascii=False)[:900])
    pid = reply["prompt_id"]

    entry = None
    while True:
        try:
            history = _req(f"/history/{pid}", timeout=20)
        except Exception as exc:
            ga.log(f"  [{key}] 查询失败：{exc}")
            history = {}
        if history and pid in history:
            entry = history[pid]
            break
        elapsed = time.time() - started
        if elapsed > args.timeout:
            raise RuntimeError(f"超时 {args.timeout:.0f}s 还没出片")
        if int(elapsed) % 60 < 12:
            ga.log(f"  [{key}] 生成中… {elapsed:.0f}s")
        time.sleep(12)

    status = (entry.get("status") or {}).get("status_str")
    if status != "success":
        detail = ""
        for kind, data in (entry.get("status") or {}).get("messages", []):
            if kind == "execution_error":
                detail = (f"节点 {data.get('node_id')} {data.get('node_type')}："
                          f"{data.get('exception_type')}: {data.get('exception_message')}")
        raise RuntimeError(f"生成失败（{status}）{detail}")

    videos = []
    for out in (entry.get("outputs") or {}).values():
        for item in out.get("images", []) or []:
            if isinstance(item, dict) and item.get("filename"):
                videos.append(os.path.join(COMFY_OUTPUT, item.get("subfolder", ""),
                                           item["filename"]))
    if not videos:
        raise RuntimeError("没有产出视频：" + json.dumps(entry.get("outputs", {}),
                                                         ensure_ascii=False)[:600])
    source = videos[-1]
    if not os.path.isfile(source):
        raise RuntimeError(f"产出路径不存在：{source}")
    shutil.copyfile(source, cache)
    ga.log(f"  [{key}] 出片完成，用时 {time.time() - started:.0f}s -> "
           f"{os.path.relpath(cache, ROOT)}（{os.path.getsize(cache) / 1e6:.1f} MB）")
    return cache


# --------------------------------------------------------------------------- 后处理

def process_video(name: str, video: str, args) -> bool:
    """色相抠掉橄榄绿幕布 → 稳定裁切 → 打包（复用桌宠已有管道）。

    ⚠️ 流畅度的关键在这几行：
      * `--fps 24`  —— 源视频就是 24fps。以前预设写 12.0，ffmpeg 会把 56 帧
        抽成 28 帧、"24fps 的连续运动"直接丢掉一半 → 播起来一顿一顿。
      * `--frames 0` —— 不做二次抽稀，56 帧全留。
      * `--no-stabilize` —— 不做逐帧重摆位（见 animate_pipeline.stabilize_and_crop）。
      * 不加 `--no-trim` —— 让 trim_loop 去掉尾部重复帧，循环接缝才顺。
    """
    cmd = [sys.executable, os.path.join(HERE, "generate_actions.py"),
           "--provider", "file", "--video", video, "--actions", name,
           "--preset-set", args.preset_set_name,
           "--preset-prefix", args.prefix or "none",
           "--force",
           "--fps", str(args.fps),
           "--height", str(args.height),
           "--key", "hue", "--key-low", str(args.key_low),
           "--key-high", str(args.key_high), "--key-min-sat", str(args.key_min_sat),
           "--key-contamination", str(args.key_contamination),
           "--despill", str(args.despill),
           "--skip-top", str(args.skip_top)]
    if args.frames_limit > 0:
        cmd += ["--frames", str(args.frames_limit)]
    if args.no_stabilize:
        cmd += ["--no-stabilize"]
    if args.mask_top:
        cmd += ["--mask-top", str(args.mask_top)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=900,
                            env=dict(os.environ, PYTHONUTF8="1"))
    for line in (result.stdout or "").splitlines():
        if line.strip().startswith(f"[{name}]"):
            ga.log("  " + line.strip())
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-1200:]
        raise RuntimeError(f"后处理失败（退出码 {result.returncode}）：{tail}")
    return True


# --------------------------------------------------------------------------- 主流程

def make_preset_set(module, prefix: str = ""):
    """伪造一个 preset 模块，让 generate_actions 能按（可能带前缀的）名字取到预设。

    动作目录名带前缀（3d_bob / 2d_bob），提示词/标题取自基础预设（bob）。
    """
    class _Set:
        PRESETS = {f"{prefix}{k}": v for k, v in module.PRESETS.items()}

        @staticmethod
        def get(name):
            base = name[len(prefix):] if prefix and name.startswith(prefix) else name
            return module.get(base)
    return _Set


def main() -> int:
    parser = argparse.ArgumentParser(description="用 ComfyUI MiniMax-H3 生成桌宠动作")
    parser.add_argument("--style", choices=sorted(STYLES), default="3d",
                        help="画风套装：3d=实体手办风（前缀 3d_）；"
                             "2dcute=2D 动漫可爱风（前缀 2d_）")
    parser.add_argument("--actions", default="",
                        help="逗号分隔；all = 该风格的全部预设（默认 bob）")
    parser.add_argument("--sheet", default=os.path.join(ROOT, "assets", "source",
                                                        "character_sheet.png"),
                        help="角色设定图（当 ref2v 的参考图）")
    parser.add_argument("--size", default=DEFAULT_SIZE,
                        help="输出尺寸，需为 32 的倍数（默认 608x1088 = 工作流 "
                             "ResolutionSelector 9:16 / 0.4MP / x32）")
    parser.add_argument("--seconds", type=float, default=2.33,
                        help="动作时长（秒）。会按工作流 node 40 的公式吸附到 17k+5 帧网格："
                             "2.33s -> 56 帧")
    parser.add_argument("--length", type=int, default=0,
                        help="直接指定帧数（覆盖 --seconds）；必须是 17k+5（5/22/39/56/73/124）")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="去噪步数")
    parser.add_argument("--fps", type=float, default=NATIVE_FPS,
                        help="打包帧率（源视频是 24fps，改成 12 会丢一半帧、看起来卡）")
    parser.add_argument("--seed", type=int, default=-1,
                        help="随机种子；固定它能让多个动作的形象更一致")
    parser.add_argument("--height", type=int, default=430, help="成品帧高度")
    parser.add_argument("--key-low", type=float, default=12.0,
                        help="色相抠像：与幕布色相距离小于此值判为背景（度）")
    parser.add_argument("--key-high", type=float, default=30.0,
                        help="色相抠像：距离大于此值判为角色（度）")
    parser.add_argument("--key-min-sat", type=float, default=0.10,
                        help="色相抠像：饱和度低于此值算中性色（白围裙），交给污染阈值判断")
    parser.add_argument("--key-contamination", type=float, default=10.0,
                        help="色相抠像：中性像素 g-max(r,b) 超过它就算幕布光污染，一并抠掉")
    parser.add_argument("--despill", type=float, default=0.85,
                        help="去绿幕环境光强度 0~1（0=关）。绿幕会反射到白裤袜上，默认 0.85")
    parser.add_argument("--reprocess-only", action="store_true",
                        help="跳过生成，只把已有视频缓存重新抠像打包（换了抠像参数后用）")
    parser.add_argument("--mask-top", type=float, default=0.0,
                        help="把画面上方这个比例抹透明（清字幕残留用，默认关）")
    parser.add_argument("--frames-limit", type=int, default=0,
                        help="每动作最多保留多少帧；0（默认）= 全留，不抽稀")
    parser.add_argument("--no-stabilize", action="store_true", default=True,
                        help="不做逐帧重摆位（默认开）。逐帧按包围盒对齐会把蹦跳这类"
                             "动作抵消掉，还会因为包围盒噪声引入抖动")
    parser.add_argument("--stabilize", dest="no_stabilize", action="store_false",
                        help="恢复旧的逐帧稳定行为（想看差异时用）")
    parser.add_argument("--skip-top", type=float, default=0.0,
                        help="量包围盒时忽略画面上方这个比例（清字幕用）。默认 0："
                             "2D 那套本来就没有字幕，忽略顶部会把头顶的月牙发饰裁掉")
    parser.add_argument("--prefix", default="",
                        help="动作名前缀（默认取画风套装：3d_ / 2d_）；"
                             "传空字符串以外的值可自定义，传 'none' 表示不加前缀")
    parser.add_argument("--timeout", type=float, default=2400.0, help="单个动作的出片超时（秒）")
    parser.add_argument("--force", action="store_true", help="忽略视频缓存重做")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示词，不出片")
    args = parser.parse_args()

    # 解析画风套装
    style = STYLES[args.style]
    presets = style["presets"]
    args.prefix = style["prefix"] if args.prefix == "" else (
        "" if args.prefix.lower() == "none" else args.prefix)
    args.preset_set_name = style["preset_set"]
    prompt_dir = os.path.join(ROOT, "assets", "source",
                              "prompts_3d" if args.style == "3d" else "prompts_2dcute")

    names = list(presets.PRESETS) if args.actions == "all" else \
        [n.strip() for n in args.actions.split(",") if n.strip()]
    unknown = [n for n in names if n not in presets.PRESETS]
    if unknown:
        ga.log(f"不认识的动作：{unknown}；可选：{', '.join(presets.PRESETS)}")
        return 2
    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except Exception:
        ga.log(f"--size 要写成 宽x高（收到 {args.size!r}）")
        return 2
    for value, label in ((width, "宽"), (height, "高")):
        if value % 32:
            ga.log(f"{label}={value} 不是 32 的倍数，模型会拒绝")
            return 2

    # 时长 -> 帧数：走用户工作流 node 40 的吸附公式（17k+5 网格）
    if args.length <= 0:
        args.length = snap_frames(args.seconds)
    elif (args.length - 5) % 17:
        snapped = args.length + (5 - (args.length % 17)) % 17
        ga.log(f"--length {args.length} 不在 17k+5 网格上，吸附到 {snapped}")
        args.length = snapped

    ga.log(f"画风套装：{args.style}    计划生成 {len(names)} 个动作：{', '.join(names)}")
    ga.log(f"规格：{args.size} / {args.length} 帧 = {args.length / NATIVE_FPS:.2f}s @ "
           f"{NATIVE_FPS}fps / {args.steps} 步 / 抠像 inner={args.key_low} outer={args.key_high}")
    ga.log(f"打包帧率：{args.fps:g}fps"
           + ("（= 源视频原生帧率，一帧不丢）" if abs(args.fps - NATIVE_FPS) < 1e-6
              else f"（⚠️ 源是 {NATIVE_FPS}fps，抽到 {args.fps:g}fps 会丢帧、看起来卡）"))
    ga.log(f"逐帧稳定：{'关（保留全部动作幅度，无对齐噪声）' if args.no_stabilize else '开'}")
    ga.log(f"动作名前缀：{args.prefix!r}"
           + ("（独立命名，不覆盖其它画风的同名动作）" if args.prefix else "（直接覆盖同名动作）"))
    ga.log(f"参考图：{os.path.relpath(args.sheet, ROOT)}")

    os.makedirs(prompt_dir, exist_ok=True)
    for name in names:
        preset = presets.get(name)
        with open(os.path.join(prompt_dir, f"{name}.txt"), "w", encoding="utf-8") as fh:
            fh.write(preset["prompt"])

    if args.dry_run:
        first = presets.get(names[0])
        ga.log("")
        ga.log(f"--- {names[0]} 提示词（{len(first['prompt'])} 字符）---")
        print(first["prompt"])
        ga.log(f"--- 提示词已写到 {os.path.relpath(prompt_dir, ROOT)} ---")
        return 0

    if not os.path.isfile(args.sheet):
        ga.log(f"找不到角色设定图：{args.sheet}")
        return 2
    if args.reprocess_only:
        ga.log("--reprocess-only：不调用模型，只重新抠像打包已有视频缓存")
        ref_name = ""
    else:
        if not service_ok():
            return 2
        ref_name = upload_reference(args.sheet)

    ok, failed = [], []
    for index, name in enumerate(names, 1):
        preset = presets.get(name)
        key = f"{args.prefix}{name}"           # 动作目录名（3d_bob 等）
        ga.log("")
        ga.log(f"=== [{index}/{len(names)}] {key} · {preset['title']} ===")
        try:
            if args.reprocess_only:
                video = os.path.join(CACHE_DIR, f"{key}.mp4")
                if not os.path.isfile(video):
                    raise RuntimeError(f"没有视频缓存 {os.path.relpath(video, ROOT)}")
                ga.log(f"  [{key}] 用缓存 {os.path.relpath(video, ROOT)}")
            else:
                video = generate_video(key, preset["prompt"], ref_name, args)
            process_video(key, video, args)
            ok.append(key)
        except Exception as exc:
            failed.append(key)
            ga.log(f"  [{key}] 失败：{type(exc).__name__}: {exc}")
            ga.log("  （继续做下一个）")

    ga.log("")
    library = ga.rebuild_library()
    ga.log(f"动作清单：{os.path.relpath(library, ROOT)}")
    if ok:
        ga.log(f"成功 {len(ok)} 个：{', '.join(ok)}")
    if failed:
        ga.log(f"失败 {len(failed)} 个：{', '.join(failed)}")
    ga.log("重启桌宠即可生效（右键 → 退出，再双击 启动桌宠.vbs）。")
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        ga.log("\n已中断。")
        raise SystemExit(130)
