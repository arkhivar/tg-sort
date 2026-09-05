# How tg-sort learns Telegram topic names

A field note from a debugging session (2026-09-04), kept so future sessions
don't have to re-derive it.

## The symptom

The web UI listed topics as `Untitled · ID 434`, `Untitled · ID 3008`, … even
though the bot was clearly seeing messages in those topics (it had learned
their IDs).

## The contradiction

- The [official Bot API docs](https://core.telegram.org/bots/api) say a topic's
  name exists only in the `forum_topic_created` and `forum_topic_edited`
  **service messages**. A regular message in an existing topic carries only
  `message_thread_id` + `is_topic_message` — no name. (There is still no
  `getForumTopics`/`getForumTopicInfo`; sites claiming otherwise are
  hallucinating.)
- Yet a live `getUpdates` dump from a test group showed the topic name on
  **every** message posted inside a topic, not just service messages.

Both were right.

## The resolution

Messages posted inside a forum topic are delivered as **replies to the
topic's creation message**, and that nested message carries the name:

```
message.message_thread_id                              -> 63621
message.reply_to_message.message_id                    -> 63621  (creation message)
message.reply_to_message.forum_topic_created.name      -> "hi Kimi"
message.reply_to_message.forum_topic_created.icon_custom_emoji_id
```

Confirmed across 4 topics (~30 messages) in test group `-1002686348537`
(threads 63607 "AB", 63594 "VP", 63621 "hi Kimi", 5 "AS"): every in-topic
message had `reply_to_message.message_id == message_thread_id` with
`forum_topic_created` inside. The top-level `forum_topic_created` appears only
once per topic, on the creation message itself.

tg-sort's bug: `TopicStore.observe_message` in `bot_handler.py` read only the
top-level `forum_topic_created`, so it saved the ID and discarded the name one
level deeper. The fix adopts the nested creation info when it belongs to the
same topic, and also handles `forum_topic_edited` (renames), which was ignored
entirely.

## Hard limits that remain

- The Bot API cannot enumerate pre-existing topics; the bot still learns them
  only from observed updates or a manual roster import.
- `getUpdates` holds updates for ~24 hours and each is delivered once, to a
  single consumer per token.
- Topics created before the bot started watching stay nameless until someone
  posts in them again (the name backfills automatically from the reply
  payload) or the topic is renamed.
- The echoed name in `reply_to_message.forum_topic_created` is **frozen at
  creation time**: for a topic renamed in the past, backfill yields the
  *original* name, not the current one. There is no API to read the current
  name; only a fresh rename (`forum_topic_edited`, always applied) or a manual
  roster import updates it. For the same reason `observe_message` uses the
  echo only to fill empty fields — applying it unconditionally overwrote
  fresher names on every observed message (bug found 2026-09-05, when a
  rename appeared to "not work" because the next ordinary message restored
  the stale creation name).

## Renames (`forum_topic_edited`)

Confirmed live (2026-09-05, test group `-1002686348537`): renaming a topic
delivers an ordinary `message` update with `message_thread_id` set and

```json
"forum_topic_edited": {"name": "I've just remember this one"}
```

(optionally also `icon_custom_emoji_id` when the icon changes). These arrive
through the existing `allowed_updates: ["message"]` polling — no extra
subscription needed. `observe_message` always applies them, so a rename is
the freshest name source and is never clobbered by later creation-name
echoes.

Future: the owner wants **rename history** (checkpoints per topic). The
store currently keeps only the latest name; capturing history means
appending `{"name": ..., "date": message.date}` to a per-topic list on each
`forum_topic_edited` (and on creation). Only renames that happen while the
bot is polling can be captured — Telegram does not expose past renames.

## Credits

Found by the project owner insisting on empirical proof over doc-based
reasoning ("test it on a real group"), with the machine doing the payload
archaeology. The contradiction above survived two rejected plans; the live
`getUpdates` dump settled it in one look.
