"""Ranking from light rows must give the same answer as ranking from full ones.

The feed used to load every post in an account — every word of every caption —
to work out a median from three integers. Measured at 363MB for a single
request on a 20,000-post account, on a box with 512MB.

Scoring never reads `body` or `image_text`, so the ranking is now computed
from counts alone and the words are fetched only for the page being shown.
That is only safe if it is EXACTLY equivalent, and "looks right" is not a
standard. These tests compare the two paths field by field over the whole set.

Run: python tests/paging.test.py
"""
import logging
import os
import random
import shutil
import sys
import tempfile

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
    auth.create_user("owner@example.com", "a-long-enough-pass", "birchwood")

    # A deliberately awkward spread: several sources, a mix of scoreable and
    # not, unread rows, comments alongside posts, demo alongside real, and
    # long bodies — the fields the light query deliberately drops.
    random.seed(11)
    with db.get_db() as conn:
        for sid in range(1, 5):
            conn.execute("INSERT INTO sources (id, user_id, fb_id, kind, name) "
                         "VALUES (?, 1, ?, 'group', ?)",
                         (sid, "group:%d" % sid, "Group %d" % sid))
        for n in range(400):
            sid = (n % 4) + 1
            read = 0 if n % 17 == 0 else 1
            conn.execute(
                """
                INSERT INTO posts (user_id, fb_post_id, source_id, body,
                                   post_type, posted_at, likes, comments,
                                   shares, engagement_read, captured_at,
                                   is_demo, item_type, image_text)
                VALUES (1, ?, ?, ?, 'text', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("fb-%d" % n, sid,
                 "x" * random.randint(50, 4000),
                 "2026-08-%02dT00:00:00" % ((n % 27) + 1),
                 0 if not read else random.randint(0, 900),
                 0 if not read else random.randint(0, 120),
                 0 if not read else random.randint(0, 40),
                 read,
                 "2026-08-%02dT00:00:00" % ((n % 27) + 1),
                 1 if n % 23 == 0 else 0,
                 "comment" if n % 9 == 0 else "post",
                 "y" * random.randint(0, 3000)))

    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = 1

        heavy = outliers.score_posts(appmod._fetch_posts())
        light = outliers.score_posts(appmod._scoring_rows())

    print("the two paths rank the same posts in the same order")
    check("same number scored", len(light), len(heavy))
    check("identical order", [r["id"] for r in light], [r["id"] for r in heavy])

    print()
    print("and every scored value matches, field by field")
    # These are the numbers the product asserts. A difference in any of them
    # is a difference in what the app claims about somebody's post.
    graded = ("outlier_multiple", "robust_z", "baseline", "has_baseline",
              "low_baseline", "tier", "bar_pct", "rank_basis",
              "weighted_engagement", "total_engagement", "engagement_known",
              "is_recent", "age_label", "age_hours")
    mismatches = {}
    by_id = {r["id"]: r for r in heavy}
    for row in light:
        other = by_id[row["id"]]
        for field in graded:
            if row[field] != other[field]:
                mismatches.setdefault(field, 0)
                mismatches[field] += 1
    for field in graded:
        check("%s identical across all %d posts" % (field, len(light)),
              mismatches.get(field, 0), 0)

    print()
    print("the light rows really are lighter")
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = 1
        full_rows = appmod._fetch_posts()
        light_rows = appmod._scoring_rows()

    def rough(rows):
        return sum(len(str(v)) for r in rows for v in r.values())

    full_size, light_size = rough(full_rows), rough(light_rows)
    check("light carries less", light_size < full_size, True)
    ratio = full_size / max(light_size, 1)
    print("       full %d chars vs light %d — %.1fx smaller"
          % (full_size, light_size, ratio))
    check("by a wide margin, not a rounding error", ratio > 3, True)
    check("and carries no captions",
          any("body" in r for r in light_rows), False)
    check("nor any image text",
          any("image_text" in r for r in light_rows), False)

    print()
    print("hydration puts the words back, and only on the page")
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = 1
        page = appmod._hydrate(light[:20])

    check("the page is the size asked for", len(page), 20)
    check("in the same order", [r["id"] for r in page], [r["id"] for r in light[:20]])
    check("captions are back", all(r.get("body") for r in page), True)
    check("so is the source name", all(r.get("source_name") for r in page), True)
    # The scored fields must survive the merge — they are what the ranking was.
    check("multiples survive hydration",
          [r["outlier_multiple"] for r in page],
          [r["outlier_multiple"] for r in light[:20]])
    check("so does the tier",
          [r["tier"] for r in page], [r["tier"] for r in light[:20]])

    print()
    print("hydration is scoped to the owner")
    auth.create_user("other@example.com", "a-long-enough-pass", "fernlake")
    with db.get_db() as conn:
        conn.execute("INSERT INTO posts (id, user_id, fb_post_id, source_id, "
                     "body, post_type, posted_at, engagement_read) VALUES "
                     "(99999, 2, 'fb-other', 1, 'someone elses words', 'text', "
                     "'2026-08-01T00:00:00', 1)")
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = 1
        stolen = appmod._hydrate([{"id": 99999, "outlier_multiple": None}])
    check("another account's post yields no words",
          stolen[0].get("body"), None)

    print()
    print("the feed itself still renders")
    client = appmod.app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 1
    response = client.get("/")
    html = response.data.decode("utf-8", "replace")
    check("200", response.status_code, 200)
    check("cards are on the page", html.count('class="post-card') > 0, True)
    check("with their captions", "post-body" in html, True)
    check("page two also works", client.get("/?page=2").status_code, 200)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("same answer, a fraction of the memory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
