import os


class Settings:
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

    VIBER_BOT_TOKEN = os.getenv("VIBER_BOT_TOKEN", "")
    VIBER_BOT_NAME = os.getenv("VIBER_BOT_NAME", "ChatCollectorBot")
    VIBER_BOT_AVATAR = os.getenv("VIBER_BOT_AVATAR", "")
    VIBER_WEBHOOK_URL = os.getenv("VIBER_WEBHOOK_URL", "")

    SESSIONS_DIR = os.getenv("SESSIONS_DIR", "/app/sessions")
    MEDIA_DIR = os.getenv("MEDIA_DIR", "/app/media")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


settings = Settings()

os.makedirs(settings.SESSIONS_DIR, exist_ok=True)
os.makedirs(settings.MEDIA_DIR, exist_ok=True)
os.makedirs(os.path.join(settings.MEDIA_DIR, "telegram"), exist_ok=True)
os.makedirs(os.path.join(settings.MEDIA_DIR, "viber"), exist_ok=True)
