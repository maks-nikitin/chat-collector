import os
from datetime import datetime

import httpx

from app.config import settings
from app.storage import viber_storage

VIBER_API = "https://chatapi.viber.com/pa"


def _headers() -> dict:
    return {
        "X-Viber-Auth-Token": settings.VIBER_BOT_TOKEN,
        "Content-Type": "application/json",
    }


async def set_webhook() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{VIBER_API}/set_webhook",
            headers=_headers(),
            json={
                "url": settings.VIBER_WEBHOOK_URL,
                "event_types": ["message", "subscribed", "unsubscribed", "conversation_started"],
            },
        )
        return resp.json()


async def send_message(receiver_id: str, text: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{VIBER_API}/send_message",
            headers=_headers(),
            json={
                "receiver": receiver_id,
                "min_api_version": 7,
                "sender": {"name": settings.VIBER_BOT_NAME, "avatar": settings.VIBER_BOT_AVATAR},
                "type": "text",
                "text": text,
            },
        )
        return resp.json()


async def _download_media(url: str, dest_dir: str, filename: str):
    os.makedirs(dest_dir, exist_ok=True)
    filepath = os.path.join(dest_dir, filename)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
    return None


async def handle_webhook_event(payload: dict):
    """Обрабатывает входящие события от Viber.

    ВАЖНО (ограничение Viber Bot API): бот получает события только из диалогов,
    которые пользователь сам начал с этим ботом (нажал кнопку подписки/написал
    первым). Прочитать существующую личную переписку пользователя или историю
    до момента запуска бота через официальный API невозможно — у Viber нет
    аналога MTProto userbot. Рабочее решение в рамках официального API:
    бот копит входящие сообщения и медиа по мере их поступления, начиная
    с момента, когда пользователь начал диалог с ботом."""

    event = payload.get("event")

    if event == "conversation_started":
        user = payload.get("user", {})
        viber_storage.upsert_chat(user.get("id"), user.get("name", "Без имени"), user.get("avatar"))
        return

    if event != "message":
        return

    sender = payload.get("sender", {})
    user_id = sender.get("id")
    name = sender.get("name", "Без имени")
    viber_storage.upsert_chat(user_id, name, sender.get("avatar"))

    message = payload.get("message", {})
    msg_type = message.get("type")
    text = message.get("text")
    media_url = None
    media_type = None

    if msg_type == "picture":
        remote_url = message.get("media")
        if remote_url:
            ts = payload.get("timestamp", int(datetime.utcnow().timestamp() * 1000))
            filename = f"{ts}.jpg"
            dest_dir = os.path.join(settings.MEDIA_DIR, "viber", str(user_id))
            filepath = await _download_media(remote_url, dest_dir, filename)
            if filepath:
                media_url = f"/api/viber/media/{user_id}/{filename}"
                media_type = "photo"

    viber_storage.add_message(
        user_id,
        {
            "id": str(payload.get("message_token", "")),
            "sender": name,
            "text": text,
            "date": datetime.utcnow().isoformat(),
            "media_url": media_url,
            "media_type": media_type,
            "is_outgoing": False,
        },
    )
