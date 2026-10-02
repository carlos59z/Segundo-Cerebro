"""Notificaciones Telegram directas (best-effort, nunca lanzan)."""
import os

import requests


def send_telegram(text):
    token = os.getenv("TELEGRAM_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000]}, timeout=10)
        return bool(r.ok)
    except requests.RequestException:
        return False
