# Evolution of the Telegram Topic Sorter

This file records an architectural decision that future contributors and
agents must respect.

## The original approach: a userbot

The first version operated as a Telegram **userbot** through Telethon. It
logged in as a personal Telegram account and required:

- `API_ID` and `API_HASH` from `my.telegram.org`
- A phone number
- Interactive login codes
- A persistent personal Telegram session file
- An MTProto client running continuously in the application

That approach was chosen because MTProto exposed
`channels.getForumTopics`, which allowed the application to enumerate forum
topics directly. It appeared to solve the original requirement of finding and
sorting every topic in a group.

In practice, it created the wrong risk profile:

1. The application was acting as a real person, not as a dedicated bot.
2. A personal account and its session became operational dependencies.
3. API credentials and session handling added unnecessary attack and failure
   surfaces.
4. Telegram account restrictions could permanently affect the owner.
5. The web application was coupled to a user login flow instead of a narrowly
   scoped bot identity.
6. “It can do more” was treated as sufficient justification for using a
   personal account.

That tradeoff is not acceptable for this project. The account was permanently
blocked, which confirmed that the theoretical convenience was not worth the
personal-account risk.

## The route we picked instead: a regular Bot API bot

The application now uses a bot created with `@BotFather` and a server-side
`BOT_TOKEN`. It communicates with Telegram through the official HTTPS Bot API.

The bot:

- Has no access to a personal Telegram account.
- Does not use `API_ID`, `API_HASH`, a phone number, Telethon, MTProto, or a
  personal session.
- Is added to target groups explicitly.
- Is checked for administrator status and **Manage Topics** permission before
  sorting.
- Learns topic IDs from incoming updates.
- Can be bootstrapped safely by sending one controlled message or mention in
  each existing topic.
- Sends quiet marker messages to known topics using `message_thread_id`.
- Continues watching for new topics through updates.

The one-time bootstrap is a reasonable operational compromise. It is
controlled, transparent, and does not require impersonating a user. It also
means the application does not need to pretend that the Bot API can perform a
capability it does not expose.

## The important limitation

The Bot API supports targeting a known topic and includes topic-management
methods, but it still does not expose the MTProto
`channels.getForumTopics` method for enumerating historical group topics.

Therefore, regular-bot mode cannot automatically reconstruct every topic that
existed before the bot was added. This is a limitation to document and design
around—not a reason to silently bring back a userbot.

For old topics, use one of these safe options:

1. Send one message or mention containing the bot username in each topic.
2. Use `/topic` in a topic when its numeric ID is needed.
3. Import a topic roster manually when titles, emoji IDs, or pinned flags must
   be supplied.

## Hard rule for future changes

**Do not reintroduce a userbot, Telethon, MTProto, `API_HASH`, or personal
Telegram login merely to recover automatic historical topic enumeration.**

A future proposal may revisit this decision only if all of the following are
true:

1. The regular Bot API and update-based bootstrap have been demonstrated to be
   insufficient for a concrete, documented requirement.
2. There is no safe Bot API, webhook, export/import, or manual-roster
   alternative.
3. The missing capability is essential rather than merely more convenient.
4. The security and account-risk implications are explicitly reviewed first.
5. The owner gives clear, deliberate approval after seeing those tradeoffs.

“The userbot is easier,” “MTProto has a method for this,” or “another project
does it” are **not** sufficient reasons.

## Current decision

Regular Bot API mode is the default and preferred architecture. It is not a
temporary downgrade or an unfinished migration. Future agents should start
from this decision and improve the safe bot workflow before suggesting any
account-based alternative.
