"""Проверка подписи initData, которую Telegram передаёт в Mini App.

Алгоритм из документации Telegram Web Apps:
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)
где data_check_string = отсортированные "key=value" (кроме hash) через "\n".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramAuthError(Exception):
    pass


@dataclass
class TelegramUser:
    id: int
    first_name: str = ""
    username: str = ""


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 24 * 3600) -> TelegramUser:
    if not init_data:
        raise TelegramAuthError("empty initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("no hash in initData")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise TelegramAuthError("bad signature")
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if max_age_seconds and auth_date and time.time() - auth_date > max_age_seconds:
        raise TelegramAuthError("initData expired")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as e:
        raise TelegramAuthError("bad user json") from e
    if "id" not in user:
        raise TelegramAuthError("no user in initData")
    return TelegramUser(id=int(user["id"]), first_name=user.get("first_name", ""), username=user.get("username", ""))


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Собрать подписанный initData (для тестов и локальной отладки)."""
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    from urllib.parse import urlencode

    return urlencode({**fields, "hash": h})
