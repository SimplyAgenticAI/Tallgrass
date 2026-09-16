"""Comments on your own posts, and which ones you have not answered.

The extension reads an open post's comment thread and sends it here. This keeps
it: one row per post, one row per comment, with the verdict the extension
reached (answered, unanswered, yours, or unknown when replies were folded).

It is the foundation for drafting replies, and it is deliberately only storage
and a list for now. A reply tool that treats an answered comment as unanswered
makes its user look careless in public, so the reading is checked on real posts
before anything is drafted from it.

Two rules:

  * A re-read updates what it saw and forgets nothing it did not. A comment
    missing from one read has usually just been scrolled or folded out of view,
    not deleted, and silently dropping it would lose the one you needed.
  * "Done" is the user's, and a re-read never undoes it. The verdict is the
    extension's, and a re-read always refreshes it.

Scoped to one owner throughout, like everything else that touches captures.
"""

import db

VERDICTS = ("unanswered", "unknown", "answered", "yours")
STATUSES = ("open", "done")

MAX_COMMENTS = 500          # per read; a thread longer than this is truncated


def _text(value, limit):
    return db.clean_text(str(value), limit) if value else ""


def _count(value):
    try:
        return max(0, min(int(value or 0), 100000))
    except (TypeError, ValueError):
        return 0


def save_thread(user_id, payload):
    """Store one read of one post's comments. Returns a summary, or raises
    ValueError with a message fit to show the extension."""
    post = (payload or {}).get("post") or {}
    items = (payload or {}).get("comments") or []
    key = _text(post.get("key"), 300)
    if not key:
        raise ValueError("post.key is required")
    if not isinstance(items, list):
        raise ValueError("comments must be a list")
    items = items[:MAX_COMMENTS]

    counts = {v: 0 for v in VERDICTS}
    new = 0
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO comment_posts (user_id, post_key, url, title, more_comments, read_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, post_key) DO UPDATE SET
                url           = COALESCE(excluded.url, comment_posts.url),
                title         = COALESCE(NULLIF(excluded.title, ''), comment_posts.title),
                more_comments = excluded.more_comments,
                read_at       = CURRENT_TIMESTAMP
            """,
            (user_id, key, _text(post.get("url"), 500) or None,
             _text(post.get("title"), 300), int(bool(post.get("more_comments")))))
        post_id = conn.execute(
            "SELECT id FROM comment_posts WHERE user_id = ? AND post_key = ?",
            (user_id, key)).fetchone()["id"]

        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            comment_key = _text(item.get("key"), 200)
            if not comment_key:
                continue
            parent = _text(item.get("parent_key"), 200) or None
            verdict = item.get("verdict") if parent is None else None
            if parent is None and verdict not in VERDICTS:
                verdict = "unknown"         # never assume unanswered
            if verdict:
                counts[verdict] += 1
            if not conn.execute(
                    "SELECT 1 FROM post_comments WHERE user_id = ? AND post_id = ? "
                    "AND comment_key = ?", (user_id, post_id, comment_key)).fetchone():
                new += 1
            conn.execute(
                """
                INSERT INTO post_comments (user_id, post_id, comment_key, parent_key,
                                           author, body, url, is_mine, verdict,
                                           hidden_replies, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, post_id, comment_key) DO UPDATE SET
                    parent_key     = excluded.parent_key,
                    author         = COALESCE(NULLIF(excluded.author, ''), post_comments.author),
                    body           = COALESCE(NULLIF(excluded.body, ''), post_comments.body),
                    url            = COALESCE(excluded.url, post_comments.url),
                    is_mine        = excluded.is_mine,
                    verdict        = excluded.verdict,
                    hidden_replies = excluded.hidden_replies,
                    position       = excluded.position,
                    seen_at        = CURRENT_TIMESTAMP
                """,
                (user_id, post_id, comment_key, parent,
                 _text(item.get("author"), 200), _text(item.get("text"), 5000),
                 _text(item.get("url"), 500) or None, int(bool(item.get("mine"))),
                 verdict, _count(item.get("hidden_replies")), position))

    return {"post_id": post_id, "comments": len(items), "new": new, "verdicts": counts}


def threads_for(user_id, show_done=False):
    """Every post with its comments, the ones needing an answer first."""
    with db.get_db() as conn:
        posts = [dict(r) for r in conn.execute(
            "SELECT * FROM comment_posts WHERE user_id = ? ORDER BY read_at DESC",
            (user_id,))]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM post_comments WHERE user_id = ? ORDER BY post_id, position",
            (user_id,))]

    by_post = {p["id"]: p for p in posts}
    for p in posts:
        p["threads"] = []
        p["counts"] = {v: 0 for v in VERDICTS}
    tops = {}
    for row in rows:
        row["replies"] = []
        if row["parent_key"] is None and row["post_id"] in by_post:
            tops[(row["post_id"], row["comment_key"])] = row
    for row in rows:
        post = by_post.get(row["post_id"])
        if post is None:
            continue
        if row["parent_key"] is None:
            post["threads"].append(row)
            if row["status"] == "open":
                post["counts"][row["verdict"] or "unknown"] += 1
        else:
            parent = tops.get((row["post_id"], row["parent_key"]))
            if parent is not None:
                parent["replies"].append(row)

    order = {v: i for i, v in enumerate(VERDICTS)}
    for p in posts:
        if not show_done:
            p["done_count"] = sum(1 for t in p["threads"] if t["status"] == "done")
            p["threads"] = [t for t in p["threads"] if t["status"] != "done"]
        p["threads"].sort(key=lambda t: (order.get(t["verdict"], 1), t["position"]))

    posts.sort(key=lambda p: (-p["counts"]["unanswered"], -p["counts"]["unknown"]))
    totals = {v: sum(p["counts"][v] for p in posts) for v in VERDICTS}
    return {"posts": posts, "totals": totals}


def context_for(user_id, comment_id=None, post_key=None, comment_key=None):
    """What a draft needs to know about one stored comment, or None.

    Found by row id (the Comments page) or by the extension's keys (Facebook).
    """
    with db.get_db() as conn:
        if comment_id is not None:
            row = conn.execute(
                "SELECT c.*, p.title AS post_title FROM post_comments c "
                "JOIN comment_posts p ON p.id = c.post_id "
                "WHERE c.id = ? AND c.user_id = ?", (int(comment_id), user_id)).fetchone()
        else:
            row = conn.execute(
                "SELECT c.*, p.title AS post_title FROM post_comments c "
                "JOIN comment_posts p ON p.id = c.post_id "
                "WHERE p.user_id = ? AND p.post_key = ? AND c.comment_key = ?",
                (user_id, post_key or "", comment_key or "")).fetchone()
        if not row:
            return None
        found = dict(row)
        found["replies"] = [dict(r) for r in conn.execute(
            "SELECT author, body AS text FROM post_comments "
            "WHERE post_id = ? AND user_id = ? AND parent_key = ? ORDER BY position",
            (found["post_id"], user_id, found["comment_key"]))]
    return found


def store_draft(user_id, comment_id, text):
    with db.get_db() as conn:
        conn.execute(
            "UPDATE post_comments SET draft = ?, drafted_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?", (_text(text, 2000), int(comment_id), user_id))


def set_status(user_id, comment_id, status):
    if status not in STATUSES:
        raise ValueError("status must be open or done")
    with db.get_db() as conn:
        return conn.execute(
            "UPDATE post_comments SET status = ? WHERE id = ? AND user_id = ?",
            (status, int(comment_id), user_id)).rowcount


def forget_post(user_id, post_id):
    with db.get_db() as conn:
        conn.execute("DELETE FROM post_comments WHERE post_id = ? AND user_id = ?",
                     (int(post_id), user_id))
        return conn.execute("DELETE FROM comment_posts WHERE id = ? AND user_id = ?",
                            (int(post_id), user_id)).rowcount
