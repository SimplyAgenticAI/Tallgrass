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

import re

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
        # The same post, reached another way.
        #
        # A post opened from a profile, from its own link or from a photo can
        # each carry a different address, and the post is keyed on its address
        # — so one post could be filed twice with the same comments under both.
        # Facebook's comment ids are unique across Facebook, so a read whose
        # comments are already stored under another post IS that post.
        facebook_ids = [_text(i.get("key"), 200) for i in items
                        if isinstance(i, dict) and str(i.get("key") or "").startswith("c:")][:500]
        if facebook_ids:
            known = conn.execute(
                "SELECT p.post_key FROM post_comments c "
                "JOIN comment_posts p ON p.id = c.post_id "
                "WHERE c.user_id = ? AND c.comment_key IN (%s) "
                "GROUP BY p.id ORDER BY COUNT(*) DESC LIMIT 1"
                % ",".join("?" * len(facebook_ids)),
                [user_id] + facebook_ids).fetchone()
            if known:
                key = known["post_key"]

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

        resolved = {}               # key as sent -> key as stored
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            comment_key = _text(item.get("key"), 200)
            if not comment_key:
                continue
            author = _text(item.get("author"), 200)
            body = _text(item.get("text"), 5000)
            # A comment with no Facebook id is keyed on its author and words,
            # so the same comment read cut short ("… See more") and then in
            # full would be two. It is matched to the one already stored.
            if not comment_key.startswith("c:"):
                comment_key = _stored_twin(conn, user_id, post_id, author, body) or comment_key
            resolved[_text(item.get("key"), 200)] = comment_key
            parent = _text(item.get("parent_key"), 200) or None
            if parent:
                parent = resolved.get(parent, parent)
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
                    -- The fuller reading wins: a later read cut short by
                    -- "See more" must not replace words already stored.
                    body           = CASE WHEN LENGTH(COALESCE(excluded.body, ''))
                                               >= LENGTH(COALESCE(post_comments.body, ''))
                                          THEN excluded.body ELSE post_comments.body END,
                    url            = COALESCE(excluded.url, post_comments.url),
                    is_mine        = excluded.is_mine,
                    verdict        = excluded.verdict,
                    hidden_replies = excluded.hidden_replies,
                    position       = excluded.position,
                    seen_at        = CURRENT_TIMESTAMP
                """,
                (user_id, post_id, comment_key, parent, author, body,
                 _text(item.get("url"), 500) or None, int(bool(item.get("mine"))),
                 verdict, _count(item.get("hidden_replies")), position))

    return {"post_id": post_id, "comments": len(items), "new": new, "verdicts": counts}


_SEE_MORE = re.compile(r"(?:\s*(?:…|\.\.\.)\s*)?(?:see more)?\s*$", re.IGNORECASE)


def _comparable(body):
    return _SEE_MORE.sub("", (body or "").strip()).strip().lower()


def _stored_twin(conn, user_id, post_id, author, body):
    """The key of this comment if it is already stored under another key.

    Same post, same author, and the same words — or one reading being the
    start of the other, which is what a "See more" cut looks like. The prefix
    match needs twenty characters, so "Yes" and "Yes please" stay two comments.
    """
    words = _comparable(body)
    if not author or not words:
        return None
    for row in conn.execute(
            "SELECT comment_key, body FROM post_comments "
            "WHERE user_id = ? AND post_id = ? AND author = ?",
            (user_id, post_id, author)):
        other = _comparable(row["body"])
        if not other:
            continue
        if other == words:
            return row["comment_key"]
        shorter = min(len(other), len(words))
        if shorter >= 20 and (other.startswith(words) or words.startswith(other)):
            return row["comment_key"]
    return None


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


def recent_own_replies(user_id, limit=5):
    """A few of the owner's own replies, newest first, as examples of their voice.

    Only what they actually posted — replies and comments by them saved from
    their own posts — never a draft, which is the model's writing, not theirs.
    """
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT body FROM post_comments "
            "WHERE user_id = ? AND is_mine = 1 AND LENGTH(body) >= 15 "
            "ORDER BY seen_at DESC LIMIT ?", (user_id, int(limit))).fetchall()
    return [r["body"] for r in rows]


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
