"""Telegram Bot API integration.

This module deliberately uses the HTTPS Bot API instead of MTProto.  A regular
bot token is all that is needed; no API_ID, API_HASH, phone number, or user
session is ever used.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable


class TelegramBotError(Exception):
    """An error returned by the Telegram Bot API."""

    def __init__(
        self,
        description: str,
        error_code: int | None = None,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__(description)
        self.description = description
        self.error_code = error_code
        self.parameters = parameters or {}


class TelegramBotAPI:
    """Minimal, dependency-free client for the Bot API."""

    def __init__(self, token: str):
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}/"

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> Any:
        encoded: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value, separators=(",", ":"))
            else:
                encoded[key] = str(value).lower() if isinstance(value, bool) else str(value)

        request = urllib.request.Request(
            self.base_url + method,
            data=urllib.parse.urlencode(encoded).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise TelegramBotError(f"Telegram HTTP error {exc.code}", exc.code) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TelegramBotError(f"Could not reach Telegram: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise TelegramBotError("Telegram returned an invalid response") from exc

        if not payload.get("ok"):
            raise TelegramBotError(
                payload.get("description", "Telegram request failed"),
                payload.get("error_code"),
                payload.get("parameters"),
            )
        return payload.get("result")

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe")

    def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 25,
    ) -> list[dict[str, Any]]:
        return self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "my_chat_member"],
            },
            timeout=timeout + 10,
        )

    def get_chat(self, chat_id: str | int) -> dict[str, Any]:
        return self.call("getChat", {"chat_id": chat_id})

    def get_chat_member(self, chat_id: str | int, user_id: int) -> dict[str, Any]:
        return self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        topic_id: int | None = None,
    ) -> dict[str, Any]:
        return self.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "message_thread_id": topic_id,
                "text": text,
                "disable_notification": True,
            },
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TopicStore:
    """Small JSON-backed cache of known chats and topic metadata.

    Bot API updates can reveal a topic as the bot sees messages in it.  The
    store also accepts manually imported topic rows for topics that existed
    before the bot was added.  A per-chat roster powers the group switcher
    in the web UI.
    """

    def __init__(self, path: str = "topics.json"):
        self.path = path
        self._lock = threading.Lock()
        self._chats: dict[str, dict[str, Any]] = {}
        self._topics: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        if "topics" in data or "chats" in data:
            if isinstance(data.get("topics"), dict):
                self._topics = data["topics"]
            if isinstance(data.get("chats"), dict):
                self._chats = data["chats"]
            return
        # Legacy flat schema: {chat_id: {topic_id: topic}}.
        self._topics = data
        for chat_key, chat_topics in data.items():
            if not isinstance(chat_topics, dict):
                continue
            title = ""
            last_seen = ""
            for topic in chat_topics.values():
                if not isinstance(topic, dict):
                    continue
                title = title or str(topic.get("chat_title") or "")
                seen = str(topic.get("last_seen") or "")
                if seen > last_seen:
                    last_seen = seen
            now = _now()
            self._chats[chat_key] = {
                "chat_id": chat_key,
                "title": title,
                "first_seen": last_seen or now,
                "last_seen": last_seen or now,
            }

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_path = f"{self.path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(
                {"chats": self._chats, "topics": self._topics},
                file,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(temporary_path, self.path)

    @staticmethod
    def _chat_key(chat_id: str | int) -> str:
        return str(chat_id)

    @staticmethod
    def _topic_key(topic_id: str | int) -> str:
        return str(int(topic_id))

    def observe_chat(self, chat: dict[str, Any]) -> dict[str, Any] | None:
        """Record a chat the bot has seen (from messages or my_chat_member)."""
        chat_id = chat.get("id")
        if chat_id is None:
            return None
        chat_key = self._chat_key(chat_id)
        now = _now()
        with self._lock:
            entry = self._chats.setdefault(
                chat_key,
                {
                    "chat_id": chat_key,
                    "title": "",
                    "first_seen": now,
                    "last_seen": now,
                },
            )
            title = chat.get("title") or chat.get("username") or ""
            if title:
                entry["title"] = title
            entry["last_seen"] = now
            self._save()
            return dict(entry)

    def _refresh_chat_locked(self, chat: dict[str, Any]) -> None:
        """observe_chat variant for callers already holding the lock."""
        chat_id = chat.get("id")
        if chat_id is None:
            return
        chat_key = self._chat_key(chat_id)
        now = _now()
        entry = self._chats.setdefault(
            chat_key,
            {
                "chat_id": chat_key,
                "title": "",
                "first_seen": now,
                "last_seen": now,
            },
        )
        title = chat.get("title") or chat.get("username") or ""
        if title:
            entry["title"] = title
        entry["last_seen"] = now

    def chat_info(self, chat_id: str | int) -> dict[str, Any] | None:
        with self._lock:
            entry = self._chats.get(self._chat_key(chat_id))
            return dict(entry) if entry else None

    def list_chats(self) -> list[dict[str, Any]]:
        with self._lock:
            chats = [
                {**entry, "topic_count": len(self._topics.get(chat_key, {}))}
                for chat_key, entry in self._chats.items()
            ]
        return sorted(
            chats,
            key=lambda item: (
                (item.get("title") or "").casefold(),
                str(item.get("chat_id")),
            ),
        )

    def observe_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        chat = message.get("chat") or {}
        thread_id = message.get("message_thread_id")
        if not chat or thread_id is None:
            return None

        chat_key = self._chat_key(chat.get("id"))
        try:
            topic_key = self._topic_key(thread_id)
        except (TypeError, ValueError):
            return None

        created = message.get("forum_topic_created") or {}
        closed = "forum_topic_closed" in message
        reopened = "forum_topic_reopened" in message
        with self._lock:
            chat_topics = self._topics.setdefault(chat_key, {})
            topic = chat_topics.setdefault(
                topic_key,
                {
                    "topic_id": int(thread_id),
                    "title": "",
                    "emoji_id": None,
                    "pinned": False,
                    "closed": False,
                    "source": "update",
                },
            )
            if created.get("name"):
                topic["title"] = created["name"]
            if created.get("icon_custom_emoji_id"):
                topic["emoji_id"] = str(created["icon_custom_emoji_id"])
            if closed:
                topic["closed"] = True
            elif reopened:
                topic["closed"] = False
            topic["last_seen"] = _now()
            topic["chat_title"] = chat.get("title") or chat.get("username") or ""
            self._refresh_chat_locked(chat)
            self._save()
            return dict(topic)

    def list_for_chat(self, chat_id: str | int) -> list[dict[str, Any]]:
        with self._lock:
            topics = list(self._topics.get(self._chat_key(chat_id), {}).values())
        return sorted(topics, key=lambda topic: int(topic["topic_id"]))

    def import_topics(
        self,
        chat_id: str | int,
        topics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        chat_key = self._chat_key(chat_id)
        with self._lock:
            chat_topics = self._topics.setdefault(chat_key, {})
            for item in topics:
                try:
                    topic_id = int(str(item.get("topic_id", "")).strip())
                except (TypeError, ValueError):
                    raise ValueError("Every topic must have a numeric topic_id")
                if topic_id < 1:
                    raise ValueError("Topic IDs must be positive integers")
                emoji_id = item.get("emoji_id")
                if emoji_id in ("", None):
                    emoji_id = None
                else:
                    emoji_id = str(emoji_id).strip()
                    if not emoji_id.isdigit():
                        raise ValueError(f"Invalid emoji_id for topic {topic_id}")
                existing = chat_topics.get(str(topic_id), {})
                chat_topics[str(topic_id)] = {
                    **existing,
                    "topic_id": topic_id,
                    "title": str(item.get("title") or existing.get("title") or "").strip(),
                    "emoji_id": emoji_id or existing.get("emoji_id"),
                    "pinned": bool(item.get("pinned", existing.get("pinned", False))),
                    "source": "import",
                    "last_seen": _now(),
                }
            self._refresh_chat_locked({"id": chat_id})
            self._save()
        return self.list_for_chat(chat_id)


def validate_chat_for_sort(
    bot: TelegramBotAPI,
    chat_id: str,
    bot_user_id: int,
) -> dict[str, Any]:
    """Check that the target is a forum-capable chat and the bot is an admin."""
    chat = bot.get_chat(chat_id)
    if chat.get("type") not in ("supergroup", "group"):
        raise TelegramBotError(
            "The target must be a Telegram group or supergroup with forum topics."
        )

    member = bot.get_chat_member(chat_id, bot_user_id)
    if member.get("status") not in ("administrator", "creator"):
        raise TelegramBotError(
            "Add the bot to the group as an administrator before sorting topics."
        )
    if member.get("status") == "administrator" and not member.get("can_manage_topics"):
        raise TelegramBotError(
            "The bot needs the Manage Topics administrator permission to sort safely."
        )
    return chat


def fetch_emoji_icons(
    store: TopicStore,
    chat_id: str,
    add_log: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Return emoji metadata from the locally known/imported topic roster."""
    topics = store.list_for_chat(chat_id)
    if not topics:
        raise TelegramBotError(
            "No topics are known yet. Import a topic roster or let the bot observe "
            "messages in the topics first."
        )

    emoji_map: dict[str, dict[str, Any]] = {}
    for topic in topics:
        emoji_id = topic.get("emoji_id")
        if not emoji_id:
            continue
        if emoji_id not in emoji_map:
            emoji_map[emoji_id] = {
                "emoji_id": emoji_id,
                "count": 0,
                "example_title": topic.get("title") or "Untitled",
            }
        emoji_map[emoji_id]["count"] += 1

    emojis = sorted(emoji_map.values(), key=lambda item: int(item["emoji_id"]))
    add_log(f"Found {len(emojis)} emoji icons in the known topic roster")
    return emojis


def sort_topics(
    bot: TelegramBotAPI,
    store: TopicStore,
    bot_user_id: int,
    chat_id: str,
    sort_status: dict[str, Any],
    add_log: Callable[[str], None],
    sort_by: str = "emoji",
    sort_order: str = "ascending",
    skip_pinned: bool = True,
    custom_emoji_order: list[str] | None = None,
    custom_message: str = ".",
) -> None:
    """Send a quiet message to each known topic in the requested order."""
    validate_chat_for_sort(bot, chat_id, bot_user_id)
    topics = store.list_for_chat(chat_id)
    if not topics:
        raise TelegramBotError(
            "The Bot API cannot list historical group topics. Import their topic "
            "IDs first, or let the bot learn them from updates."
        )

    if skip_pinned:
        pinned_topics = [topic for topic in topics if topic.get("pinned")]
        topics_to_sort = [topic for topic in topics if not topic.get("pinned")]
        if pinned_topics:
            add_log(f"Skipping {len(pinned_topics)} topic(s) marked pinned in the roster")
    else:
        topics_to_sort = topics

    if sort_by == "alphabetical":
        topics_to_sort.sort(
            key=lambda topic: (topic.get("title") or "").casefold(),
            reverse=sort_order == "descending",
        )
    elif sort_by == "custom":
        priority = {
            str(emoji_id): index
            for index, emoji_id in enumerate(custom_emoji_order or [])
        }
        topics_to_sort = [
            topic for topic in topics_to_sort if str(topic.get("emoji_id")) in priority
        ]
        topics_to_sort.sort(key=lambda topic: priority[str(topic.get("emoji_id"))])
    else:
        topics_to_sort.sort(
            key=lambda topic: int(topic.get("emoji_id") or 0),
            reverse=sort_order == "descending",
        )

    if not topics_to_sort:
        raise TelegramBotError("No topics match the selected sorting options.")

    sort_status["total"] = len(topics_to_sort)
    add_log(f"Sending a quiet marker to {len(topics_to_sort)} topic(s)")
    for index, topic in enumerate(topics_to_sort):
        topic_id = int(topic["topic_id"])
        try:
            bot.send_message(chat_id, custom_message, topic_id)
            sort_status["progress"] = index + 1
            add_log(
                f"Sent marker to topic {topic_id} "
                f"({index + 1}/{len(topics_to_sort)})"
            )
        except TelegramBotError as exc:
            retry_after = exc.parameters.get("retry_after")
            if retry_after:
                add_log(f"Telegram rate limit: waiting {retry_after} seconds")
                time.sleep(min(int(retry_after), 120))
                bot.send_message(chat_id, custom_message, topic_id)
                sort_status["progress"] = index + 1
                add_log(f"Sent marker to topic {topic_id} after rate limit")
            else:
                add_log(f"Could not send to topic {topic_id}: {exc}")
                sort_status["progress"] = index + 1
