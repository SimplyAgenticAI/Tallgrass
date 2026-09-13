"""Where people stop, between signing up and paying.

Fifteen accounts, nobody paying, and the only two facts on record were "made an
account" and "captured a post". Everything between those — did they click
install, did the extension ever connect, did they see anything worth paying for,
did they even open pricing — was invisible, so every fix to the funnel was a
guess about which step was the wall.

One row per account per step, holding the FIRST time it happened. Later repeats
are ignored, so this answers "did they ever get here, and how long did it take",
not "how often".

Two chains, because they are not one line:

  activation  signup → went to install → connected → captured → saw an outlier
  buying      opened pricing → started checkout → paid

Somebody can open pricing before installing anything, so a pricing view says
nothing about activation. Within a chain, reaching a step implies the ones
before it: a capture means the extension connected even if that event predates
this module, and an install from an email link never touches the tracked
button. Counting those as reached keeps the funnel from reading as more people
capturing than connecting.

Never raises into a page. A metric is not worth a failed request.
"""

import logging
import statistics
from datetime import datetime

import db

log = logging.getLogger("tallgrass")


# (key, label, chain). Order within a chain is the funnel order.
STEPS = (
    ("signup", "Signed up", "activation"),
    ("store_click", "Went to install", "activation"),
    ("connected", "Extension connected", "activation"),
    ("first_capture", "Captured a real post", "activation"),
    # Strong or Breakout on one of their own posts — see outliers._tier.
    ("outlier_seen", "Saw a 3×+ outlier of their own", "activation"),
    ("pricing_view", "Opened pricing", "buying"),
    ("checkout", "Started checkout", "buying"),
    ("paid", "Paid", "buying"),
)
STEP_KEYS = tuple(key for key, _label, _chain in STEPS)
CHAIN = {key: chain for key, _label, chain in STEPS}

BACKFILLED_KEY = "funnel_backfilled"

# Steps already known to be on record, so a feed load that re-reaches
# "outlier_seen" costs nothing. Per process, and only ever a shortcut: the
# primary key is what actually keeps one row.
_recorded = set()


def record(user_id, step):
    """Note that this account reached this step. First time only.

    Reads before it writes. The feed calls this on every load, and an INSERT
    OR IGNORE takes the write lock even when it ignores — which would queue a
    page view behind a capture batch for no reason. Call it outside any open
    transaction: it opens its own connection.
    """
    if not user_id or step not in STEP_KEYS or step == "signup":
        return
    key = (int(user_id), step)
    if key in _recorded:
        return
    try:
        with db.get_db() as conn:
            seen = conn.execute(
                "SELECT 1 FROM funnel_events WHERE user_id = ? AND step = ?",
                key).fetchone()
            if not seen:
                conn.execute(
                    "INSERT OR IGNORE INTO funnel_events (user_id, step) "
                    "VALUES (?, ?)", key)
        _recorded.add(key)
    except Exception:                                   # noqa: BLE001
        log.warning("funnel: could not record %s for user %s", step, user_id,
                    exc_info=True)


def backfill_once():
    """Recover what history already knows, a single time.

    Real captures and pricing views predate this module and are sitting in
    `posts` and `visits`. The click, the connection and the outlier view left
    no trace, so they are not invented — the chain rule in report() covers the
    ones a later step proves. A paid account's payment time is unknown and
    stays NULL rather than being stamped with today.
    """
    if db.get_setting(BACKFILLED_KEY, ""):
        return 0
    try:
        with db.get_db() as conn:
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO funnel_events (user_id, step, first_at)
                SELECT user_id, 'first_capture', MIN(captured_at) FROM posts
                 WHERE is_demo = 0 AND user_id IN (SELECT id FROM users)
                 GROUP BY user_id
                """)
            conn.execute(
                """
                INSERT OR IGNORE INTO funnel_events (user_id, step, first_at)
                SELECT user_id, 'pricing_view', MIN(created_at) FROM visits
                 WHERE path = '/pricing' AND user_id IN (SELECT id FROM users)
                 GROUP BY user_id
                """)
            conn.execute(
                """
                INSERT OR IGNORE INTO funnel_events (user_id, step, first_at)
                SELECT id, 'paid', NULL FROM users
                 WHERE plan = 'pro' AND stripe_subscription_id IS NOT NULL
                """)
            added = conn.total_changes - before
        db.set_setting(BACKFILLED_KEY, "1")
        return added
    except Exception:                                   # noqa: BLE001
        # Never stops the app booting. Unflagged, so the next start retries.
        log.exception("funnel backfill failed")
        return 0


def _parse(stamp):
    """SQLite's 'YYYY-MM-DD HH:MM:SS', or an ISO string with a T. None if not."""
    if not stamp:
        return None
    try:
        return datetime.strptime(str(stamp)[:19].replace("T", " "),
                                 "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _duration(hours):
    if hours is None:
        return None
    if hours < 1:
        return "<1h"
    if hours < 48:
        return "%dh" % round(hours)
    return "%dd" % round(hours / 24)


def _reached(has, step):
    """Has this step, or any later step in the same chain."""
    chain = [key for key, _l, c in STEPS if c == CHAIN[step]]
    return any(key in has for key in chain[chain.index(step):])


def report(days=30):
    """The funnel across every non-admin account, and for recent signups.

    Admins are left out: the operator reaches every step by testing, and one
    account at 100% in a group of fifteen moves every percentage on the page.
    """
    with db.get_db() as conn:
        users = [dict(r) for r in conn.execute(
            "SELECT id, created_at FROM users WHERE COALESCE(is_admin, 0) = 0")]
        events = conn.execute(
            "SELECT user_id, step, first_at FROM funnel_events").fetchall()
        cutoff = conn.execute(
            "SELECT datetime('now', ?)", ("-%d days" % int(days),)).fetchone()[0]

    stamps = {}
    for row in events:
        stamps.setdefault(row["user_id"], {})[row["step"]] = row["first_at"]

    for user in users:
        user["has"] = set(stamps.get(user["id"], {})) | {"signup"}
        user["recent"] = (user["created_at"] or "") >= cutoff

    steps = []
    previous = {}
    for key, label, chain in STEPS:
        reached = [u for u in users if _reached(u["has"], key)]
        recent = [u for u in reached if u["recent"]]

        # Time from signup, only for accounts where this step was actually
        # recorded. An implied step has no time, and zero would be a lie.
        hours = []
        for user in reached:
            joined = _parse(user["created_at"])
            got = _parse(stamps.get(user["id"], {}).get(key))
            if key != "signup" and joined and got and got >= joined:
                hours.append((got - joined).total_seconds() / 3600)

        prior = previous.get(chain)
        steps.append({
            "key": key,
            "label": label,
            "chain": chain,
            "count": len(reached),
            "recent": len(recent),
            "pct": round(100.0 * len(reached) / len(users)) if users else 0,
            # Lost since the previous step of the same chain. The first step
            # of each chain has no predecessor to lose people from.
            "lost": (prior["count"] - len(reached)) if prior else None,
            "median": _duration(statistics.median(hours)) if hours else None,
        })
        previous[chain] = steps[-1]

    activation = [s for s in steps if s["chain"] == "activation"]
    leak = None
    for before, after in zip(activation, activation[1:]):
        if after["lost"] and (leak is None or after["lost"] > leak["lost"]):
            leak = {"lost": after["lost"], "of": before["count"],
                    "from": before["label"], "to": after["label"]}

    # How far each account got, for the per-account table.
    furthest = {}
    for user in users:
        got = [label for key, label, chain in STEPS
               if chain == "activation" and key in user["has"]]
        bought = [label for key, label, chain in STEPS
                  if chain == "buying" and key in user["has"]]
        furthest[user["id"]] = " · ".join(
            part for part in (got[-1] if got else None,
                              bought[-1] if bought else None) if part)

    return {
        "steps": steps,
        "total": len(users),
        "recent_total": sum(1 for u in users if u["recent"]),
        "days": int(days),
        "leak": leak,
        "furthest": furthest,
    }
