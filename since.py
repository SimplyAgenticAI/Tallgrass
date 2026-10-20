"""What broke out since you were last here.

The reason this exists is a trade that was half-made. Comments and DMs were
removed from the product, and they were the only thing in it anybody opened
DAILY — scoring is a weekly habit, replying was an hourly one. Taking the inbox
out without putting something in its place leaves no reason to come back
between scans, which costs retention even though the feature removed was the
weaker one.

So: the one thing this app knows that nothing else does, said on arrival. Not a
digest and not a notification — a line at the top of the feed naming the posts
that cleared their group's median since the last look, which is a fact nobody
else can tell them.

It claims nothing it cannot support:

  - Real captures only. A sample post breaking out is a demonstration.
  - A usable baseline only. Without one there is no multiple, and "broke out"
    with no number behind it is the kind of claim this app does not make.
  - Measured on captured_at, not posted_at. "New to me" is when it arrived
    here; a post written three weeks ago that was scanned this morning is news
    to the reader and an old post to Facebook.

The comparison is strictly greater-than, and captured_at has one-second
resolution, so a post that arrives in the same second as the mark is counted as
already seen. That is deliberate: the alternative is >=, which re-announces the
very post that set the watermark and leaves a card that never clears. The cost
is a post captured inside the same second as a page load, which takes a scan
starting and finishing between the request and the response.

The watermark is the subtle part. It advances only to the newest post actually
ANNOUNCED, and not at all when there was nothing to announce. A post captured
before its group had a baseline is unscoreable and so unannounceable, and
moving the mark past it on sight would mean it never gets mentioned — it would
become a breakout in silence. Left behind the mark, it waits until the group
can be scored and is announced then.
"""

MARK = "feed_seen_at"


def _stamp(value):
    """One shape for a timestamp, so a comparison means what it looks like.

    This is here because of a bug that made the whole feature silently dead.
    The mark was being written with pipeline.now_utc(), which is
    "2026-10-20T18:00:00", while a post's captured_at comes from SQLite's
    CURRENT_TIMESTAMP, which is "2026-10-20 18:00:00". Compared as strings, the
    space at index ten sorts BEFORE the "T" - so every post in the database
    looked older than the mark, nothing was ever new, and the card never
    appeared. No error, no log line, just a feature that did nothing.

    So both sides go through here, and anything stored by an older build still
    compares correctly.
    """
    text = str(value or "").strip().replace("T", " ")
    # Fractional seconds on one side and not the other would do the same thing
    # on a tie.
    return text.split(".")[0]


def now_mark():
    """The clock the rows are stamped by, in the format they are stamped in.

    Read from SQLite rather than Python so the mark and captured_at cannot
    disagree about either the time or the shape of it.
    """
    import db
    try:
        with db.get_db() as conn:
            return conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    except Exception:                         # noqa: BLE001 - never break the feed
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# At most this many named. The count carries the rest.
#
# Three because the card is a prompt, not a page: the feed it sits on top of is
# where the whole list lives, and a card that reprints it is a second feed.
TOP_N = 3


def whats_new(scored, mark):
    """Breakouts captured since `mark`, newest-best first.

    `scored` is the feed's own scoring pass — this adds no query and no second
    pass over the data. `mark` is the stored watermark, or falsy on a first
    visit, which yields nothing: "since you were last here" means nothing when
    there was no last time, and a card announcing forty-seven posts to somebody
    who has just arrived is noise.

    Returns {"count", "items", "watermark"}. `watermark` is the newest
    captured_at among the items, or None when there are none — see the module
    note for why it is that rather than "now".
    """
    if not mark:
        return {"count": 0, "items": [], "watermark": None}

    since_when = _stamp(mark)
    fresh = [
        s for s in scored
        if not s.get("is_demo")
        and (s.get("item_type") or "post") == "post"
        and s.get("has_baseline")
        and s.get("outlier_multiple") is not None
        and s.get("tier") in ("breakout", "strong")
        and _stamp(s.get("captured_at")) > since_when
    ]
    if not fresh:
        return {"count": 0, "items": [], "watermark": None}

    fresh.sort(key=lambda s: s["outlier_multiple"] or 0, reverse=True)
    return {
        "count": len(fresh),
        "items": fresh[:TOP_N],
        "watermark": max(s["captured_at"] for s in fresh),
    }
