"""Messenger chats that are waiting on you, or have gone quiet.

The extension reads the chat list on facebook.com/messages — the same rows you
see, each saying who the chat is with, the last line and when — and sends a
summary of each here. Two lists come out of it:

  waiting   they spoke last. Someone is waiting on an answer.
  replied   you spoke last, recently. Nothing to do yet — the ball is theirs.
  quiet     you spoke last, QUIET_DAYS or more ago, and nothing came back.
            A conversation worth bringing back to life.

A chat moves between them on its own: answering it moves it to replied, time
moves it to quiet, and their next message moves it back to waiting. Nobody has
to press Done for any of that — Done is only for a chat to set aside.

What is kept is the least that makes those lists work, by design: who the
chat is with, its link, who spoke last, roughly when, whether the last message
looked like an opportunity (decided in the browser), and a hash of it. Never
the message text. Drafting the next message reads the open conversation in
the browser and sends it to the AI once, on request, and nothing about it is
stored here.

"Done" is the user's. It holds until the chat actually changes — a new last
message, detected by its hash — and then the chat comes back.
"""

from datetime import datetime, timedelta, timezone

import db

QUIET_DAYS = 3
MAX_THREADS = 500
SIGNALS = ("opportunity", "question")


def _text(value, limit):
    return db.clean_text(str(value), limit) if value else ""


def _when(value):
    """The extension's approximate ISO time, or None. Never in the future."""
    try:
        when = datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return min(when, now).strftime("%Y-%m-%dT%H:%M:%S")


def save_threads(user_id, payload):
    rows = (payload or {}).get("threads")
    if not isinstance(rows, list):
        raise ValueError("threads must be a list")
    rows = rows[:MAX_THREADS]

    saved = 0
    with db.get_db() as conn:
        # The first real save replaces the examples, in this same transaction.
        import reply_samples
        reply_samples.clear_thread_samples(conn, user_id)
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = _text(row.get("key"), 200)
            last_from = row.get("last_from")
            if not key or last_from not in ("me", "them"):
                continue
            signal = row.get("signal") if row.get("signal") in SIGNALS else None
            if last_from == "me":
                signal = None           # a signal describes THEIR last message
            conn.execute(
                """
                INSERT INTO message_threads (user_id, thread_key, name, url, last_from,
                                             last_at, signal, unread, last_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, thread_key) DO UPDATE SET
                    name      = COALESCE(NULLIF(excluded.name, ''), message_threads.name),
                    url       = COALESCE(excluded.url, message_threads.url),
                    last_from = excluded.last_from,
                    last_at   = COALESCE(excluded.last_at, message_threads.last_at),
                    signal    = excluded.signal,
                    unread    = excluded.unread,
                    last_hash = excluded.last_hash,
                    -- Done holds until the conversation actually moves.
                    status    = CASE WHEN message_threads.status = 'done'
                                      AND excluded.last_hash IS NOT message_threads.done_hash
                                     THEN 'open' ELSE message_threads.status END,
                    seen_at   = CURRENT_TIMESTAMP
                """,
                (user_id, key, _text(row.get("name"), 200),
                 _text(row.get("url"), 500) or None, last_from, _when(row.get("last_at")),
                 signal, int(bool(row.get("unread"))), _text(row.get("last_hash"), 64) or None))
            saved += 1

    lists = inbox(user_id)
    return {"saved": saved, "waiting": len(lists["waiting"]), "replied": len(lists["replied"]),
            "quiet": len(lists["quiet"]), "opportunities": lists["opportunities"]}


def inbox(user_id, show_done=False):
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM message_threads WHERE user_id = ?", (user_id,))]

    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
              - timedelta(days=QUIET_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    waiting, replied, quiet = [], [], []
    for row in rows:
        if row["status"] == "done" and not show_done:
            continue
        if row["last_from"] == "them":
            waiting.append(row)
        # Quiet only once it has actually been quiet a while, and only when the
        # time was readable — a chat with no known time could be from a minute
        # ago, so it waits under replied rather than being called quiet.
        elif row["last_from"] == "me" and row["last_at"] and row["last_at"] <= cutoff:
            quiet.append(row)
        elif row["last_from"] == "me":
            replied.append(row)

    waiting.sort(key=lambda r: r["last_at"] or "", reverse=True)
    waiting.sort(key=lambda r: (r["signal"] != "opportunity", not r["unread"]))
    replied.sort(key=lambda r: r["last_at"] or "", reverse=True)
    quiet.sort(key=lambda r: r["last_at"] or "", reverse=True)
    return {
        "waiting": waiting,
        "replied": replied,
        "quiet": quiet,
        "opportunities": sum(1 for r in waiting if r["signal"] == "opportunity"),
        "quiet_days": QUIET_DAYS,
    }


def set_status(user_id, thread_id, status):
    if status not in ("open", "done"):
        raise ValueError("status must be open or done")
    with db.get_db() as conn:
        return conn.execute(
            "UPDATE message_threads SET status = ?, "
            "done_hash = CASE WHEN ? = 'done' THEN last_hash ELSE done_hash END "
            "WHERE id = ? AND user_id = ?",
            (status, status, int(thread_id), user_id)).rowcount


def forget_all(user_id):
    with db.get_db() as conn:
        return conn.execute("DELETE FROM message_threads WHERE user_id = ?",
                            (user_id,)).rowcount
