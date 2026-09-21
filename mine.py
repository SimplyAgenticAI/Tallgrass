"""Which captured posts are the user's own, and how they did against the group.

The loop the product never closed: it shows what worked for other people, the
user posts their own version — and never hears how it went. Their own posts
are usually already captured, because they sit in the same groups they scan.
What was missing is knowing which ones are theirs.

Identity is a name the user confirms in Settings, matched against the author
of captured posts. It is suggested from the one place the extension already
knows who they are for certain: comments it recorded as theirs (is_mine),
which it works out from Facebook's own "Comment as <name>" composer. Nothing
here touches extraction, so nothing here needs a store review.

Name matching can collide — two Jane Smiths in one group. That is why this is
shown as a list the user can check before anything is built on top of it.

Accuracy rules as everywhere: a post with no usable baseline gets no multiple,
and demo posts are never anybody's.
"""

from datetime import datetime

import db
import outliers

SETTING = "my_fb_names"


def _norm(name):
    return " ".join((name or "").split()).lower()


def get_names(user_id):
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, SETTING)).fetchone()
    raw = row["value"] if row else ""
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


def set_names(user_id, text):
    names = []
    for part in (text or "").replace("\n", ",").split(","):
        part = " ".join(part.split())[:60]
        if part and _norm(part) not in {_norm(n) for n in names}:
            names.append(part)
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, SETTING, ", ".join(names[:5])))
    return names[:5]


def suggested_names(user_id):
    """Full names the extension recorded on the user's own comments, commonest
    first. Full names only — a first name alone is not proof of anyone."""
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT author, COUNT(*) AS n FROM post_comments "
            "WHERE user_id = ? AND is_mine = 1 AND author LIKE '% %' "
            "GROUP BY LOWER(author) ORDER BY n DESC LIMIT 3",
            (user_id,)).fetchall()
    return [r["author"] for r in rows]


def names_for(user_id):
    """What to match on: what they confirmed, else what the comments suggest.
    Returns (names, confirmed)."""
    names = get_names(user_id)
    if names:
        return names, True
    return suggested_names(user_id)[:1], False


def my_posts(user_id, names=None):
    """The user's own captured posts, scored against their groups, best first.

    Scored over every real post the account has, because that is what the
    baselines are made of; only the matches are returned.
    """
    if names is None:
        names, _ = names_for(user_id)
    wanted = {_norm(n) for n in names if _norm(n)}
    if not wanted:
        return []
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT p.id, p.source_id, p.item_type, p.likes, p.comments, "
            "p.shares, p.engagement_read, p.posted_at, p.captured_at, "
            "p.is_demo, p.fb_post_id, p.parent_fb_id, p.body, p.permalink, "
            "a.name AS author_name, s.name AS source_name "
            "FROM posts p LEFT JOIN authors a ON a.id = p.author_id "
            "LEFT JOIN sources s ON s.id = p.source_id "
            "WHERE p.user_id = ? AND p.is_demo = 0 "
            "ORDER BY p.posted_at DESC", (user_id,)).fetchall()]
    scored = outliers.score_posts(rows)
    mine = [s for s in scored
            if (s.get("item_type") or "post") == "post"
            and _norm(s.get("author_name")) in wanted]
    for post in mine:
        if not post.get("has_baseline"):
            post["outlier_multiple"] = None
    mine.sort(key=lambda s: (s["outlier_multiple"] is not None,
                             s["outlier_multiple"] or 0), reverse=True)
    return mine


def _median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return round(values[mid], 1)
    return round((values[mid - 1] + values[mid]) / 2, 1)


def _month_label(month):
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return month


def _rollup(posts):
    scored = [p["outlier_multiple"] for p in posts if p["outlier_multiple"] is not None]
    return {
        "count": len(posts),
        "scored": len(scored),
        "beat": sum(1 for m in scored if m >= 1),
        "median": _median(scored),
        "best": max(scored) if scored else None,
    }


def results(user_id):
    """Everything the My results page shows. Only confirmed names count here —
    a page titled "your results" must not be built on a guess."""
    names = get_names(user_id)
    posts = my_posts(user_id, names) if names else []

    groups = {}
    for p in posts:
        groups.setdefault(p["source_id"], {"name": p.get("source_name") or "a group",
                                           "posts": []})["posts"].append(p)
    by_group = sorted(
        ({"name": g["name"], **_rollup(g["posts"])} for g in groups.values()),
        key=lambda g: (g["median"] is not None, g["median"] or 0), reverse=True)

    months = {}
    for p in posts:
        month = (p.get("posted_at") or p.get("captured_at") or "")[:7]
        if month:
            months.setdefault(month, []).append(p)
    by_month = [{"month": m, "label": _month_label(m), **_rollup(months[m])}
                for m in sorted(months)][-12:]

    return {
        "names": names,
        "suggested": suggested_names(user_id),
        "overall": _rollup(posts),
        "by_group": by_group,
        "by_month": by_month,
        "posts": posts,
    }


def recent(user_id, since):
    """Confirmed-name posts first seen on or after `since` (SQLite timestamp
    text). For the weekly brief."""
    names = get_names(user_id)
    if not names:
        return []
    return [p for p in my_posts(user_id, names)
            if (p.get("captured_at") or "")[:19].replace("T", " ") >= since]


def summary(user_id):
    """What Settings shows: the names, whether confirmed, and the matches."""
    names, confirmed = names_for(user_id)
    posts = my_posts(user_id, names)
    scored = [p["outlier_multiple"] for p in posts if p["outlier_multiple"] is not None]
    return {
        "names": names,
        "confirmed": confirmed,
        "suggested": suggested_names(user_id),
        "posts": posts,
        "groups": len({p["source_id"] for p in posts}),
        "beat": sum(1 for m in scored if m >= 1),
        "scored": len(scored),
    }
