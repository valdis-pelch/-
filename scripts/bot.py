"""Минимальный бот (long polling): на /start отвечает кнопкой, открывающей Mini App.

Необязателен: кнопка меню из setup_bot.py работает и без запущенного бота.
Запуск:  python scripts/bot.py
"""
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402


def main() -> None:
    s = get_settings()
    api = f"https://api.telegram.org/bot{s.telegram_bot_token}"
    allowed = s.allowed_user_ids
    offset = 0
    print("bot started")
    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=40)
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                user_id = (msg.get("from") or {}).get("id")
                if not chat_id:
                    continue
                if allowed and user_id not in allowed:
                    httpx.post(f"{api}/sendMessage", json={"chat_id": chat_id, "text": f"Нет доступа. Ваш id: {user_id}"})
                    continue
                httpx.post(f"{api}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "Нажмите кнопку, чтобы завести товар.",
                    "reply_markup": {"inline_keyboard": [[{"text": "Новый товар", "web_app": {"url": s.public_base_url}}]]},
                })
        except Exception as e:  # noqa: BLE001
            print("poll error:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
