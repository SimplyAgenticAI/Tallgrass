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
SIGNALS = ("opportunity", "question", "not_now")


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
                    -- An AI label stands until the conversation moves.
                    signal    = CASE WHEN message_threads.ai_hash IS NOT NULL
                                      AND message_threads.ai_hash IS excluded.last_hash
                                     THEN message_threads.signal ELSE excluded.signal END,
                    signal_reason = CASE WHEN message_threads.ai_hash IS NOT NULL
                                          AND message_threads.ai_hash IS excluded.last_hash
                                         THEN message_threads.signal_reason ELSE NULL END,
                    unread    = excluded.unread,
                    -- A snooze ends early when they write again.
                    snooze_until = CASE WHEN excluded.last_hash IS NOT message_threads.last_hash
                                        THEN NULL ELSE message_threads.snooze_until END,
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


def set_signal(user_id, thread_key, signal):
    """Relabel a chat from the open conversation. Returns whether it changed.

    Only while they spoke last — a label describes THEIR messages — and only a
    chat already saved; this never creates one.
    """
    if signal not in SIGNALS:
        signal = None
    with db.get_db() as conn:
        return conn.execute(
            "UPDATE message_threads SET signal = ? WHERE user_id = ? AND thread_key = ? "
            "AND last_from = 'them' AND signal IS NOT ? "
            "AND (ai_hash IS NULL OR ai_hash IS NOT last_hash)",
            (signal, user_id, _text(thread_key, 200), signal)).rowcount > 0


# ------------------------------------------------------------------ AI sort
#
# Opt-in, from Settings. Keywords called "As much as I would love to purchase
# this year… broke until I get a job" an opportunity. With this on, the text
# the extension can see — the chat list's preview line, or the recent messages
# of a chat you open — goes to the AI once to be labelled, and is dropped.
# Only the label, a few-word reason and the fingerprint it was judged on are
# kept. Off, nothing but the keyword label ever leaves the browser.

AI_SETTING = "messenger_ai_sort"
AI_LABELS = {"opportunity": "opportunity", "question": "question", "not_now": "not_now", "other": None}
SORT_ASYNC = True            # tests run it inline
SORT_BATCH = 60              # chats per AI call


def needs_sort(user_id, keys, basis):
    """Of these chats, the ones waiting on you with no AI label for where they
    stand now. A preview label is improved on once the whole chat is seen."""
    keys = [_text(k, 200) for k in (keys or []) if k][:MAX_THREADS]
    if not keys:
        return []
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT thread_key, ai_hash, ai_basis, last_hash FROM message_threads "
            "WHERE user_id = ? AND last_from = 'them' AND is_demo = 0 AND thread_key IN (%s)"
            % ",".join("?" * len(keys)), [user_id] + keys).fetchall()
    return [r["thread_key"] for r in rows
            if r["ai_hash"] is None or r["ai_hash"] != r["last_hash"]
            or (basis == "conversation" and r["ai_basis"] != "conversation")]


def sortable(user_id, items, basis):
    """The items the extension sent that still need a label, with the
    fingerprint each is judged against. Text is trimmed, never stored."""
    items = [i for i in (items or []) if isinstance(i, dict) and i.get("key")][:MAX_THREADS]
    wanted = set(needs_sort(user_id, [i["key"] for i in items], basis))
    with db.get_db() as conn:
        hashes = {r["thread_key"]: r["last_hash"] for r in conn.execute(
            "SELECT thread_key, last_hash FROM message_threads WHERE user_id = ?", (user_id,))}
    out = []
    for i in items:
        key = _text(i["key"], 200)
        text = str(i.get("text") or "").strip()[:1500]
        if key in wanted and text:
            out.append({"id": key, "name": _text(i.get("name"), 120), "text": text, "hash": hashes.get(key)})
    return out


def store_sort(user_id, labels, judged, basis):
    """Apply the AI's labels to chats that have not moved since they were read."""
    stored = 0
    with db.get_db() as conn:
        for item in labels or []:
            if not isinstance(item, dict) or item.get("label") not in AI_LABELS:
                continue
            key = str(item.get("id") or "")
            if key not in judged:
                continue
            stored += conn.execute(
                "UPDATE message_threads SET signal = ?, signal_reason = ?, ai_hash = last_hash, ai_basis = ? "
                "WHERE user_id = ? AND thread_key = ? AND last_from = 'them' AND last_hash IS ?",
                (AI_LABELS[item["label"]], _text(item.get("reason"), 140) or None, basis,
                 user_id, key, judged[key])).rowcount
    return stored


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
