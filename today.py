"""Today: everyone waiting on an answer, in one list.

Unanswered comments lived on the Comments page and waiting chats on the
Messages page, so answering people meant working two lists. This merges them
into one queue — what looks like an opportunity first, then the newest — and
gives the count that the navigation and the extension icon show.

Read-only over the two stores. Done and drafting still go through them.
"""

import re

import db

# The same signals the extension looks for in a chat's last line, applied to
# comment text here. A hint for ordering, never a verdict.
OPPORTUNITY_RE = re.compile(
    r"\b(?:how much|price|pricing|prices|cost|costs|quote|rates?|available|availability"
    r"|interested|book|booking|appointment|schedule|order|buy|purchase"
    r"|still (?:have|available|for sale)|ship|shipping|deliver|delivery|invoice|payment"
    r"|deposit|call me|text me|dm me|pm me|inbox me|more info|details)\b",
    re.IGNORECASE)


def queue(user_id):
    with db.get_db() as conn:
        comment_rows = conn.execute(
            """
            SELECT c.id, c.author, c.body, c.url, c.verdict, c.hidden_replies, c.draft,
                   c.first_seen_at, p.title AS post_title, p.url AS post_url
            FROM post_comments c JOIN comment_posts p ON p.id = c.post_id
            WHERE c.user_id = ? AND c.parent_key IS NULL AND c.status = 'open'
              AND c.is_mine = 0 AND c.verdict IN ('unanswered', 'unknown')
            """, (user_id,)).fetchall()
        chat_rows = conn.execute(
            """
            SELECT id, name, url, last_at, signal, unread FROM message_threads
            WHERE user_id = ? AND status = 'open' AND last_from = 'them'
            """, (user_id,)).fetchall()

    items = []
    for r in comment_rows:
        items.append({
            "kind": "comment",
            "id": r["id"],
            "who": r["author"] or "Someone",
            "text": r["body"] or "",
            "where": r["post_title"] or "Your post",
            "url": r["url"] or r["post_url"],
            "when": r["first_seen_at"],
            "verdict": r["verdict"],
            "hidden_replies": r["hidden_replies"],
            "draft": r["draft"],
            "opportunity": bool(OPPORTUNITY_RE.search(r["body"] or "")),
            "question": (r["body"] or "").rstrip().endswith("?"),
        })
    for r in chat_rows:
        items.append({
            "kind": "message",
            "id": r["id"],
            "who": r["name"] or "Unnamed chat",
            "text": "",
            "where": "Messenger",
            "url": r["url"],
            "when": (r["last_at"] or "").replace("T", " "),
            "unread": bool(r["unread"]),
            "opportunity": r["signal"] == "opportunity",
            "question": r["signal"] == "question",
        })

    items.sort(key=lambda i: i["when"] or "", reverse=True)
    items.sort(key=lambda i: (not i["opportunity"], not i["question"]))
    return {
        "entries": items,
        "comments": sum(1 for i in items if i["kind"] == "comment"),
        "messages": sum(1 for i in items if i["kind"] == "message"),
        "opportunities": sum(1 for i in items if i["opportunity"]),
    }


def waiting_count(user_id):
    """How many people are waiting on an answer. Cheap: two counts."""
    with db.get_db() as conn:
        comments = conn.execute(
            "SELECT COUNT(*) FROM post_comments WHERE user_id = ? AND parent_key IS NULL "
            "AND status = 'open' AND is_mine = 0 AND verdict IN ('unanswered', 'unknown')",
            (user_id,)).fetchone()[0]
        chats = conn.execute(
            "SELECT COUNT(*) FROM message_threads WHERE user_id = ? AND status = 'open' "
            "AND last_from = 'them'", (user_id,)).fetchone()[0]
    return comments + chats
