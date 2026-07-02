import os
from typing import Dict

from telethon import TelegramClient

from app.config import settings

# Держим живые клиенты Telethon в памяти процесса, по одному на номер телефона.
# Файл .session для каждого номера сохраняется на диск (volume) и переживает
# перезапуск контейнера, поэтому повторная авторизация не требуется.
_clients: Dict[str, TelegramClient] = {}


def _session_path(phone: str) -> str:
    safe = phone.replace("+", "").replace(" ", "").replace("(", "").replace(")", "").replace("-", "")
    return os.path.join(settings.SESSIONS_DIR, safe)


async def get_client(phone: str) -> TelegramClient:
    client = _clients.get(phone)
    if client is not None and client.is_connected():
        return client

    client = TelegramClient(_session_path(phone), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    await client.connect()
    _clients[phone] = client
    return client


async def is_authorized(phone: str) -> bool:
    client = await get_client(phone)
    return await client.is_user_authorized()
