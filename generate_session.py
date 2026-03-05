"""
generate_session.py — ЗАПУСТИТЬ ОДИН РАЗ ЛОКАЛЬНО для получения session string
Полученную строку положить в .env как TELEGRAM_SESSION_STRING=...
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("Введи API_ID: "))
API_HASH = input("Введи API_HASH: ")

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        session_str = client.session.save()
        print("\n✅ Session string (скопируй в .env):\n")
        print(f"TELEGRAM_SESSION_STRING={session_str}\n")

asyncio.run(main())
