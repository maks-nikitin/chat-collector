import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import telegram_service
from app.config import settings
from app.schemas import (
    JoinChatRequest,
    SendCodeRequest,
    VerifyCodeRequest,
    VerifyPasswordRequest,
    ViberImportRequest,
)
from app.storage import viber_storage

app = FastAPI(
    title="Chat Collector API",
    description="""
## API для сбора сообщений из Telegram

Приложение подключается к вашему аккаунту Telegram через протокол **MTProto** 
(библиотека Telethon) и позволяет просматривать переписку в едином веб-интерфейсе.

### Порядок работы:
1. **Авторизация** — отправьте код на номер телефона, подтвердите его
2. **Чаты** — получите список диалогов или вступите в новый чат
3. **Сообщения** — загрузите историю сообщений из выбранного чата
""",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Система"], summary="Проверка работоспособности сервера")
async def health():
    """Возвращает статус сервера. Используется для проверки что бэкенд запущен и отвечает."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Telegram — Авторизация
# ---------------------------------------------------------------------------

@app.post(
    "/api/telegram/auth/send_code",
    tags=["Авторизация Telegram"],
    summary="Шаг 1 — отправить код подтверждения",
)
async def telegram_send_code(body: SendCodeRequest):
    """
    Запрашивает у Telegram отправку SMS-кода (или кода в приложении) на указанный номер телефона.

    **Возвращает** `phone_code_hash` — токен сессии, который нужно передать на следующем шаге.
    Сохраните его, он понадобится при подтверждении кода.
    """
    try:
        phone_code_hash = await telegram_service.send_code(body.phone)
        return {"status": "code_sent", "phone_code_hash": phone_code_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/api/telegram/auth/verify_code",
    tags=["Авторизация Telegram"],
    summary="Шаг 2 — подтвердить код из Telegram",
)
async def telegram_verify_code(body: VerifyCodeRequest):
    """
    Подтверждает код, полученный на предыдущем шаге.

    **Возможные ответы:**
    - `{"status": "ok"}` — авторизация успешна
    - `{"status": "password_required"}` — у аккаунта включена двухфакторная аутентификация,
      нужно перейти к шагу 3
    """
    result = await telegram_service.verify_code(body.phone, body.code, body.phone_code_hash)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.post(
    "/api/telegram/auth/verify_password",
    tags=["Авторизация Telegram"],
    summary="Шаг 3 — ввести пароль двухфакторной аутентификации (если включена)",
)
async def telegram_verify_password(body: VerifyPasswordRequest):
    """
    Выполняется только если на шаге 2 пришёл ответ `password_required`.

    Вводится облачный пароль (2FA), установленный в настройках Telegram.
    После успешного входа сессия сохраняется в файл `.session` на диске
    и авторизация при следующем запуске не потребуется.
    """
    result = await telegram_service.verify_password(body.phone, body.password)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ---------------------------------------------------------------------------
# Telegram — Чаты
# ---------------------------------------------------------------------------

@app.get(
    "/api/telegram/chats",
    tags=["Чаты Telegram"],
    summary="Получить список диалогов",
)
async def telegram_chats(
    phone: str = Query(..., description="Номер телефона в международном формате, например +79991234567"),
    limit: int = Query(50, description="Максимальное количество чатов (по умолчанию 50)"),
):
    """
    Возвращает список всех диалогов авторизованного пользователя:
    личные переписки, группы, супергруппы и каналы.

    Для каждого чата возвращается:
    - `id` — уникальный идентификатор (используется для получения сообщений)
    - `name` — название чата или имя собеседника
    - `type` — тип: `private`, `group`, `supergroup`, `channel`
    - `unread_count` — количество непрочитанных сообщений
    - `last_message` — текст последнего сообщения
    """
    try:
        return {"chats": await telegram_service.list_chats(phone, limit)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/api/telegram/join",
    tags=["Чаты Telegram"],
    summary="Вступить в чат по ссылке или username",
)
async def telegram_join(body: JoinChatRequest):
    """
    Вступает в публичный канал или группу по username, либо в приватный чат по инвайт-ссылке.

    **Форматы `identifier`:**
    - `@username` или `username`
    - `https://t.me/username`
    - `https://t.me/+HASH` — приватная инвайт-ссылка
    - `https://t.me/joinchat/HASH` — старый формат инвайт-ссылки

    После вступления чат появляется в списке `/api/telegram/chats`.
    """
    try:
        return await telegram_service.join_chat(body.phone, body.identifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Telegram — Сообщения
# ---------------------------------------------------------------------------

@app.get(
    "/api/telegram/messages",
    tags=["Сообщения Telegram"],
    summary="Получить последние N сообщений из чата",
)
async def telegram_messages(
    phone: str = Query(..., description="Номер телефона авторизованного пользователя"),
    chat_id: str = Query(..., description="ID чата из списка /api/telegram/chats"),
    limit: int = Query(30, ge=1, le=500, description="Количество сообщений от 1 до 500"),
):
    """
    Загружает последние `limit` сообщений из указанного чата.

    Для каждого сообщения возвращается:
    - `id` — идентификатор сообщения
    - `sender` — имя отправителя
    - `text` — текст сообщения (null если только медиа)
    - `date` — дата и время в формате ISO 8601
    - `media_url` — ссылка на изображение (null если нет медиа)
    - `is_outgoing` — true если сообщение отправлено вами

    Сообщения отсортированы от старых к новым.
    """
    try:
        return {"messages": await telegram_service.get_messages(phone, chat_id, limit)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/api/telegram/media/{chat_dir}/{filename}",
    tags=["Сообщения Telegram"],
    summary="Получить медиафайл из сообщения",
)
async def telegram_media(
    chat_dir: str,
    filename: str,
):
    """
    Отдаёт изображение или другой медиафайл, прикреплённый к сообщению.

    Путь к файлу берётся из поля `media_url` в ответе `/api/telegram/messages`.
    Файлы хранятся локально на сервере в директории `/app/media/telegram/`.
    """
    filepath = os.path.join(settings.MEDIA_DIR, "telegram", chat_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(filepath)

# ---------------------------------------------------------------------------
# Viber — тестовый приём данных 
# ---------------------------------------------------------------------------

@app.post(
    "/api/viber/import",
    tags=["Viber (тест)"],
    summary="Временный приём сообщений Viber, скопированных вручную",
)
async def viber_import(body: ViberImportRequest):
    """
    Тестовый эндпоинт: принимает одно сообщение Viber и складывает его
    в то же хранилище, которым пользуется официальный webhook (app/storage.py).
    Позже коллега сделает свой приём — формат JSON можно оставить тем же.
    """
    viber_storage.upsert_chat(body.chat_id, body.chat_name)
    viber_storage.add_message(
        body.chat_id,
        {
            "id": str(int(datetime.utcnow().timestamp() * 1000)),
            "sender": body.sender,
            "text": body.text,
            "date": body.date or datetime.utcnow().isoformat(),
            "media_url": None,
            "media_type": None,
            "is_outgoing": body.is_outgoing,
        },
    )
    return {"status": "ok"}


@app.get(
    "/api/viber/chats",
    tags=["Viber (тест)"],
    summary="Список собранных Viber-чатов",
)
async def viber_chats():
    return {"chats": viber_storage.list_chats()}


@app.get(
    "/api/viber/messages",
    tags=["Viber (тест)"],
    summary="Сообщения конкретного Viber-чата",
)
async def viber_messages(chat_id: str = Query(..., description="chat_id, который отправляли в /api/viber/import")):
    return {"messages": viber_storage.get_messages(chat_id)}
