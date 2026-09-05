"""What a brand-new account actually sees.

Signing up used to land on the install page: six manual steps ending in
Chrome's Developer mode, in front of a product the person had never seen
working. Fifteen accounts were created that way and not one of them ever
captured a post — the funnel did not have a persuasion problem, it had a
nothing-to-look-at problem.

So a new account is given the sample set and lands on the feed. These tests
care about the two halves of that being true at once:

  it works   — the feed ranks, the numbers are real, and Write can generate
               before anything has been installed
  it lies    — never. The rows are marked, the page says so in words, they
  about it     hide themselves the moment a real capture lands, and one
               account's samples are its own

The last two are the ones worth guarding. Sample data that outstays its
welcome, or that a second account can see, turns a demonstration into a bug
report about phantom posts.

Run: python tests/onboarding.test.py
"""
import logging
import os
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


def sign_up(client, email, username):
    """Register through the real form. Returns the response."""
    return client.post("/register", data={
        "email": email,
        "password": "a-long-enough-pass",
        "password_confirm": "a-long-enough-pass",
        "username": username,
    })


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import outliers
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    print("signing up lands on the product, not on an install manual")
    newbie = appmod.app.test_client()
    response = sign_up(newbie, "newbie@example.com", "birchwood")
    check("the account is made", response.status_code, 302)
    # The specific destination is the whole point of the change. /capture is
    # where people stopped.
    check("and goes to the feed", response.headers.get("Location"), "/")

    print()
    print("the feed is populated and ranked before anything is installed")
    page = newbie.get("/").get_data(as_text=True)
    check("it is not the empty state", "Nothing captured yet" in page, False)
    # Three per card, which is how the card template refers to its post.
    check("cards are rendered", page.count("data-post-id") > 0, True)

    # The set has to contain a breakout, or it demonstrates a breakout-finder
    # finding nothing. It did not for a long time: the multipliers were spread
    # evenly enough that the median landed at 3.55 and the best post managed
    # 4.3x against it, so this page opened with "0 breakout posts". Harmless
    # while sample data was an empty-install convenience, and not harmless at
    # all now that it is the first thing every new account sees.
    check("something scored as a breakout", "tier-breakout" in page, True)

    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = 1").fetchone()[0]
        marked = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = 1 AND is_demo = 1"
        ).fetchone()[0]
    check("posts were written", rows > 0, True)
    check("and EVERY one is marked as sample", marked, rows)

    print()
    print("the page says what it is, in words, unprompted")
    # A labelled row in the database is not a disclosure. The person reading
    # the feed has to be told before they mistake it for their own data.
    check("the banner is shown", "This is sample data" in page, True)
    check("  and points at the real next step",
          "Scan your first group" in page, True)

    print()
    print("the payoff page works immediately")
    # Write is the half of the product worth paying for, and on an empty
    # account it can only say "nothing captured has enough scored posts".
    # Reaching it needs sources past MIN_SAMPLE, which is what the sample set
    # is sized for.
    write = newbie.get("/write").get_data(as_text=True)
    check("Write is not empty-handed",
          "Nothing captured has enough" in write, False)
    check("  and offers the sample groups", "[DEMO]" in write, True)

    print()
    print("enough of it to actually score, not just to fill a page")
    with db.get_db() as conn:
        per_source = conn.execute(
            "SELECT source_id, COUNT(*) AS n FROM posts WHERE user_id = 1 "
            "GROUP BY source_id").fetchall()
    check("more than one group to compare",  len(per_source) > 1, True)
    check("every group clears the sample floor",
          all(r["n"] >= outliers.MIN_SAMPLE for r in per_source), True)

    print()
    print("a second account gets its OWN copy, not a view of the first's")
    # The sample sources share fb_ids across accounts by design, so this is
    # entirely down to upsert_source being keyed on (user_id, fb_id). If that
    # ever slipped, the second signup would silently adopt the first's rows.
    second = appmod.app.test_client()
    sign_up(second, "second@example.com", "fernlake")
    with db.get_db() as conn:
        owners = conn.execute(
            "SELECT user_id, COUNT(*) AS n FROM posts GROUP BY user_id"
        ).fetchall()
        sources = conn.execute(
            "SELECT user_id, COUNT(*) AS n FROM sources GROUP BY user_id"
        ).fetchall()
    check("two accounts hold posts", len(owners), 2)
    check("the same number each", owners[0]["n"], owners[1]["n"])
    check("and their own sources", len(sources), 2)
    check("  not shared", sources[0]["n"], sources[1]["n"])

    print()
    print("a real capture retires the samples on its own")
    # This is the safety property. Sample data that lingers next to real
    # captures is not a demonstration any more, it is noise the user has to
    # mentally filter — and eventually a support question about posts they
    # never scanned.
    with db.get_db() as conn:
        # A real group of their own, not a sample one — otherwise the sample
        # group's NAME is still on the page, on the real post's card, and this
        # test fails for a reason that has nothing to do with what it checks.
        cursor = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) "
            "VALUES (1, 'group:real', 'group', 'A Group They Actually Scanned')")
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
            "post_type, posted_at, likes, comments, shares, "
            "engagement_read, is_demo) "
            "VALUES (1, 'real-1', ?, 'A post somebody actually captured.', "
            "'text', '2026-09-01T00:00:00', 500, 40, 12, 1, 0)",
            (cursor.lastrowid,))

    after = newbie.get("/").get_data(as_text=True)
    check("the real post is on the feed",
          "A post somebody actually captured." in after, True)
    check("the sample banner is gone", "This is sample data" in after, False)
    check("and so are the sample cards",
          "Ecommerce Founders" in after, False)
    # Hidden, not deleted — they are still reachable behind the filter, and
    # Settings is still the thing that removes them.
    shown = newbie.get("/?samples=1").get_data(as_text=True)
    check("but they are hidden, not destroyed",
          "Ecommerce Founders" in shown, True)

    print()
    print("a failure to seed never costs somebody their account")
    # Sample data is a courtesy. If it throws, the person still signed up.
    import demo_data
    original = demo_data.seed_demo_data

    def explode(*args, **kwargs):
        raise RuntimeError("disk full, or any other bad day")

    appmod.seed_demo_data = explode
    try:
        third = appmod.app.test_client()
        response = sign_up(third, "third@example.com", "hollowbrook")
        check("registration still succeeds", response.status_code, 302)
        with db.get_db() as conn:
            exists = conn.execute(
                "SELECT COUNT(*) FROM users WHERE email = 'third@example.com'"
            ).fetchone()[0]
        check("and the account is real", exists, 1)
    finally:
        appmod.seed_demo_data = original

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("a new account sees the product working, and is told what it is")
    return 0


if __name__ == "__main__":
    sys.exit(main())
