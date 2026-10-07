"""Один раз после деплоя: поставить боту кнопку меню, открывающую Mini App.

  python scripts/setup_bot.py

Берёт TELEGRAM_BOT_TOKEN и PUBLIC_BASE_URL из .env.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402


def main() -> None:
    s = get_settings()
    if not s.telegram_bot_token or not s.public_base_url.startswith("https://"):
        sys.exit("Нужны TELEGRAM_BOT_TOKEN и PUBLIC_BASE_URL (https://...) в .env")
    api = f"https://api.telegram.org/bot{s.telegram_bot_token}"
    r = httpx.post(f"{api}/setChatMenuButton", json={
        "menu_button": {"type": "web_app", "text": "Новый товар", "web_app": {"url": s.public_base_url}}
    })
    print("setChatMenuButton:", r.json())
    r = httpx.post(f"{api}/setMyCommands", json={"commands": [{"command": "start", "description": "Открыть приложение"}]})
    print("setMyCommands:", r.json())


if __name__ == "__main__":
    main()
