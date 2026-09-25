"""The optimisations, and the proof they changed nothing but the clock.

Three changes worth guarding:

  one pass   the groups list used to fetch and score once per source. It now
             splits one light pass by source. Every stat must come out
             identical to the per-source computation it replaced.
  parsing    _hours_since grew a hand-rolled fast path. Exactly the same
             strings must parse, to the same hour, and the same junk must
             still come back None.
  caching    static URLs carry the app version and are cached hard; pages
             themselves must still be no-store.

Run: python tests/perf.test.py
"""
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import auth
    import outliers
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("perf@example.com", "a-long-enough-pass", "perfy")
    uid = user["id"]

    # Deliberately awkward data: a group big enough to score, one too small, one
    # whose posts were never measured, comments alongside posts, sample rows,
    # and a post with no timestamp at all.
    def seed():
        with db.get_db() as conn:
            aid = conn.execute("INSERT INTO authors (name) VALUES ('Someone')").lastrowid
            plan = [
                ("Big Group", 0, [(n, 1, "post") for n in (5, 8, 9, 10, 11, 12, 14, 40, 120)]),
                ("Small Group", 0, [(6, 1, "post"), (7, 1, "post")]),
                ("Unread Group", 0, [(0, 0, "post")] * 9),
                ("Mixed Group", 0, [(30, 1, "post")] * 9 + [(4, 1, "comment")] * 9),
                ("Samples", 1, [(20, 1, "post")] * 9),
            ]
            for group, demo, posts in plan:
                sid = conn.execute(
                    "INSERT INTO sources (user_id, fb_id, kind, name, last_capture) "
                    "VALUES (?, ?, 'group', ?, datetime('now'))",
                    (uid, "fb:" + group, group)).lastrowid
                for i, (likes, read, kind) in enumerate(posts):
                    when = "NULL" if (group == "Big Group" and i == 0) else "datetime('now','-2 days')"
                    conn.execute(
                        "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, "
                        "likes, comments, shares, posted_at, is_demo, item_type, engagement_read) "
                        "VALUES (?, ?, ?, ?, ?, ?, 2, 1, %s, ?, ?, ?)" % when,
                        (uid, "%s-%d" % (group, i), sid, aid, "words " * 5,
                         likes, demo, kind, read))
    seed()

    print("the groups list: one pass, identical numbers")
    # The old way, spelled out here so the comparison is against the real thing
    # and not against the new code describing itself.
    with db.get_db() as conn:
        source_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sources WHERE user_id = ? ORDER BY id", (uid,)).fetchall()]
    old = {}
    for sid in source_ids:
        posts = appmod._fetch_posts(source_id=sid, user_id=uid)
        old[sid] = outliers.source_stats(posts) if posts else None

    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    with appmod.app.test_request_context("/groups"):
        from flask import session
        session["user_id"] = uid
        new = {s["id"]: s["stats"] for s in appmod._sources_with_stats()}

    check("every source is still listed", sorted(new), sorted(old))
    for sid in source_ids:
        check("  source %d's stats are byte-identical" % sid, new.get(sid), old.get(sid))
    check("a group that cannot score still says so",
          [s["blocker"] for s in new.values() if s and s["post_count"] == 2], ["too-few"])
    check("the unread group is still blocked as unreadable",
          any(s and s["blocker"] == "unreadable" for s in new.values()), True)

    print()
    print("timestamps parse exactly as before")

    # Both sides read the same instant, or the comparison measures how long
    # the loop took rather than whether the parsing agrees.
    fixed = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    def reference(timestamp):
        """_hours_since as it was written before the fast path."""
        if not timestamp:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(timestamp[:19], fmt).replace(tzinfo=timezone.utc)
                return (fixed - dt).total_seconds() / 3600.0
            except ValueError:
                continue
        return None

    cases = [
        "2026-09-21 14:30:00", "2026-09-21T14:30:00", "2026-09-21",
        "2026-09-21T14:30:00+00:00", "2026-09-21 14:30:00.123456",
        "2026-02-29 00:00:00",          # not a leap year
        "2026-13-45 99:99:99", "2026-09-21 14:30", "not a date at all",
        "", None, "0000-00-00 00:00:00",
    ]
    for value in cases:
        mine_ = outliers._hours_since(value, fixed)
        ref = reference(value)
        check("  %r" % (value,), mine_, ref)

    print()
    print("a clock read once per pass, not once per post")
    rows = appmod._scoring_rows(user_id=uid)
    ages = {s["id"]: s["age_hours"] for s in outliers.score_posts(rows)}
    again = {s["id"]: s["age_hours"] for s in outliers.score_posts(rows)}
    check("ages are stable across passes", ages, again)
    check("a post with no timestamp has no age",
          None in [v for v in ages.values()], True)

    print()
    print("assets are cached, pages are not")
    html = client.get("/settings").get_data(as_text=True)
    check("the stylesheet URL carries the version",
          ("css/outlier.css?v=%s" % appmod.APP_VERSION) in html, True)
    check("so does the script",
          ("js/outlier.js?v=%s" % appmod.APP_VERSION) in html, True)
    asset = client.get("/static/css/outlier.css?v=%s" % appmod.APP_VERSION)
    check("the stylesheet is cacheable for a long time",
          "31536000" in asset.headers.get("Cache-Control", ""), True)
    page = client.get("/settings")
    check("but a page is never stored",
          "no-store" in page.headers.get("Cache-Control", ""), True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("faster, and the numbers did not move")
    return 0


if __name__ == "__main__":
    sys.exit(main())
