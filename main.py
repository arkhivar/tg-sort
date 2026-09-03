from __future__ import annotations

from flask import Flask, jsonify, render_template, request
import os
import queue
import threading
import time
from datetime import datetime
from typing import Any

from bot_handler import (
    TelegramBotAPI,
    TelegramBotError,
    TopicStore,
    fetch_emoji_icons,
    sort_topics,
)


app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24))

bot_token = os.environ.get("BOT_TOKEN", "").strip()
bot = TelegramBotAPI(bot_token) if bot_token else None
bot_identity: dict[str, Any] | None = None
bot_identity_error: str | None = None
topic_store = TopicStore()
update_state = {
    "running": False,
    "last_update": None,
    "error": None,
    "observed_topics": 0,
}

task_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
sort_status = {
    "running": False,
    "current_chat": None,
    "progress": 0,
    "total": 0,
    "error": None,
    "logs": [],
}
status_lock = threading.Lock()


def add_log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    with status_lock:
        sort_status["logs"].append(f"[{timestamp}] {message}")
        if len(sort_status["logs"]) > 50:
            sort_status["logs"] = sort_status["logs"][-50:]


def set_status(**values: Any) -> None:
    with status_lock:
        sort_status.update(values)


def remember_update(update: dict[str, Any]) -> None:
    member_update = update.get("my_chat_member")
    if isinstance(member_update, dict):
        chat = member_update.get("chat")
        if isinstance(chat, dict) and topic_store.observe_chat(chat):
            add_log(f"Monitoring chat: {chat.get('title') or chat.get('id')}")

    message = update.get("message")
    if not isinstance(message, dict):
        return

    topic = topic_store.observe_message(message)
    if topic:
        update_state["observed_topics"] += 1

    text = (message.get("text") or "").strip()
    if text.startswith("/topic") and bot and message.get("chat"):
        command = text.split()[0].split("@")[0]
        if command == "/topic":
            thread_id = message.get("message_thread_id")
            reply = (
                f"Topic ID: {thread_id}"
                if thread_id is not None
                else "This message is in the General topic; it has no regular topic ID."
            )
            try:
                bot.send_message(
                    message["chat"]["id"],
                    reply,
                    int(thread_id) if thread_id is not None else None,
                )
            except TelegramBotError as exc:
                # A command in General cannot always be sent with a thread ID.
                # The discovery data is already recorded; do not stop polling.
                add_log(f"Could not answer /topic: {exc}")


def update_poller() -> None:
    """Long-poll updates and build the topic roster without a user account."""
    global bot_identity, bot_identity_error
    if not bot:
        return

    try:
        bot_identity = bot.get_me()
        bot_identity_error = None
        add_log(
            f"Connected as @{bot_identity.get('username', bot_identity.get('first_name', 'bot'))}"
        )
    except TelegramBotError as exc:
        bot_identity_error = str(exc)
        update_state["error"] = str(exc)
        return

    offset: int | None = None
    update_state["running"] = True
    while True:
        try:
            updates = bot.get_updates(offset=offset)
            update_state["error"] = None
            for update in updates:
                offset = int(update["update_id"]) + 1
                update_state["last_update"] = datetime.now().isoformat(timespec="seconds")
                remember_update(update)
        except TelegramBotError as exc:
            update_state["error"] = str(exc)
            if exc.error_code == 409:
                update_state["running"] = False
                bot_identity_error = (
                    "Another Telegram consumer or a webhook is using this bot. "
                    "Disable it before using polling."
                )
                return
            time.sleep(5)
        except Exception as exc:
            update_state["error"] = str(exc)
            time.sleep(5)


def background_worker() -> None:
    while True:
        task = task_queue.get()
        if task is None:
            break
        try:
            chat_label = task["chat_id"]
            if task.get("chat_title"):
                chat_label = f"{task['chat_title']} ({task['chat_id']})"
            set_status(
                running=True,
                current_chat=chat_label,
                progress=0,
                total=0,
                error=None,
                logs=[],
            )
            add_log(f"Starting safe bot sort for chat: {chat_label}")
            add_log(f"Sort method: {task['sort_by']}, order: {task['sort_order']}")
            if task["skip_pinned"]:
                add_log("Only topics explicitly marked pinned in the roster will be skipped")
            sort_topics(
                bot=bot,
                store=topic_store,
                bot_user_id=bot_identity["id"],
                chat_id=task["chat_id"],
                sort_status=sort_status,
                add_log=add_log,
                sort_by=task["sort_by"],
                sort_order=task["sort_order"],
                skip_pinned=task["skip_pinned"],
                custom_emoji_order=task["custom_emoji_order"],
                custom_message=task["custom_message"],
            )
            add_log("Sort completed successfully.")
        except Exception as exc:
            set_status(error=str(exc))
            add_log(f"Error: {exc}")
        finally:
            set_status(running=False)
            task_queue.task_done()


if bot:
    threading.Thread(target=update_poller, daemon=True, name="telegram-updates").start()
threading.Thread(target=background_worker, daemon=True, name="sort-worker").start()


def require_bot():
    if not bot:
        return jsonify(
            {
                "error": (
                    "BOT_TOKEN is not configured. Create a bot with @BotFather and "
                    "set the BOT_TOKEN environment variable to its token."
                )
            }
        ), 503
    if bot_identity_error or not bot_identity:
        return jsonify({"error": bot_identity_error or "The bot is not connected yet."}), 503
    return None


def canonical_chat_id(chat_id: str) -> str:
    """Resolve @usernames once so learned numeric topic keys are reusable."""
    chat = bot.get_chat(chat_id)
    topic_store.observe_chat(chat)
    return str(chat["id"])


@app.route("/")
def index():
    return render_template("index.html", bot_configured=bool(bot))


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/auth_status")
def auth_status():
    if not bot:
        return jsonify(
            {
                "configured": False,
                "connected": False,
                "error": "BOT_TOKEN is not configured.",
            }
        )
    return jsonify(
        {
            "configured": True,
            "connected": bool(bot_identity and not bot_identity_error),
            "bot": bot_identity,
            "error": bot_identity_error,
            "poller": update_state,
        }
    )


@app.route("/chats")
def chats():
    """List groups the bot has seen, for the UI group switcher.

    Reads only the local store, so it works even before the bot connects.
    """
    return jsonify({"chats": topic_store.list_chats()})


@app.route("/topics")
def topics():
    missing = require_bot()
    if missing:
        return missing
    chat_id = (request.args.get("chat_id") or "").strip()
    if not chat_id:
        return jsonify({"error": "Chat ID is required"}), 400
    try:
        chat_id = canonical_chat_id(chat_id)
    except TelegramBotError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "topics": topic_store.list_for_chat(chat_id),
            "can_enumerate_historical": False,
            "note": (
                "The Bot API does not provide a method to list historical group "
                "topics. These are topics learned from updates or imported manually."
            ),
        }
    )


@app.route("/import_topics", methods=["POST"])
def import_topics():
    missing = require_bot()
    if missing:
        return missing
    data = request.get_json(silent=True) or {}
    chat_id = str(data.get("chat_id") or "").strip()
    imported = data.get("topics")
    if not chat_id or not isinstance(imported, list) or not imported:
        return jsonify({"error": "chat_id and a non-empty topics list are required"}), 400
    try:
        chat_id = canonical_chat_id(chat_id)
        saved = topic_store.import_topics(chat_id, imported)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "success", "topics": saved})


@app.route("/fetch_emojis", methods=["POST"])
def fetch_emojis_route():
    missing = require_bot()
    if missing:
        return missing
    data = request.get_json(silent=True) or {}
    chat_id = str(data.get("chat_id") or "").strip()
    if not chat_id:
        return jsonify({"error": "Chat ID is required"}), 400
    try:
        chat_id = canonical_chat_id(chat_id)
        return jsonify({"emojis": fetch_emoji_icons(topic_store, chat_id, add_log)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/start_sort", methods=["POST"])
def start_sort():
    missing = require_bot()
    if missing:
        return missing
    data = request.get_json(silent=True) or {}
    chat_id = str(data.get("chat_id") or "").strip()
    sort_by = data.get("sort_by", "emoji")
    sort_order = data.get("sort_order", "ascending")
    skip_pinned = bool(data.get("skip_pinned", True))
    custom_emoji_order = data.get("custom_emoji_order")
    custom_message = str(data.get("custom_message") or ".").strip() or "."

    if not chat_id:
        return jsonify({"error": "Chat ID is required"}), 400
    if sort_by not in ("emoji", "alphabetical", "custom"):
        return jsonify({"error": "Invalid sort method"}), 400
    if sort_order not in ("ascending", "descending"):
        return jsonify({"error": "Invalid sort order"}), 400
    if sort_by == "custom" and not custom_emoji_order:
        return jsonify({"error": "Select at least one emoji for custom sorting"}), 400
    if sort_status["running"]:
        return jsonify({"error": "A sort operation is already running"}), 400

    try:
        chat_id = canonical_chat_id(chat_id)
    except TelegramBotError as exc:
        return jsonify({"error": str(exc)}), 400

    chat_info = topic_store.chat_info(chat_id) or {}
    task_queue.put(
        {
            "chat_id": chat_id,
            "chat_title": chat_info.get("title") or "",
            "sort_by": sort_by,
            "sort_order": sort_order,
            "skip_pinned": skip_pinned,
            "custom_emoji_order": custom_emoji_order,
            "custom_message": custom_message[:200],
        }
    )
    return jsonify({"status": "queued", "message": "Sort operation queued"})


@app.route("/status")
def status():
    with status_lock:
        return jsonify(dict(sort_status))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)