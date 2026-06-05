# -*- coding: utf-8 -*-
"""钉钉自定义机器人：发送 markdown 消息，支持加签。"""
import time
import hmac
import base64
import hashlib
import urllib.parse
import requests


def _sign(webhook: str, secret: str) -> str:
    """开启加签时，给 webhook 追加 timestamp 和 sign 参数。"""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"),
                      string_to_sign.encode("utf-8"),
                      hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"


def send_markdown(webhook: str, secret: str, title: str, text: str,
                  at_mobiles=None, at_all=False):
    url = _sign(webhook, secret)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": bool(at_all)},
    }
    r = requests.post(url, json=payload, timeout=15)
    data = r.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"钉钉推送失败: {data}")
    return data
