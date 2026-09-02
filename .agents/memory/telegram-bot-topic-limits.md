---
name: Telegram Bot API topic discovery
description: Durable limitation and safe workflow for forum-topic sorting with a regular bot
---

The regular Telegram Bot API supports sending to a known forum topic with
`message_thread_id`, but it does not expose the MTProto
`channels.getForumTopics` capability for enumerating historical group topics.

**Why:** A userbot can inspect a group’s topic list through MTProto, but relying
on that requires a personal Telegram session and API credentials. The safer
regular-bot design must not recreate that dependency when the Bot API lacks the
equivalent method.

**How to apply:** Use update-based discovery and/or an explicit imported topic
roster. Never imply that a regular bot can automatically recover every topic
that existed before it joined, and validate the bot’s Manage Topics permission
before sending.