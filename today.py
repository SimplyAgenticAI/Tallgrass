"""Today: the comments on your posts that nobody has answered.

This used to merge unanswered comments AND waiting Messenger chats into one
queue. The chats are gone from it, deliberately.

A merged inbox competes with Facebook's own, and loses on every axis that
matters: Facebook delivers in real time where this scrapes, it has mobile apps,
labels and saved replies, and it is free and native. A duplicated inbox is also
a liability rather than a feature — when this said three people were waiting
and Facebook said five, the trust that went was the trust the SCORING earned,
which had nothing to do with chats.

Comments are not the same bet, and they stay. Facebook's Professional Dashboard
is Page-centric: it gives you nothing for comments on your own posts inside
GROUPS from a personal profile, which is this product's whole premise. Those
land in notification soup. And only this app knows which post is an outlier, so
"these comments are on the post doing 14x its group's median" is a judgement
Facebook cannot make.

Chats keep their own page under More, and keep "Suggest a message" in the
on-Facebook panel, which works from inside an open chat and needs no queue.

Read-only over the comment store. Done and drafting still go through it.
"""

import re

import comments
import db
import pipeline

# The same signals the extension looks for in a chat's last line, applied to
# comment text here. A hint for ordering, never a verdict.
OPPORTUNITY_RE = re.compile(
    r"\b(?:how much|price|pricing|prices|cost|costs|quote|rates?|available|availability"
    r"|interested|book|booking|appointment|schedule|order|buy|purchase"
    r"|still (?:have|available|for sale)|ship|shipping|deliver|delivery|invoice|payment"
    r"|deposit|call me|text me|dm me|pm me|inbox me|more info|details)\b",
    re.IGNORECASE)

# Someone saying no, or not yet — the extension's DECLINE_RE, for comments that
# have no AI label. A comment that matches is never called an opportunity.
DECLINE_RE = re.compile(
    r"as much as i(?:'d|’d| would)? (?:love|like)|wish i could|i(?:'d|’d| would) love to,? but"
    r"|(?:can't|can’t|cannot|can not|won't be able to|unable to|not able to) (?:afford|swing|do it|buy|purchase|right now)"
    r"|\bbroke\b|no money|out of money|money(?:'s|’s| is) tight|tight budget|on a budget|not in (?:my|the) budget"
    r"|between jobs|unemployed|(?:lost|lose|losing) (?:my|our) (?:job|work)|until i (?:get|find) (?:a |another )?(?:job|work)"
    r"|(?:rough|hard|tough|difficult) (?:time|year|patch|few months)"
    r"|not (?:right now|now|this (?:year|month|time|season)|at (?:the|this) (?:moment|time)|interested|for me|ready)"
    r"|(?:maybe|perhaps) (?:next|later|another time|down the road|in the future)"
    r"|no,? thank(?:s| you)|i(?:'ll|’ll| will) pass|(?:going|gonna) (?:to )?pass"
    r"|(?:changed|change) my mind|found someone else|went with (?:someone|another)|already (?:found|hired|bought|booked)",
    re.IGNORECASE)


def queue(user_id):
    with db.get_db() as conn:
        comment_rows = conn.execute(
            """
            SELECT c.id, c.author, c.body, c.url, c.verdict, c.hidden_replies, c.draft, c.came_back,
                   c.intent, c.intent_reason,
                   c.first_seen_at, c.stage, c.note, c.author_url,
                   p.title AS post_title, p.url AS post_url, p.is_demo
            FROM post_comments c JOIN comment_posts p ON p.id = c.post_id
            WHERE c.user_id = ? AND c.parent_key IS NULL AND c.status = 'open'
              AND c.is_mine = 0 AND c.verdict IN ('unanswered', 'unknown')
              AND (c.snooze_until IS NULL OR c.snooze_until <= ?)
              AND c.intent IS NOT 'spam'
            """, (user_id, pipeline.now_utc())).fetchall()

    items = []
    for r in comment_rows:
        items.append({
            "kind": "comment",
            "id": r["id"],
            "who": r["author"] or "Someone",
            "text": r["body"] or "",
            "where": r["post_title"] or "Your post",
            # Only ever a link to the post — never the commenter's profile.
            "url": comments.post_link(r["url"]) or comments.post_link(r["post_url"]),
            "when": r["first_seen_at"],
            "verdict": r["verdict"],
            "hidden_replies": r["hidden_replies"],
            "came_back": bool(r["came_back"]),
            "stage": r["stage"],
            "note": r["note"],
            "draft": r["draft"],
            "sample": bool(r["is_demo"]),
            # Message them: reach the commenter in Messenger.
            "dm_url": comments.messenger_link(r["author_url"]),
            # The AI's label when there is one; the keyword check when not.
            "intent": r["intent"],
            "intent_label": comments.INTENT_LABELS.get(r["intent"]),
            "intent_reason": r["intent_reason"],
            "opportunity": r["intent"] == "hot_lead" if r["intent"]
                           else bool(OPPORTUNITY_RE.search(r["body"] or ""))
                           and not DECLINE_RE.search(r["body"] or ""),
            "question": r["intent"] == "question" if r["intent"]
                        else (r["body"] or "").rstrip().endswith("?"),
            "low": r["intent"] in ("praise", "tag", "other"),
        })
    items.sort(key=lambda i: i["when"] or "", reverse=True)
    items.sort(key=lambda i: (not i["opportunity"], not i["question"], i["low"]))
    # `messages` is kept at zero rather than dropped: the key is read in a
    # couple of places that have nothing to do with this decision, and a
    # KeyError there would be a worse outcome than a number that is always 0.
    return {
        "entries": items,
        "comments": len(items),
        "messages": 0,
        "opportunities": sum(1 for i in items if i["opportunity"]),
        "samples": any(i["sample"] for i in items),
    }


def for_panel(user_id, limit=15):
    """The top of the queue for the extension's panel: real people only.

    Examples have no link to open and nobody behind them, so the panel never
    offers one. Text is trimmed to what fits on a card.
    """
    entries = [e for e in queue(user_id)["entries"] if not e["sample"] and e["url"]][:limit]
    return [{
        "kind": e["kind"], "id": e["id"], "who": e["who"], "where": e["where"],
        "text": (e["text"] or "")[:160], "url": e["url"],
        "opportunity": e["opportunity"], "question": e["question"],
        "stage": pipeline.STAGE_LABELS.get(e["stage"]),
        "dm_url": e.get("dm_url"),
    } for e in entries]


def waiting_count(user_id):
    """How many comments are waiting on an answer. Cheap: one count.

    Examples are never counted: this is the number on a red badge, and it
    should only ever mean somebody real is waiting.

    It counts exactly what the queue above shows, and that is the point of it
    being here rather than written out again wherever a badge is drawn. It used
    to add waiting chats, and a badge that counts something the list does not
    show is the specific way an app stops being believed.
    """
    now = pipeline.now_utc()
    with db.get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM post_comments c JOIN comment_posts p ON p.id = c.post_id "
            "WHERE c.user_id = ? AND c.parent_key IS NULL AND c.status = 'open' "
            "AND c.is_mine = 0 AND c.verdict IN ('unanswered', 'unknown') AND p.is_demo = 0 "
            "AND (c.snooze_until IS NULL OR c.snooze_until <= ?) AND c.intent IS NOT 'spam'",
            (user_id, now)).fetchone()[0]
