import asyncio
import logging
import os
from typing import Optional
from urllib.parse import quote

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

from app import rich
from app.config import settings
from app.session_store import get_client

log = logging.getLogger("uvicorn.error")


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
            last_text = _message_text(d.message) or _media_label(d.message)
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


# ---------------------------------------------------------------------------
# Медиа и сообщения
# ---------------------------------------------------------------------------

_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(5)  # не качаем сотни файлов одновременно
_file_locks: dict = {}                      # чтобы один файл не качался дважды сразу


def _poll_question(m) -> str:
    q = m.poll.poll.question
    return getattr(q, "text", q) or ""


def _media_label(m) -> Optional[str]:
    """Короткая текстовая метка для медиа (для превью реплаев, списка чатов
    и сообщений, у которых нечего показать кроме типа вложения)."""
    if m.photo:
        return "[Фото]"
    if m.sticker:
        return "[Стикер]"
    if m.gif:
        return "[GIF]"
    if m.video_note:
        return "[Видеосообщение]"
    if m.video:
        return "[Видео]"
    if m.voice:
        return "[Голосовое сообщение]"
    if m.audio:
        return "[Аудио]"
    if m.document:
        return "[Файл]"
    if m.poll:
        return "[Опрос] " + _poll_question(m)
    if m.geo or m.venue:
        return "[Геопозиция]"
    if m.contact:
        return "[Контакт]"
    if m.dice:
        return "[Кубик]"
    if m.game:
        return "[Игра]"
    if m.invoice:
        return "[Счёт]"
    if m.web_preview:
        return None  # превью ссылки: сама ссылка уже есть в тексте
    if m.media:
        kind = type(m.media).__name__
        if kind == "MessageMediaStory":
            return "[История]"
        if kind in ("MessageMediaGiveaway", "MessageMediaGiveawayResults"):
            return "[Розыгрыш]"
        if kind == "MessageMediaUnsupported":
            return "[Неподдерживаемое медиа: Telegram не отдаёт его этой версии клиента]"
        if kind in ("MessageMediaEmpty",) or (
            kind == "MessageMediaDocument" and not m.document
        ) or (kind == "MessageMediaPhoto" and not m.photo):
            return "[Медиа недоступно: удалено или истёк срок]"
        # Неизвестный тип: показываем его имя и пишем подробности в лог бэкенда
        log.warning("Неизвестный тип медиа в сообщении %s: %s", getattr(m, "id", "?"), repr(m.media)[:600])
        return f"[Медиа: {kind}]"
    if getattr(m, "action", None):
        return "[Служебное сообщение]"
    return None


def _file_url(phone: str, chat_id: str, message_id: int, download: bool = False, doc_id: Optional[int] = None) -> str:
    url = f"/api/telegram/file?phone={quote(phone)}&chat_id={quote(str(chat_id))}&message_id={message_id}"
    if doc_id:
        url += f"&doc_id={doc_id}"
    return url + "&download=1" if download else url


def _doc_info(doc) -> dict:
    """Имя, mime, размер и длительность документа (для файлов внутри rich_message)."""
    name, duration = None, None
    for a in getattr(doc, "attributes", None) or []:
        kind = type(a).__name__
        if kind == "DocumentAttributeFilename":
            name = a.file_name
        elif kind in ("DocumentAttributeVideo", "DocumentAttributeAudio"):
            duration = getattr(a, "duration", None)
    return {"name": name, "mime": doc.mime_type, "size": doc.size, "duration": duration}


def _rich_blocks_raw(m):
    """Простые блоки из rich_message сообщения (без скачивания файлов) или None."""
    rm = getattr(m, "rich_message", None)
    if rm is None:
        return None
    return rich.convert_blocks(rm.blocks)


def _message_text(m) -> str:
    """Текст сообщения: обычный или, если его нет, текст «богатого» поста."""
    if m.message:
        return m.message
    blocks = _rich_blocks_raw(m)
    return rich.blocks_plain_text(blocks) if blocks else ""


async def _build_rich(client, m, phone, chat_id, chat_dir, media_dir) -> Optional[list]:
    """Блоки «богатого» поста с готовыми ссылками на фото/видео."""
    rm = getattr(m, "rich_message", None)
    if rm is None:
        return None
    base = f"/api/telegram/media/{chat_dir}"
    photos = {p.id: p for p in (rm.photos or []) if hasattr(p, "id")}
    docs = {d.id: d for d in (rm.documents or []) if hasattr(d, "id")}

    out = []
    for b in rich.convert_blocks(rm.blocks):
        kind = b["type"]
        if kind == "photo":
            p = photos.get(b["photo_id"])
            if p is None:
                continue
            name = f"{m.id}_rich_{p.id}.jpg"
            if await _download_to(client, p, os.path.join(media_dir, name)):
                out.append({"type": "photo", "url": f"{base}/{name}", "caption": b["caption"]})
        elif kind in ("video", "audio", "file"):
            d = docs.get(b["doc_id"])
            if d is None:
                continue
            item = {
                "type": "gif" if b.get("gif") else kind,
                "caption": b["caption"],
                "url": _file_url(phone, chat_id, m.id, download=(kind == "file"), doc_id=d.id),
                "thumb": None,
                **_doc_info(d),
            }
            if kind == "video":
                thumb = f"{m.id}_rich_{d.id}_thumb.jpg"
                if await _download_to(client, d, os.path.join(media_dir, thumb), thumb=-1):
                    item["thumb"] = f"{base}/{thumb}"
            out.append(item)
        else:
            out.append(b)
    return out


async def _download_to(client, m, filepath: str, **kwargs) -> bool:
    """Скачивает медиа в filepath (если ещё не скачано). True — файл на месте."""
    if not os.path.exists(filepath):
        async with _DOWNLOAD_SEMAPHORE:
            try:
                await client.download_media(m, file=filepath, **kwargs)
            except Exception:
                return False
    return os.path.exists(filepath)


async def _extract_media(client, m, phone: str, chat_id: str, chat_dir: str, media_dir: str) -> Optional[dict]:
    """Описание вложения сообщения. Лёгкие вещи (фото, превью видео, стикеры)
    скачиваются сразу, тяжёлые (видео, аудио, файлы) — только по запросу
    пользователя через /api/telegram/file."""
    base = f"/api/telegram/media/{chat_dir}"
    f = m.file

    # --- фото ---
    if m.photo:
        name = f"{m.id}.jpg"
        if await _download_to(client, m, os.path.join(media_dir, name)):
            return {"type": "photo", "url": f"{base}/{name}"}
        return None

    # --- стикеры ---
    if m.sticker:
        if f and f.mime_type == "image/webp":
            name = f"{m.id}_sticker.webp"
            if await _download_to(client, m, os.path.join(media_dir, name)):
                return {"type": "sticker", "url": f"{base}/{name}"}
        return None  # анимированные (tgs/webm) — покажем меткой

    # --- видео / GIF / кружочки (gif проверяем раньше video: у gif тоже есть атрибут video) ---
    if m.gif or m.video or m.video_note:
        kind = "gif" if m.gif else "video"
        item = {
            "type": kind,
            "url": _file_url(phone, chat_id, m.id),
            "mime": f.mime_type if f else None,
            "size": f.size if f else None,
            "duration": f.duration if f else None,
            "thumb": None,
        }
        thumb_name = f"{m.id}_thumb.jpg"
        if await _download_to(client, m, os.path.join(media_dir, thumb_name), thumb=-1):
            item["thumb"] = f"{base}/{thumb_name}"
        return item

    # --- голосовые и аудио ---
    if m.voice or m.audio:
        return {
            "type": "audio",
            "url": _file_url(phone, chat_id, m.id),
            "name": (f.name if f else None) or ("Голосовое сообщение" if m.voice else "Аудио"),
            "mime": f.mime_type if f else None,
            "size": f.size if f else None,
            "duration": f.duration if f else None,
        }

    # --- прочие документы ---
    if m.document:
        mime = (f.mime_type if f else None) or ""
        if mime.startswith("image/"):
            name = f"{m.id}_{m.document.id}.jpg"
            if await _download_to(client, m, os.path.join(media_dir, name)):
                return {"type": "image", "url": f"{base}/{name}"}
            return None
        return {
            "type": "file",
            "url": _file_url(phone, chat_id, m.id, download=True),
            "name": (f.name if f else None) or f"file_{m.id}{(f.ext if f else '') or ''}",
            "mime": mime or None,
            "size": f.size if f else None,
        }

    return None


async def _sender_name(m, cache: dict) -> str:
    key = m.sender_id
    if key is not None and key in cache:
        return cache[key]
    name = "—"
    try:
        sender = await m.get_sender()
        if sender is not None:
            name = _entity_name(sender)
    except Exception:
        pass
    if key is not None:
        cache[key] = name
    return name


async def _forward_info(m, cache: dict) -> Optional[dict]:
    """Откуда переслано сообщение: {"name": ..., "date": ...} или None, если не пересылка."""
    hdr = getattr(m, "fwd_from", None)
    if hdr is None:
        return None
    date = getattr(hdr, "date", None)
    # from_name заполнен, когда автор скрыл аккаунт в настройках приватности
    name = getattr(hdr, "from_name", None)
    if not name:
        peer = getattr(hdr, "from_id", None)
        key = f"fwd:{peer!r}" if peer is not None else None
        if key and key in cache:
            name = cache[key]
        else:
            fwd = getattr(m, "forward", None)
            try:
                entity = await fwd.get_sender() if fwd else None
                if entity is None and fwd:
                    entity = await fwd.get_chat()  # пересылка поста из канала/чата
                if entity is not None:
                    name = _entity_name(entity)
            except Exception:
                pass
            name = name or getattr(hdr, "post_author", None)
            if key and name:
                cache[key] = name
    return {"name": name or "Неизвестный источник", "date": date.isoformat() if date else None}


def _reply_target_id(m) -> Optional[int]:
    """id сообщения, на которое это сообщение отвечает (или None).
    В форумах (темах) у обычных сообщений reply_to указывает на корень темы —
    это не настоящий реплай, его пропускаем."""
    rt = getattr(m, "reply_to", None)
    if rt is None or not getattr(rt, "reply_to_msg_id", None):
        return None
    if getattr(rt, "reply_to_peer_id", None):
        return None  # ответ на сообщение из другого чата
    if getattr(rt, "forum_topic", False) and not getattr(rt, "reply_to_top_id", None):
        return None
    return rt.reply_to_msg_id


async def _process_message(client, m, phone, chat_id, chat_dir, media_dir, name_cache) -> dict:
    media = await _extract_media(client, m, phone, chat_id, chat_dir, media_dir)
    rich_blocks = await _build_rich(client, m, phone, chat_id, chat_dir, media_dir)
    return {
        "id": m.id,
        "grouped_id": m.grouped_id,
        "sender": await _sender_name(m, name_cache),
        "text": _message_text(m) or None,
        "rich": rich_blocks or None,
        "forward": await _forward_info(m, name_cache),
        "date": m.date.isoformat() if m.date else "",
        "is_outgoing": bool(m.out),
        "media": media,
        # метка нужна, только если показать вложение нечем
        "label": None if (media or rich_blocks) else _media_label(m),
        "reply_id": _reply_target_id(m),
    }


async def _load_reply_previews(client, entity, reply_ids: set, loaded: dict, name_cache: dict) -> dict:
    """Возвращает {id: превью} для сообщений, на которые есть реплаи.
    Недостающие в загруженной пачке подтягиваются одним-двумя запросами."""
    found = {rid: loaded[rid] for rid in reply_ids if rid in loaded}
    missing = [rid for rid in reply_ids if rid not in found]
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        try:
            fetched = await client.get_messages(entity, ids=chunk)
        except Exception:
            continue
        for rid, msg in zip(chunk, fetched):
            if msg is not None:
                found[rid] = msg

    previews = {}
    for rid in reply_ids:
        msg = found.get(rid)
        if msg is None:
            previews[rid] = {"id": rid, "missing": True}
            continue
        text = _message_text(msg).strip()
        label = None if text else _media_label(msg)
        previews[rid] = {
            "id": rid,
            "missing": False,
            "sender": await _sender_name(msg, name_cache),
            "text": (text[:150] + "…") if len(text) > 150 else text or None,
            "label": label,
        }
    return previews


async def get_messages(phone: str, chat_id: str, limit: int = 30) -> list:
    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")

    entity = await client.get_entity(int(chat_id))
    messages = list(await client.get_messages(entity, limit=limit))

    # Если самый старый загруженный пост — кусок альбома, дотягиваем остаток
    # альбома, иначе он отобразится обрезанным.
    if messages and messages[-1].grouped_id:
        gid = messages[-1].grouped_id
        older = await client.get_messages(entity, limit=10, offset_id=messages[-1].id)
        for o in older:
            if o.grouped_id != gid:
                break
            messages.append(o)

    chat_dir = _safe_dir_name(chat_id)
    media_dir = os.path.join(settings.MEDIA_DIR, "telegram", chat_dir)
    os.makedirs(media_dir, exist_ok=True)

    name_cache: dict = {}
    processed = await asyncio.gather(
        *[_process_message(client, m, phone, chat_id, chat_dir, media_dir, name_cache) for m in messages]
    )
    processed.sort(key=lambda p: p["id"])  # от старых к новым

    # --- склеиваем альбомы (общий grouped_id) в одно сообщение ---
    items = []
    albums = {}
    for p in processed:
        gid = p["grouped_id"]
        if gid and gid in albums:
            it = albums[gid]
            it["ids"].append(p["id"])
            if p["media"]:
                it["media"].append(p["media"])
            it["text"] = it["text"] or p["text"]        # подпись может быть не у первого фото
            it["label"] = it["label"] or p["label"]
            it["reply_id"] = it["reply_id"] or p["reply_id"]
            it["rich"] = it["rich"] or p["rich"]
            it["forward"] = it["forward"] or p["forward"]
            continue
        it = {
            "id": p["id"],
            "ids": [p["id"]],
            "sender": p["sender"],
            "text": p["text"],
            "rich": p["rich"],
            "forward": p["forward"],
            "date": p["date"],
            "is_outgoing": p["is_outgoing"],
            "media": [p["media"]] if p["media"] else [],
            "label": p["label"],
            "reply_id": p["reply_id"],
        }
        if gid:
            albums[gid] = it
        items.append(it)

    # --- превью реплаев ---
    reply_ids = {it["reply_id"] for it in items if it["reply_id"]}
    previews = {}
    if reply_ids:
        loaded = {m.id: m for m in messages}
        previews = await _load_reply_previews(client, entity, reply_ids, loaded, name_cache)

    result = []
    for it in items:
        first_url = next((md["url"] for md in it["media"] if md.get("url")), None)
        first_type = it["media"][0]["type"] if it["media"] else None
        result.append(
            {
                "id": str(it["id"]),
                "ids": [str(i) for i in it["ids"]],
                "sender": it["sender"],
                "text": it["text"],
                "rich": it["rich"],
                "forward": it["forward"],
                "date": it["date"],
                "is_outgoing": it["is_outgoing"],
                "media": it["media"],
                "media_url": first_url,       # для обратной совместимости
                "media_type": first_type,
                "placeholder": it["label"] if not (it["media"] or it["rich"]) else None,
                "reply": previews.get(it["reply_id"]) if it["reply_id"] else None,
            }
        )
    return result


async def ensure_media_file(phone: str, chat_id: str, message_id: int, doc_id: Optional[int] = None):
    """Скачивает вложение сообщения при первом обращении и кэширует на диске.
    doc_id — документ из «богатого» поста (rich_message).
    Возвращает (путь, mime-type, имя файла)."""
    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")

    entity = await client.get_entity(int(chat_id))
    m = await client.get_messages(entity, ids=message_id)
    if m is None:
        raise FileNotFoundError("Сообщение не найдено")

    if doc_id:
        rm = getattr(m, "rich_message", None)
        doc = next((d for d in ((rm.documents if rm else None) or []) if getattr(d, "id", None) == doc_id), None)
        if doc is None:
            raise FileNotFoundError("Документ не найден в сообщении")
        ext = utils.get_extension(doc) or ""
        info = _doc_info(doc)
        target, mime = doc, info["mime"] or "application/octet-stream"
        filename = info["name"] or f"{doc_id}{ext}"
        cache_name = f"{message_id}_doc{doc_id}{ext}"
    else:
        if not m.file:
            raise FileNotFoundError("У сообщения нет вложения")
        ext = m.file.ext or ""
        target, mime = m, m.file.mime_type or "application/octet-stream"
        filename = m.file.name or f"{message_id}{ext}"
        cache_name = f"{message_id}_file{ext}"

    media_dir = os.path.join(settings.MEDIA_DIR, "telegram", _safe_dir_name(chat_id))
    os.makedirs(media_dir, exist_ok=True)
    path = os.path.join(media_dir, cache_name)

    if os.path.exists(path):
        return path, mime, filename

    lock = _file_locks.setdefault(path, asyncio.Lock())
    async with lock:
        if not os.path.exists(path):
            tmp = path + ".part"
            await client.download_media(target, file=tmp)
            os.replace(tmp, path)  # атомарно, чтобы не отдать недокачанный файл
    return path, mime, filename


async def get_raw_message(phone: str, chat_id: str, message_id: int) -> dict:
    """Диагностика: версия Telethon и «сырое» сообщение так, как его отдал Telegram."""
    import json

    import telethon
    from telethon.tl.alltlobjects import LAYER

    client = await get_client(phone)
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована. Сначала выполните вход.")
    entity = await client.get_entity(int(chat_id))
    m = await client.get_messages(entity, ids=message_id)
    if m is None:
        raise FileNotFoundError("Сообщение не найдено")
    return {
        "telethon_version": telethon.__version__,
        "api_layer": LAYER,
        "media_class": type(m.media).__name__ if m.media else None,
        "message": json.loads(json.dumps(m.to_dict(), default=str)),
    }
