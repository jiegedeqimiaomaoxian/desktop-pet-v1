# -*- coding: utf-8 -*-
"""API Key 读取：apikey.txt / 环境变量。

apikey.txt 就放在程序目录（desktop-pet 下），格式随便写，支持：

    FAL_KEY=xxxxxxxx
    REPLICATE_API_TOKEN=xxxxxxxx
    OPENAI_API_KEY=xxxxxxxx
    sk-xxxxxxxx                     <- 单独一行没名字的，按当前服务商猜
    # 井号开头是注释

也支持 `KEY: value` 和 `"KEY": "value"` 这种写法。
"""

from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "apikey.txt")

# 每家服务商认识的环境变量名（按顺序找）
PROVIDER_ENV = {
    "fal": ("FAL_KEY", "FAL_API_KEY", "FALAI_API_KEY"),
    "replicate": ("REPLICATE_API_TOKEN", "REPLICATE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "kling": ("KLING_API_KEY", "KLING_ACCESS_KEY"),
}

_LINE = re.compile(r'^\s*(?:"?([A-Za-z0-9_]+)"?)\s*[:=]\s*"?([^"\s#]+)"?\s*$')


def parse_key_file(path: str = KEY_FILE) -> dict[str, str]:
    """把 apikey.txt 解析成 {KEY: value}；解析不了的行按裸 Key 收集到 _bare。"""
    out: dict[str, str] = {}
    bare: list[str] = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = _LINE.match(line)
            if match:
                out[match.group(1).upper()] = match.group(2)
            elif "=" not in line and ":" not in line:
                bare.append(line)
    if bare:
        out["_bare"] = bare
    return out


def load_keys(path: str = KEY_FILE) -> dict[str, str]:
    """合并 apikey.txt 与环境变量（环境变量优先）。"""
    keys = parse_key_file(path)
    for name, value in os.environ.items():
        if value and ("KEY" in name.upper() or "TOKEN" in name.upper()):
            keys.setdefault(name.upper(), value.strip())
    return keys


def key_for(provider: str, keys: dict[str, str] | None = None) -> str:
    """取某个服务商的 Key：先看它专属的环境变量名，再看裸 Key。"""
    keys = keys if keys is not None else load_keys()
    for name in PROVIDER_ENV.get(provider, ()):
        value = keys.get(name) or os.environ.get(name)
        if value:
            return value.strip()
    bare = keys.get("_bare") or []
    if len(bare) == 1:
        return bare[0]
    if bare:
        return bare[0]
    # 最后再试一次：任何名字里带这个服务商的键
    for name, value in keys.items():
        if provider.upper() in name.upper():
            return value
    return ""


def describe(provider: str, keys: dict[str, str] | None = None) -> str:
    """给人看的说明：Key 从哪来的。"""
    keys = keys if keys is not None else load_keys()
    for name in PROVIDER_ENV.get(provider, ()):
        if os.environ.get(name):
            return f"环境变量 {name}"
        if keys.get(name):
            return f"{KEY_FILE} 里的 {name}"
    if keys.get("_bare"):
        return f"{KEY_FILE} 里的裸 Key"
    return "没找到"


if __name__ == "__main__":
    found = load_keys()
    print("apikey.txt:", KEY_FILE, "存在" if os.path.isfile(KEY_FILE) else "不存在")
    for name in sorted(found):
        value = found[name]
        if name == "_bare":
            print(f"  裸 Key      {len(value)} 个: {[v[:8] + '...' for v in value]}")
        else:
            print(f"  {name:24} {value[:8]}...")
    for provider in ("fal", "replicate", "openai"):
        print(f"{provider:10} -> {describe(provider)}")
