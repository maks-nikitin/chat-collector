# Chat Collector — Telegram

Веб-приложение для просмотра переписки из Telegram в едином интерфейсе.
Подключается к вашему аккаунту через протокол **MTProto** (без ботов, от имени обычного пользователя).

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)

---

## Возможности

- Авторизация через номер телефона + код подтверждения + 2FA
- Просмотр всех диалогов: личные переписки, группы, каналы
- Загрузка последних N сообщений (до 500) из любого чата
- Просмотр изображений из сообщений
- Вступление в чаты по username или инвайт-ссылке
- REST API с документацией Swagger UI
- Postman-коллекция для тестирования

---

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Бэкенд | Python 3.11, FastAPI, Telethon |
| Прокси-сервер | Node.js, Express.js |
| Фронтенд | HTML, CSS, JavaScript, jQuery |
| Контейнеризация | Docker, Docker Compose |

---

## Быстрый старт

### 1. Получи Telegram API credentials

Зайди на [my.telegram.org](https://my.telegram.org) → **API development tools** → создай приложение → скопируй `api_id` и `api_hash`.

### 2. Создай файл .env

```bash
cp .env.example .env
```

Открой `.env` и заполни:

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
```

### 3. Запусти приложение

```bash
docker compose up --build
```

### 4. Открой в браузере

| URL | Что там |
|-----|---------|
| http://localhost:3000 | Веб-интерфейс |
| http://localhost:8001/docs | Swagger UI (документация API) |
| http://localhost:8001/redoc | ReDoc (альтернативная документация) |

---

## Структура проекта

```
chat-collector/
├── docker-compose.yml
├── .env.example
├── Chat_Collector.postman_collection.json
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI роуты
│       ├── config.py           # конфигурация
│       ├── schemas.py          # Pydantic-модели
│       ├── session_store.py    # управление сессиями Telethon
│       └── telegram_service.py # логика Telegram
├── node-server/
│   ├── Dockerfile
│   ├── package.json
│   └── server.js
└── frontend/
    ├── index.html
    ├── css/style.css
    └── js/app.js
```

---

## API эндпоинты

### Авторизация

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/telegram/auth/send_code` | Отправить код на телефон |
| POST | `/api/telegram/auth/verify_code` | Подтвердить код |
| POST | `/api/telegram/auth/verify_password` | Ввести пароль 2FA |
| POST | `/api/telegram/auth/logout` | Выйти из аккаунта |

### Чаты

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/telegram/chats` | Список всех диалогов |
| POST | `/api/telegram/join` | Вступить в чат |

### Сообщения

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/telegram/messages` | Получить сообщения из чата |
| GET | `/api/telegram/media/{chat}/{file}` | Получить медиафайл |

---

## Тестирование через Postman

1. Скачай [Postman](https://postman.com)
2. **Import** → выбери файл `Chat_Collector.postman_collection.json`
3. В настройках коллекции (**Variables**) замени `phone` на свой номер телефона
4. Запускай запросы по порядку начиная с папки «Авторизация Telegram»

---

## Примечание о Viber

Viber с февраля 2024 года прекратил бесплатную регистрацию ботов.
Интеграция Viber через Bot API требует коммерческого договора.
Попытка чтения локальной базы `viber.db` показала, что современные версии
Viber Desktop используют нестандартное шифрование SQLCipher с закрытыми параметрами.
