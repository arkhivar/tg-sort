# Telegram Topic Sorter

A Flask web app that uses a regular Telegram Bot API token to sort known forum
topics. It does **not** use a user account, MTProto, Telethon, API_ID,
API_HASH, phone number, or a session file.

The rationale for this architecture and the strict rules for reconsidering it
are documented in [EVOLUTION.md](EVOLUTION.md).

Self-hosting instructions are documented in
[DEPLOYMENT.md](DEPLOYMENT.md).

## What it does

- Sorts known topics by emoji ID or title, ascending or descending.
- Supports a manually arranged custom emoji order.
- Skips topics explicitly marked as pinned in the imported roster.
- Sends a quiet marker message to each topic in sorted order.
- Learns topic IDs from incoming Bot API updates.
- Provides `/topic` inside Telegram to report the current topic ID.
- Keeps the bot token server-side in the environment file.

## Important Bot API limitation

The current Bot API supports `message_thread_id` and methods for creating,
editing, closing, reopening, deleting, and unpinning topics. It still does not
provide an equivalent of the MTProto `channels.getForumTopics` method for
listing historical topics in group forums.

Therefore, a regular bot cannot automatically discover every topic that
existed before it was added. This app intentionally sends only to topics in its
known/imported roster:

1. Add the bot to the forum group as an administrator with **Manage Topics**.
2. Send `hello @tg_sort_bot` once in each existing topic. This is a controlled,
   one-time bootstrap; each message gives the bot its topic ID.
3. Use **Load known topics** in the web UI.
4. Disable privacy mode in @BotFather if the bot should learn topics from
   ordinary messages without a mention.
5. Use **/topic** inside Telegram to identify a topic when needed.
6. Import older topics in the UI using:
   `topic_id | title | emoji_id | pinned`

Only `topic_id` is required. The other fields enable title/emoji sorting and
explicit pinned-topic skipping.

## Setup

Create a bot with [@BotFather](https://t.me/BotFather), then add this secret:

```text
BOT_TOKEN=the-token-from-BotFather
SESSION_SECRET=optional-flask-session-secret
```

Keep the token in the server environment file only. Never put it in frontend
code, source control, screenshots, or chat messages.

Run:

```bash
python main.py
```

For production, run Gunicorn under systemd as described in
[DEPLOYMENT.md](DEPLOYMENT.md).

## Architecture

- `main.py` runs Flask, the long-polling `getUpdates` listener, and the sort
  worker.
- `bot_handler.py` contains the dependency-free HTTPS Bot API client, topic
  roster, permissions check, and sorting logic.
- `topics.json` stores only learned/imported topic metadata. It is local
  runtime state, not tracked in git: one file holds every group (keyed by
  chat ID) and grows as the bot learns topics. Back it up manually (see
  [DEPLOYMENT.md](DEPLOYMENT.md)).
- `static/app.js` and `templates/index.html` provide the web UI.

The poller uses `getMe`, `getUpdates`, `getChat`, and `getChatMember`. Sorting
uses `sendMessage` with `message_thread_id` and `disable_notification`.

## Safety behavior

- No personal Telegram account is ever logged in.
- No API hash or API ID is read.
- The bot token is never returned by an endpoint or rendered into the browser.
- Sorting is blocked unless the bot is an administrator with Manage Topics.
- Historical topic discovery is not faked; the UI explains when a roster is
  incomplete.
- Bot API errors and rate limits are surfaced in the activity log.

## Troubleshooting

### Bot does not connect

- Confirm the `BOT_TOKEN` environment variable exists and is correct.
- Ensure no other process is polling this bot.
- Ensure no webhook is configured for the bot while this app uses polling.
- Restart the service after changing the token.

### Topics are missing

The Bot API cannot list old group topics. Let the bot observe messages in the
missing topics, use `/topic` to identify them, or import their IDs manually.

### Sorting is rejected

The target must be a group/supergroup, the bot must be an administrator, and
the bot must have **Manage Topics** permission.

## Development notes

- Keep Telegram IDs as strings at the browser/JSON boundary to avoid JavaScript
  precision loss.
- Do not log, expose, or commit `BOT_TOKEN`.
- Do not reintroduce Telethon/API_HASH as a workaround for Bot API limitations.
- Use the existing queue worker for long-running sorts.
