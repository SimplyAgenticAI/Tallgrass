"""The walkthrough: where things are, pointed at on the actual page.

The app already says what to do next — _next_step in app.py computes one action
from the database and puts it at the top of the feed. What it cannot do is
point. Somebody who has just signed up is looking at a dashboard full of sample
data and a navigation bar of words they have no reason to understand yet, and
the most common thing they do is nothing.

So this is a spotlight on real elements, driven from the database:

  - a step whose job is already done is never shown, so the walkthrough cannot
    tell somebody to install an extension they installed last week
  - a step whose target is not on the page is skipped by the client rather
    than pointing at nothing
  - it runs once, and after that only when asked for from Settings
  - it never blocks: every step can be left, and leaving is remembered

Targets are CSS selectors built from real routes, so no markup exists purely
for the walkthrough and a renamed page cannot leave a step pointing at a link
that is no longer there — url_for is the single source of both.
"""

import db

SEEN = "guide_seen"


def seen(user_id):
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, SEEN)).fetchone()
    return bool(row and row["value"] == "1")


def mark_seen(user_id, value=True):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, SEEN, "1" if value else "0"))


def _facts(user, conn):
    """The few things the steps need to know, in one trip."""
    uid = user["id"]
    real = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE user_id = ? AND is_demo = 0",
        (uid,)).fetchone()[0]
    remixed = conn.execute(
        "SELECT 1 FROM remixes WHERE user_id = ? LIMIT 1", (uid,)).fetchone()
    waiting = conn.execute(
        "SELECT 1 FROM post_comments WHERE user_id = ? AND is_mine = 0 LIMIT 1",
        (uid,)).fetchone()
    return {
        "connected": bool(user.get("api_key_prefix")),
        "captured": real,
        "remixed": bool(remixed),
        "comments": bool(waiting),
    }


def steps(user, urls):
    """The walkthrough for this account.

    `urls` is {name: path} from the caller, which owns url_for. Each step is
    {key, title, body, target, href}; `target` is a selector the client
    highlights, and a step whose target is missing is skipped there.
    """
    if not user:
        return []
    with db.get_db() as conn:
        facts = _facts(user, conn)

    out = []

    def add(key, title, body, target, href=None):
        out.append({"key": key, "title": title, "body": body,
                    "target": target, "href": href})

    # Always first, and the only step that is about the screen they are on
    # rather than somewhere to go.
    add("feed", "This is your feed",
        "Every post here is scored against what's normal in the group it came "
        "from — so a quiet group's breakout doesn't get buried under a big "
        "group's ordinary post. Until you scan, these are samples, marked as "
        "such.",
        'a[href="%s"]' % urls["feed"])

    if not facts["connected"] or not facts["captured"]:
        add("extension", "One step to make it yours",
            "Tallgrass reads posts as you scroll Facebook, so it needs a "
            "Chrome extension. It's on the Chrome Web Store — one click, then "
            "come back here and it connects itself.",
            'a[href="%s"]' % urls["capture"], urls["capture"])

    if facts["captured"]:
        add("groups", "What each group needs",
            "A group can only be scored once enough of its posts have been "
            "read. This page tells you exactly what each one is still short "
            "of, instead of leaving you guessing why a number is missing.",
            'a[href="%s"]' % urls["groups"], urls["groups"])

    if not facts["remixed"]:
        add("write", "Turn a winner into your own post",
            "Finding what worked is half of it. Write takes a post that beat "
            "its group and builds versions in your voice — you pick the one "
            "you'd actually publish.",
            'a[href="%s"]' % urls["write"], urls["write"])

    if facts["comments"]:
        add("today", "Nobody waiting too long",
            "Comments and messages waiting on a reply collect here, oldest "
            "first, with a draft ready for each. Tallgrass never sends "
            "anything — you approve every word.",
            'a[href="%s"]' % urls["today"], urls["today"])

    add("playbook", "How to win in a group",
        "The Playbook is what to do with a winner once you've found one — "
        "which ones repeat, which ones are a one-off, and how to borrow a "
        "mechanic without copying a post.",
        'a[href="%s"]' % urls["playbook"], urls["playbook"])

    return out


def state(user, urls):
    """What the page needs: whether to run unasked, and the steps."""
    if not user:
        return {"run": False, "steps": []}
    return {"run": not seen(user["id"]), "steps": steps(user, urls)}
