import os

from telethon import utils
from telethon.errors import (
    ChannelsTooMuchError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat, User

from app.config import settings
from app.session_store import get_client


async def send_code(phone: str) -> str:
    """Запрашивает у Telegram код подтверждения для номера телефона.
    Возвращает phone_code_hash, который нужно передать дальше при вводе кода."""
    client = await get_client(phone)
    result = await client.send_code_request(phone)
    return result.phone_code_hash


async def verify_code(phone: str, code: str, phone_code_hash: str) -> dict:
    """Подтверждает код из SMS/Telegram. Если у аккаунта включена двухфакторная
    аутентификация — вернёт status=password_required, и нужно вызвать verify_password."""
    client = await get_client(phone)
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        return {"status": "ok"}
    except SessionPasswordNeededError:
        return {"status": "password_required"}
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        return {"status": "error", "message": str(e)}


async def verify_password(phone: str, password: str) -> dict:
    client = await get_client(phone)
    try:
        await client.sign_in(password=password)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _entity_type(entity) -> str:
    if isinstance(entity, User):
        return "private"
    if isinstance(entity, Channel):
        return "channel" if entity.broadcast else "supergroup"
    if isinstance(entity, Chat):
        return "group"
    return "unknown"


def _entity_name(entity) -> str:
    if isinstance(entity, User):
        parts = [entity.first_name or "", entity.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        return name or (entity.username or str(entity.id))
    return getattr(entity, "title", str(getattr(entity, "id", "")))


def _parse_identifier(identifier: str):
    """Разбирает то, что ввёл пользователь: @username, t.me/username,
    публичную ссылку или инвайт-ссылку приватного чата (t.me/+HASH,
    t.me/joinchat/HASH). Возвращает (username_or_none, invite_hash_or_none)."""
    identifier = identifier.strip()

    if "joinchat/" in identifier:
        return None, identifier.split("joinchat/")[-1].split("?")[0]
    if "/+" in identifier:
        return None, identifier.split("/+")[-1].split("?")[0]
    if identifier.startswith("+") and len(identifier) > 8:
        return None, identifier[1:]

    username = identifier
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if username.startswith(prefix):
            username = username[len(prefix):]
            break
    return username, None


async def join_chat(phone: str, identifier: str) -> dict:
    """Вступает в публичный канал/группу по username, либо в чат по инвайт-ссылке,
    которую пользователь уже получил (т.е. так же, как ручное вступление в
    приложении Telegram). После вступления чат становится обычным диалогом
    и читается через list_chats/get_messages как любой другой."""
    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")

    username, invite_hash = _parse_identifier(identifier)
    entity = None

    try:
        if invite_hash:
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
                if updates.chats:
                    entity = updates.chats[0]
            except UserAlreadyParticipantError:
                pass
        else:
            entity = await client.get_entity(username)
            try:
                await client(JoinChannelRequest(entity))
            except UserAlreadyParticipantError:
                pass
    except (InviteHashExpiredError, InviteHashInvalidError):
        raise RuntimeError("Ссылка-приглашение недействительна или устарела")
    except ChannelsTooMuchError:
        raise RuntimeError("Превышен лимит каналов/групп для этого аккаунта Telegram")
    except ValueError as e:
        raise RuntimeError(f"Не удалось найти чат по '{identifier}': {e}")

    if entity is None:
        # Уже состояли в чате по инвайт-ссылке — найдём его обычным способом
        entity = await client.get_entity(username) if username else None
    if entity is None:
        raise RuntimeError("Не удалось определить чат после вступления")

    return {
        "id": str(utils.get_peer_id(entity)),
        "name": _entity_name(entity),
        "type": _entity_type(entity),
    }


async def list_chats(phone: str, limit: int = 50) -> list:
    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")

    dialogs = await client.get_dialogs(limit=limit)
    result = []
    for d in dialogs:
        entity = d.entity
        last_text = None
        if d.message:
            last_text = d.message.message or ("[медиа]" if d.message.media else None)
        result.append(
            {
                "id": str(d.id),
                "name": _entity_name(entity),
                "type": _entity_type(entity),
                "unread_count": d.unread_count,
                "last_message": last_text,
                "last_message_date": d.date.isoformat() if d.date else None,
            }
        )
    return result


def _safe_dir_name(chat_id: str) -> str:
    return chat_id.replace("-", "n")


async def get_messages(phone: str, chat_id: str, limit: int = 30) -> list:
    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")

    entity = await client.get_entity(int(chat_id))
    messages = await client.get_messages(entity, limit=limit)

    chat_dir = _safe_dir_name(chat_id)
    media_dir = os.path.join(settings.MEDIA_DIR, "telegram", chat_dir)
    os.makedirs(media_dir, exist_ok=True)

    result = []
    for m in messages:
        sender_name = "—"
        try:
            sender = await m.get_sender()
            if sender is not None:
                if isinstance(sender, User):
                    sender_name = " ".join(p for p in [sender.first_name, sender.last_name] if p) or (
                        sender.username or str(sender.id)
                    )
                else:
                    sender_name = getattr(sender, "title", str(sender.id))
        except Exception:
            pass

        media_url = None
        media_type = None

        if m.photo:
            filename = f"{m.id}.jpg"
            filepath = os.path.join(media_dir, filename)
            if not os.path.exists(filepath):
                try:
                    await client.download_media(m, file=filepath)
                except Exception:
                    filepath = None
            if filepath and os.path.exists(filepath):
                media_url = f"/api/telegram/media/{chat_dir}/{filename}"
                media_type = "photo"
        elif m.document and m.document.mime_type and m.document.mime_type.startswith("image/"):
            filename = f"{m.id}_{m.document.id}.jpg"
            filepath = os.path.join(media_dir, filename)
            if not os.path.exists(filepath):
                try:
                    await client.download_media(m, file=filepath)
                except Exception:
                    filepath = None
            if filepath and os.path.exists(filepath):
                media_url = f"/api/telegram/media/{chat_dir}/{filename}"
                media_type = "image"

        result.append(
            {
                "id": str(m.id),
                "sender": sender_name,
                "text": m.message or None,
                "date": m.date.isoformat() if m.date else "",
                "media_url": media_url,
                "media_type": media_type,
                "is_outgoing": bool(m.out),
            }
        )

    result.reverse()  # от старых к новым, удобно для отображения в чате
    return result
