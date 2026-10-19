from typing import Optional
from pydantic import BaseModel, Field


class SendCodeRequest(BaseModel):
    phone: str = Field(
        ...,
        description="Номер телефона в международном формате",
        examples=["+79991234567"],
    )


class VerifyCodeRequest(BaseModel):
    phone: str = Field(..., description="Тот же номер телефона что на шаге 1", examples=["+79991234567"])
    code: str = Field(..., description="Код из SMS или приложения Telegram", examples=["12345"])
    phone_code_hash: str = Field(
        ...,
        description="Токен сессии, полученный в ответе на шаге 1 (поле phone_code_hash)",
        examples=["abc123xyz"],
    )


class VerifyPasswordRequest(BaseModel):
    phone: str = Field(..., description="Номер телефона", examples=["+79991234567"])
    password: str = Field(..., description="Облачный пароль двухфакторной аутентификации Telegram")


class JoinChatRequest(BaseModel):
    phone: str = Field(..., description="Номер телефона авторизованного пользователя", examples=["+79991234567"])
    identifier: str = Field(
        ...,
        description="Username, ссылка t.me/username или инвайт-ссылка t.me/+HASH",
        examples=["@durov"],
    )


class ChatOut(BaseModel):
    id: str = Field(..., description="Уникальный идентификатор чата")
    name: str = Field(..., description="Название чата или имя собеседника")
    type: str = Field(..., description="Тип: private, group, supergroup, channel")
    unread_count: int = Field(0, description="Количество непрочитанных сообщений")
    last_message: Optional[str] = Field(None, description="Текст последнего сообщения")
    last_message_date: Optional[str] = Field(None, description="Дата последнего сообщения ISO 8601")


class MediaOut(BaseModel):
    type: str = Field(..., description="photo, image, sticker, video, gif, audio, file")
    url: Optional[str] = Field(None, description="URL для показа/воспроизведения/скачивания")
    thumb: Optional[str] = Field(None, description="Превью (для видео)")
    name: Optional[str] = Field(None, description="Имя файла (для аудио и файлов)")
    mime: Optional[str] = Field(None, description="MIME-тип")
    size: Optional[int] = Field(None, description="Размер в байтах")
    duration: Optional[float] = Field(None, description="Длительность в секундах (видео, аудио)")


class ReplyOut(BaseModel):
    id: int = Field(..., description="ID сообщения, на которое отвечают")
    missing: bool = Field(False, description="True если исходное сообщение удалено или недоступно")
    sender: Optional[str] = Field(None, description="Автор исходного сообщения")
    text: Optional[str] = Field(None, description="Фрагмент текста исходного сообщения")
    label: Optional[str] = Field(None, description="Метка вложения, если у исходного сообщения нет текста")


class ForwardOut(BaseModel):
    name: str = Field(..., description="Источник пересланного сообщения (автор, канал или чат)")
    date: Optional[str] = Field(None, description="Дата оригинального сообщения (ISO 8601)")


class MessageOut(BaseModel):
    id: str = Field(..., description="Идентификатор сообщения (для альбома — самого раннего сообщения)")
    ids: list[str] = Field(default_factory=list, description="Все id сообщений Telegram, вошедших в это сообщение")
    sender: str = Field(..., description="Имя отправителя")
    text: Optional[str] = Field(None, description="Текст сообщения или подпись к медиа")
    date: str = Field(..., description="Дата и время в формате ISO 8601")
    media: list[MediaOut] = Field(default_factory=list, description="Вложения (у альбома — несколько)")
    rich: Optional[list[dict]] = Field(
        None,
        description="Блоки «богатого» поста (заголовки, абзацы с форматированием, фото, списки). "
                    "Если есть — фронтенд рисует их вместо text",
    )
    media_url: Optional[str] = Field(None, description="URL первого вложения (для обратной совместимости)")
    media_type: Optional[str] = Field(None, description="Тип первого вложения (для обратной совместимости)")
    placeholder: Optional[str] = Field(None, description="Метка, если вложение показать нечем")
    reply: Optional[ReplyOut] = Field(None, description="Превью сообщения, на которое это — ответ")
    forward: Optional[ForwardOut] = Field(None, description="Источник, если сообщение переслано (иначе null)")
    is_outgoing: bool = Field(False, description="True если сообщение отправлено вами")


class ViberImportRequest(BaseModel):
    chat_id: str = Field(
        ...,
        description="Идентификатор чата/собеседника в Viber (пока можно любой уникальный текст, например номер телефона)",
        examples=["+380991234567"],
    )
    chat_name: str = Field(..., description="Имя собеседника или название чата", examples=["Иван Иванов"])
    sender: str = Field(..., description="Имя отправителя этого сообщения")
    text: Optional[str] = Field(None, description="Текст сообщения")
    is_outgoing: bool = Field(False, description="True если сообщение отправили вы, а не собеседник")
    date: Optional[str] = Field(None, description="Дата и время ISO 8601. Если не передать — подставится текущее время сервера")
