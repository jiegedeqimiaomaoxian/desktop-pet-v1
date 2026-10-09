# -*- coding: utf-8 -*-
"""DeepSeek 账户余额查询。

接口：GET https://api.deepseek.com/user/balance
认证：Authorization: Bearer <API Key>
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BALANCE_URL = "https://api.deepseek.com/user/balance"
ENV_KEYS = ("DEEPSEEK_API_KEY", "DS_API_KEY")


def resolve_key(cfg: dict) -> tuple[str, str]:
    """返回 (api_key, 来源说明)。环境变量优先，其次配置文件。"""
    for name in ENV_KEYS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value, f"环境变量 {name}"
    value = str(cfg.get("api_key") or "").strip()
    if value:
        return value, "配置文件 pet_config.json"
    return "", ""


def parse_balance(payload: dict) -> tuple[bool, str, dict]:
    """把接口返回解析成 (是否可用, 提示语, 模板字段)。"""
    infos = payload.get("balance_infos") or []
    if not infos:
        return False, "接口没有返回余额信息，请确认账号状态。", {}
    info = infos[0]
    currency = info.get("currency", "CNY") or "CNY"
    fields = {
        "currency": currency,
        "total_balance": info.get("total_balance", "-"),
        "granted_balance": info.get("granted_balance", "-"),
        "topped_up_balance": info.get("topped_up_balance", "-"),
        "is_available": "可用" if payload.get("is_available", True) else "余额不足",
        "count": len(infos),
    }
    if not payload.get("is_available", True):
        return False, f"⚠️ 账户余额不足\n总额 {fields['total_balance']} {currency}", fields
    return True, "", fields


def fetch_balance(api_key: str, timeout: float = 12.0) -> tuple[bool, str, dict]:
    """同步查询余额，返回 (成功, 提示语, 模板字段)。"""
    key = (api_key or "").strip()
    if not key:
        return False, "还没有填 API Key 哦～\n右键我 → 设置 里填一个吧。", {}
    request = urllib.request.Request(
        BALANCE_URL,
        headers={"Authorization": f"Bearer {key}",
                 "Accept": "application/json",
                 "User-Agent": "DesktopPet/2.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = exc.read().decode("utf-8", "replace")
            detail = (json.loads(body).get("error") or {}).get("message", "")
        except Exception:
            pass
        if exc.code in (401, 403):
            return False, f"❌ API Key 被拒绝了（HTTP {exc.code}）\n{detail or '请检查 Key 是否正确'}", {}
        if exc.code == 429:
            return False, "⏳ 查询太频繁了（HTTP 429），\n稍等一下再点我。", {}
        return False, f"❌ 查询失败：HTTP {exc.code}\n{detail}".strip(), {}
    except urllib.error.URLError as exc:
        return False, f"📡 连不上 DeepSeek 服务器\n{exc.reason}", {}
    except TimeoutError:
        return False, "📡 查询超时了，检查一下网络？", {}
    except Exception as exc:
        return False, f"❌ 查询出错：{exc}", {}

    return parse_balance(payload)
