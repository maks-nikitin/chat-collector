import json
import os
import threading

from app.config import settings

_LOCK = threading.Lock()
_STORAGE_FILE = os.path.join(settings.MEDIA_DIR, "viber", "storage.json")


class ViberStorage:
    """Простое JSON-файловое хранилище переписки Viber.
    Файл лежит в volume с медиафайлами, поэтому переживает пересборку контейнера."""

    def __init__(self):
        os.makedirs(os.path.dirname(_STORAGE_FILE), exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(_STORAGE_FILE):
            try:
                with open(_STORAGE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        with open(_STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def upsert_chat(self, user_id: str, name: str, avatar: str = None):
        with _LOCK:
            if user_id not in self._data:
                self._data[user_id] = {"name": name, "avatar": avatar, "messages": []}
            else:
                self._data[user_id]["name"] = name
            self._save()

    def add_message(self, user_id: str, message: dict):
        with _LOCK:
            if user_id not in self._data:
                self._data[user_id] = {"name": "Без имени", "avatar": None, "messages": []}
            self._data[user_id]["messages"].append(message)
            self._save()

    def list_chats(self) -> list:
        with _LOCK:
            out = []
            for uid, v in self._data.items():
                last = v["messages"][-1] if v["messages"] else None
                out.append(
                    {
                        "id": uid,
                        "name": v.get("name", "Без имени"),
                        "type": "viber_private",
                        "unread_count": 0,
                        "last_message": last["text"] if last else None,
                        "last_message_date": last["date"] if last else None,
                    }
                )
            return out

    def get_messages(self, user_id: str, limit: int = 30) -> list:
        with _LOCK:
            msgs = self._data.get(user_id, {}).get("messages", [])
            return msgs[-limit:]


viber_storage = ViberStorage()
