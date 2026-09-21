"""The weekly brief: what somebody's groups rewarded this week, by email.

Everything else in this app only happens while somebody is on Facebook with
the extension running. Nothing ever reached out to an ACTIVE user — welcome and
nudge are both about getting started — so once the novelty wore off there was
no reason in anybody's week to come back. This is that reason: once a week,
their best posts from recent scans, how many people are waiting on a reply,
and a nudge to rescan when the numbers have gone stale.

This module only composes. Sending, switches, the once-a-week claim and the
unsubscribe all belong to outreach, the same as every other automatic email.

The accuracy rules hold here as everywhere: a post with no usable baseline is
never given a multiple, demo posts are never counted, and when there is
nothing true to say about a week the email says that instead of padding.
"""

from datetime import datetime, timedelta, timezone

import db
import mine
import outliers

# What counts as "this week". A post seen on any scan in the window — first
# captured or refreshed by a rescan — is fair game for the top list.
WINDOW_DAYS = 7

# Nobody is mailed a brief after this long without a scan. They have stopped
# using it, and a weekly email about data a month old is noise that trains
# them to ignore the sender.
ACTIVE_DAYS = 30

# A post has to beat its group by at least this much to be called out. Same
# floor as the "Above baseline" tier.
MIN_MULTIPLE = 1.5

TOP_N = 3
SNIPPET = 110


def _stamp(value):
    """SQLite timestamp text, normalised so it compares as a string."""
    return (value or "")[:19].replace("T", " ")


def _cutoff(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _rows(user_id):
    """Every real row this account has, with what scoring needs plus freshness."""
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT p.id, p.source_id, p.item_type, p.likes, p.comments, "
            "p.shares, p.engagement_read, p.posted_at, p.captured_at, "
            "p.updated_at, p.is_demo, p.fb_post_id, p.parent_fb_id "
            "FROM posts p WHERE p.user_id = ? AND p.is_demo = 0 "
            "ORDER BY p.posted_at DESC", (user_id,)).fetchall()]


def _seen(row):
    return max(_stamp(row.get("captured_at")), _stamp(row.get("updated_at")))


def _details(user_id, ids):
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with db.get_db() as conn:
        return {r["id"]: dict(r) for r in conn.execute(
            "SELECT p.id, p.body, p.post_type, s.name AS source_name, "
            "a.name AS author_name FROM posts p "
            "LEFT JOIN sources s ON s.id = p.source_id "
            "LEFT JOIN authors a ON a.id = p.author_id "
            "WHERE p.user_id = ? AND p.id IN (%s)" % marks,
            [user_id] + list(ids)).fetchall()}


def _snippet(text):
    text = " ".join((text or "").split())
    if len(text) <= SNIPPET:
        return text
    return text[:SNIPPET].rsplit(" ", 1)[0] + "…"


def _waiting(user_id):
    try:
        import today
        return today.waiting_count(user_id)
    except Exception:                         # noqa: BLE001 - a brief without it
        return 0


def compose(user_id, base_url):
    """This account's brief as {"headline", "summary"}, or None if there is
    nothing honest to send (no real posts, or no scan in ACTIVE_DAYS)."""
    rows = _rows(user_id)
    if not rows:
        return None
    last_seen = max(_seen(r) for r in rows)
    if last_seen < _cutoff(ACTIVE_DAYS):
        return None

    # Scored over the whole history, because that is what the baselines are
    # made of; only the top list is limited to the week.
    week = _cutoff(WINDOW_DAYS)
    scored = outliers.score_posts(rows)
    recent = [s for s in scored if _seen(s) >= week]
    groups = len({s["source_id"] for s in recent})
    top = sorted(
        (s for s in recent
         if (s.get("item_type") or "post") == "post"
         and s.get("has_baseline") and s.get("outlier_multiple") is not None
         and s["outlier_multiple"] >= MIN_MULTIPLE),
        key=lambda s: s["outlier_multiple"], reverse=True)[:TOP_N]
    info = _details(user_id, [s["id"] for s in top])
    waiting = _waiting(user_id)

    lines = []
    if top:
        lines.append("Your top posts from this week's scans:")
        for n, post in enumerate(top, 1):
            d = info.get(post["id"], {})
            lines.append("")
            lines.append("%d. %s× the group's usual — %s" % (
                n, post["outlier_multiple"], d.get("source_name") or "a group"))
            quote = _snippet(d.get("body"))
            if quote:
                by = d.get("author_name")
                lines.append('   "%s"%s' % (quote, (" — " + by) if by else ""))
            lines.append("   %spost/%d" % (base_url, post["id"]))
        lines.append("")
        lines.append("Open any of them and hit Write to make your own version "
                     "while the idea is still working.")
        headline = "%s× in %s" % (top[0]["outlier_multiple"],
                                   info.get(top[0]["id"], {}).get("source_name")
                                   or "your groups")
    elif recent:
        lines.append("You scanned %d group%s this week and nothing stood clear "
                     "of the usual — that's normal for a quiet week, and it "
                     "means the posts that do break out next time will mean "
                     "more." % (groups, "" if groups == 1 else "s"))
        headline = "a quiet week in your groups"
    else:
        lines.append("You haven't scanned this week, so these numbers are "
                     "going stale. Your groups have kept posting — a quick "
                     "scan shows what's winning right now.")
        headline = "time for a fresh scan"

    # Their own posts, only under a name they confirmed in Settings — an email
    # saying "your post" about somebody else's would end the trust in it.
    own = mine.recent(user_id, week)
    own_hit = False
    if own:
        scored_own = [p for p in own if p["outlier_multiple"] is not None]
        lines.append("")
        if scored_own:
            best = scored_own[0]
            lines.append("Your own posts this week: %d. Your best did %s× "
                         "its group's usual, in %s." % (
                             len(own), best["outlier_multiple"],
                             best.get("source_name") or "a group"))
            # Only a win goes in the subject line; a 0.6× is said plainly
            # in the body, not announced.
            if best["outlier_multiple"] >= 1:
                headline = "your post hit %s×" % best["outlier_multiple"]
                own_hit = True
        else:
            lines.append("Your own posts this week: %d — not enough scanned "
                         "in those groups yet to score them." % len(own))
        lines.append("%sresults" % base_url)

    if waiting:
        lines.append("")
        lines.append("%d %s waiting on a reply from you:" % (
            waiting, "person is" if waiting == 1 else "people are"))
        lines.append("%stoday" % base_url)
        if not top and not own_hit:
            headline = "%d waiting on a reply" % waiting

    return {"headline": headline, "summary": "\n".join(lines)}
