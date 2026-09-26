"""Letting other people's old posts go, and keeping everything that matters.

A captured post measures about 4KB — a caption, a long signed CDN URL,
Facebook's description of the image and, once a graphic has been read, a couple
of thousand characters of vision description. Ten thousand posts is 39MB, and
nothing bounded the total, so "unlimited" was a promise the disk could not keep.

The value of somebody else's post decays fast. What a group rewards NOW is what
its median should describe; a post from a year ago in a stranger's group is
storage, not evidence. So other people's posts age out after
billing.RETENTION_MONTHS, and four things never do:

  their own posts     the whole of My results is built on them, and they are a
                      tiny fraction of any account
  saved posts         somebody pressed a button to keep it
  remixed posts       the remix references the post it came from

The reply pipeline is not in this table at all: comment threads and Messenger
chats live in comment_posts / message_threads, keyed by Facebook's own ids, so
nothing here can touch them. Said explicitly because "will this delete the
conversation I'm mid-way through" is the first question anybody would ask.

TWO RULES THAT MAKE THIS SAFE
-----------------------------
A per-group floor. A source needs MIN_SAMPLE measured posts before anything in
it can be scored at all, so pruning a group down to nothing would silently stop
it scoring and make it look broken. The newest posts in every group are kept
regardless of age — always enough to keep its baseline alive.

Dry run by default. `enabled()` is off, and `report()` says exactly what WOULD
go. No rule that deletes somebody's data should run before its output has been
read on real accounts. Turning it on is a decision, taken on the admin page,
after looking.
"""

import logging

import billing
import db
import outliers
from db import get_viewer_names

log = logging.getLogger("tallgrass.retention")

ENABLED_KEY = "retention_enabled"

# Never take a source below this many posts, whatever their age. MIN_SAMPLE is
# what scoring needs; the margin is so that one unreadable post does not tip a
# group back under the line.
FLOOR_PER_SOURCE = outliers.MIN_SAMPLE * 2


def enabled():
    return db.get_setting(ENABLED_KEY, "") == "on"


def set_enabled(on):
    db.set_setting(ENABLED_KEY, "on" if on else "off")
    return enabled()


def _candidates(conn, months, floor):
    """Post ids that may be dropped, and what is protecting the rest.

    One query per rule rather than one clever query: each exemption is a
    sentence somebody can check against the docstring above.
    """
    cutoff = "-%d months" % int(months)

    # Their own posts — and NOT only under the name they confirmed in Settings.
    #
    # The first version of this read mine.get_names, which is the name somebody
    # typed into Settings. Almost nobody has, so almost nobody's own posts were
    # protected, and the exemption that makes this rule safe would have applied
    # to hardly anyone. Every name the app has reason to believe is theirs
    # counts instead: what they confirmed, what their own comments say (the
    # extension reads "Comment as <name>" from Facebook itself), and the name
    # they gave for stripping their own name out of captures.
    import mine
    own_names = set()
    for user_id in [r["id"] for r in conn.execute(
            "SELECT id FROM users").fetchall()]:
        candidates = list(mine.get_names(user_id))
        candidates += mine.suggested_names(user_id)
        candidates += [n for n in get_viewer_names(conn, user_id) if " " in n]
        for name in candidates:
            cleaned = " ".join((name or "").split()).lower()
            if cleaned:
                own_names.add((user_id, cleaned))

    # OLD BY EVERY CLOCK, not just by when it was written.
    #
    # Ageing on posted_at alone would delete a post somebody captured or
    # re-scanned yesterday, because the post itself is old — so scanning a group
    # with older posts in it would be followed by the count going DOWN, which
    # from the outside is indistinguishable from losing data. A re-scan bumps
    # updated_at (upsert_post), the first capture sets captured_at, and
    # posted_at is when Facebook says it was written. A post goes only when all
    # three are past the window: old content that nobody has touched since.
    rows = conn.execute(
        """
        SELECT p.id, p.user_id, p.source_id, p.posted_at, p.captured_at,
               LOWER(a.name) AS author
        FROM posts p LEFT JOIN authors a ON a.id = p.author_id
        WHERE p.is_demo = 0
          AND COALESCE(p.posted_at, p.captured_at) < datetime('now', ?)
          AND COALESCE(p.captured_at, p.posted_at) < datetime('now', ?)
          AND COALESCE(p.updated_at, p.captured_at, p.posted_at) < datetime('now', ?)
          AND NOT EXISTS (SELECT 1 FROM saved s WHERE s.post_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM remixes r WHERE r.post_id = p.id)
        ORDER BY COALESCE(p.posted_at, p.captured_at) ASC
        """, (cutoff, cutoff, cutoff)).fetchall()

    # The floor: how many posts each source has in total, so the newest are
    # kept even when everything in the group is old.
    totals = {r["source_id"]: r["n"] for r in conn.execute(
        "SELECT source_id, COUNT(*) AS n FROM posts "
        "WHERE is_demo = 0 GROUP BY source_id").fetchall()}

    doomed = []
    kept_own = kept_floor = 0
    dropping = {}
    for row in rows:
        author = " ".join((row["author"] or "").split())
        if (row["user_id"], author) in own_names:
            kept_own += 1
            continue
        source = row["source_id"]
        remaining = totals.get(source, 0) - dropping.get(source, 0)
        if remaining <= floor:
            kept_floor += 1
            continue
        dropping[source] = dropping.get(source, 0) + 1
        doomed.append(row["id"])

    return doomed, {"own": kept_own, "floor": kept_floor}


def report(months=None, floor=FLOOR_PER_SOURCE):
    """What retention would remove right now. Reads only."""
    months = billing.RETENTION_MONTHS if months is None else months
    try:
        with db.get_db() as conn:
            doomed, kept = _candidates(conn, months, floor)
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM posts WHERE is_demo = 0").fetchone()["n"]
    except Exception:                         # noqa: BLE001
        log.warning("retention report failed", exc_info=True)
        return {"months": months, "posts": 0, "mb": 0.0, "total": 0,
                "kept": {"own": 0, "floor": 0}, "enabled": False, "error": True}

    return {
        "months": months,
        "posts": len(doomed),
        "mb": round(len(doomed) * 4096 / 1048576, 1),
        "total": total,
        "kept": kept,
        "enabled": enabled(),
        "error": False,
    }


def sweep(months=None, floor=FLOOR_PER_SOURCE, limit=5000):
    """Actually remove them. Returns (removed, error).

    Does nothing unless switched on. `limit` keeps one sweep bounded so a first
    run on a large account cannot sit inside somebody's page load.
    """
    if not enabled():
        return 0, "Retention is switched off — nothing was removed."
    months = billing.RETENTION_MONTHS if months is None else months
    try:
        with db.get_db() as conn:
            doomed, _kept = _candidates(conn, months, floor)
            doomed = doomed[:limit]
            if not doomed:
                return 0, None
            marks = ",".join("?" * len(doomed))
            # Only the posts. Nothing saved or remixed is ever a candidate —
            # _candidates excludes them with NOT EXISTS — so there is nothing
            # pointing at these rows to clean up, and a DELETE against saved or
            # remixes here would be a no-op that implied otherwise.
            conn.execute("DELETE FROM posts WHERE id IN (%s)" % marks, doomed)
        # Outside the transaction: the pictures of posts that have just gone.
        # Without this the cache keeps paying for them until the LRU cap
        # eventually notices, on the disk this whole feature exists to protect.
        db._forget_pictures(doomed)
        log.info("retention removed %d posts older than %d months",
                 len(doomed), months)
        return len(doomed), None
    except Exception as exc:                  # noqa: BLE001
        log.warning("retention sweep failed", exc_info=True)
        return 0, "Retention failed: %s" % exc
