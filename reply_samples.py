"""Example comments and chats, so the reply features are not empty on day one.

New accounts are seeded with sample posts because nobody installs an
extension on faith. The same held for comments and Messenger: until somebody
had saved their own, Comments, Messages and Today were three empty pages
describing features nobody had seen work.

So each account gets a small, clearly marked set — a post with comments in
each state, and chats in each list — the first time one of those pages is
opened (or at signup). Rules, the same ones posts follow:

  * Marked is_demo, labelled Sample wherever shown, and never counted in the
    waiting badge, which is a number people act on.
  * Removed in the same transaction that saves the first real comments or
    chats, so a sample never sits beside real data.
  * Seeded once. Clearing everything afterwards does not bring them back.
"""

from datetime import datetime, timedelta, timezone

import db

SEEDED_KEY = "reply_samples_seeded"

POST = {"key": "sample:post", "title": "3 things I wish I'd known before hiring a web designer"}

COMMENTS = [
    # (key, parent, author, text, verdict, mine)
    ("sample:c1", None, "Dana Brooks", "How much does something like this usually cost?", "unanswered", 0),
    ("sample:c2", None, "Marcus Lee", "Do you work with restaurants too?", "unanswered", 0),
    ("sample:c3", None, "Priya Patel", "This was so helpful, thank you!", "answered", 0),
    ("sample:c3r", "sample:c3", "You", "Glad it helped, Priya! Shout if you have questions.", None, 1),
]

# (key, name, last_from, hours ago, signal)
THREADS = [
    ("sample:t1", "Chris Alvarez", "them", 2, "opportunity"),
    ("sample:t2", "Jordan Blake", "them", 26, "question"),
    ("sample:t3", "Sam Rivera", "me", 20, None),
    ("sample:t4", "Taylor Kim", "me", 24 * 6, None),
]


def _flag(conn, user_id):
    return conn.execute("SELECT 1 FROM user_settings WHERE user_id = ? AND key = ?",
                        (user_id, SEEDED_KEY)).fetchone()


def seed_once(user_id):
    """Seed the examples if this account has never had them. Never raises."""
    if not user_id:
        return False
    try:
        with db.get_db() as conn:
            if _flag(conn, user_id):
                return False
            has_real = conn.execute(
                "SELECT (SELECT COUNT(*) FROM comment_posts WHERE user_id = ?) + "
                "(SELECT COUNT(*) FROM message_threads WHERE user_id = ?)",
                (user_id, user_id)).fetchone()[0]
            conn.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) "
                         "VALUES (?, ?, '1')", (user_id, SEEDED_KEY))
            if has_real:
                return False            # already using it for real — no examples needed

            conn.execute("INSERT INTO comment_posts (user_id, post_key, title, is_demo) "
                         "VALUES (?, ?, ?, 1)", (user_id, POST["key"], POST["title"]))
            post_id = conn.execute("SELECT id FROM comment_posts WHERE user_id = ? AND post_key = ?",
                                   (user_id, POST["key"])).fetchone()["id"]
            for position, (key, parent, author, text, verdict, mine) in enumerate(COMMENTS):
                conn.execute(
                    "INSERT INTO post_comments (user_id, post_id, comment_key, parent_key, author, "
                    "body, is_mine, verdict, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, post_id, key, parent, author, text, mine, verdict, position))

            now = datetime.now(timezone.utc)
            for key, name, last_from, hours, signal in THREADS:
                conn.execute(
                    "INSERT INTO message_threads (user_id, thread_key, name, last_from, last_at, "
                    "signal, last_hash, is_demo) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (user_id, key, name, last_from,
                     (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S"), signal, key))
        return True
    except Exception:                                   # noqa: BLE001
        return False                                    # examples are a courtesy


def clear_comment_samples(conn, user_id):
    """Inside the caller's transaction, so the first real save replaces them atomically."""
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM comment_posts WHERE user_id = ? AND is_demo = 1", (user_id,))]
    for post_id in ids:
        conn.execute("DELETE FROM post_comments WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        conn.execute("DELETE FROM comment_posts WHERE id = ? AND user_id = ?", (post_id, user_id))


def clear_thread_samples(conn, user_id):
    conn.execute("DELETE FROM message_threads WHERE user_id = ? AND is_demo = 1", (user_id,))
