"""What the dragonfly is allowed to say.

It is a friendly thing in the corner of every page, which makes it the easiest
place in the app to start lying — a cheerful hint about "your best post" to
somebody who has captured nothing, or a number that came from nowhere. Same rule
as hooks.py and patterns.py: a claim about their data only when the data is
there.

  where they are  somebody with nothing captured is told how to capture, not
                  how to pick between winners
  real numbers    a multiple is only mentioned when the meadow has one, and it
                  is the one the meadow is drawn from
  the page        a tip about the page they are on comes before general advice
  cheap           this runs on every page load, so the facts it uses are ones
                  the page already had
  no repeats      the same sentence never appears twice in one list

Run: python tests/tips.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import outliers  # noqa: E402
import tips      # noqa: E402

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


SOMEBODY = {"id": 1}


def words(tips):
    """Just the sentences, for the assertions that are about wording."""
    return [t["text"] for t in tips]


def main():
    print("nobody signed in")
    out = words(tips.for_page("feed", [], None))
    check("there is still something to say", len(out) > 1, True)
    check("  and none of it claims to know them",
          any("your" in t.lower() for t in out), False)

    print()
    print("signed in, nothing captured")
    out = words(tips.for_page("feed", [], SOMEBODY, {"posts": 0}))
    check("the first thing said is how to capture",
          "press Start" in out[0], True)
    check("  not how to choose between winners",
          any("28×" in t for t in out[:1]), False)
    check("  and no multiple is invented",
          any("× the median of its group" in t for t in out), False)

    print()
    print("captured, but nothing scoreable yet")
    out = words(tips.for_page("groups", [], SOMEBODY, {"posts": 40}))
    check("it explains what a baseline needs", str(outliers.MIN_SAMPLE) in out[0], True)
    check("  and still no multiple", any("its group" in t for t in out[:1]), False)

    print()
    print("scores exist, so it may talk about them")
    out = words(tips.for_page("feed", [2.1, 14.63, 3.4], SOMEBODY, {"posts": 300}))
    check("it leads with their own best", "14.6×" in out[0], True)
    check("  rounded, not raw", "14.63" in out[0], False)

    # A meadow of ordinary posts is not a brag.
    out = words(tips.for_page("feed", [1.1, 0.9, 1.0], SOMEBODY, {"posts": 300}))
    check("a best of 1.1× is not announced as a win",
          any("did 1.1×" in t for t in out), False)
    check("  but there is still advice", len(out) > 2, True)

    print()
    print("people waiting on a reply come before craft")
    out = words(tips.for_page("feed", [9.0, 2.0], SOMEBODY, {"posts": 300, "waiting": 3}))
    check("it mentions them", any("3 people are waiting" in t for t in out), True)
    check("  before the general advice",
          [i for i, t in enumerate(out) if "waiting" in t][0] <
          [i for i, t in enumerate(out) if "plausibly" in t][0], True)
    one = words(tips.for_page("feed", [9.0], SOMEBODY, {"posts": 300, "waiting": 1}))
    check("and one person is singular", any("1 person is waiting" in t for t in one), True)

    print()
    print("the page they are on gets a word in")
    for page, must in (("groups", "Needs more data"), ("today", "ever sent for you"),
                       ("write", "opening line"), ("results", "same medians")):
        out = words(tips.for_page(page, [9.0], SOMEBODY, {"posts": 300}))
        check("  %s" % page, any(must in t for t in out), True)
    out = words(tips.for_page("nowhere-in-particular", [9.0], SOMEBODY, {"posts": 300}))
    check("an unknown page still gets craft advice", len(out) > 2, True)

    print()
    print("the list itself")
    out = words(tips.for_page("feed", [9.0, 2.0], SOMEBODY, {"posts": 300, "waiting": 2}))
    check("nothing repeats", len(out), len(set(out)))
    check("it is capped", len(out) <= 8, True)
    # A count may legitimately open a line ("3 people are waiting on a reply").
    check("every line is a real sentence",
          all(len(t) > 20 and (t[0].isupper() or t[0].isdigit()) and t.endswith(".")
              for t in out), True)
    check("nothing arrives with broken whitespace",
          all("  " not in t and "\\n" not in t for t in out), True)

    print()
    print("missing counts are not guessed at")
    # The page failed to get a count; that must not read as "zero posts".
    out = words(tips.for_page("feed", [9.0, 2.0], SOMEBODY, {}))
    check("no 'nothing captured' claim without knowing",
          any("press Start" in t for t in out), False)
    check("  and the score it can see is still used", "9.0×" in out[0], True)

    print()
    print("the deep tips: the same picture Sage reasons over")
    # These read every post the account holds, so they are fetched on a tap and
    # never on a page load. What matters is that they only name what is real.
    import logging, os, shutil, tempfile
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    import db, auth
    import app as appmod
    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("deep@example.com", "a-long-enough-pass", "deepone")
    uid = user["id"]

    def group(name, rows, demo=0):
        """rows: (likes, engagement_read) per post."""
        with db.get_db() as conn:
            sid = conn.execute(
                "INSERT INTO sources (user_id, fb_id, kind, name) VALUES (?, ?, 'group', ?)",
                (uid, "fb:" + name, name)).lastrowid
            aid = conn.execute("SELECT id FROM authors WHERE name = 'Someone'").fetchone()
            aid = aid[0] if aid else conn.execute(
                "INSERT INTO authors (name) VALUES ('Someone')").lastrowid
            for i, (likes, read) in enumerate(rows):
                # A post whose engagement could not be read has NO counts at
                # all. Leaving comments and shares on one made it read as
                # measured, which is what "engagement_recorded_pct" counts.
                conn.execute(
                    "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, "
                    "likes, comments, shares, posted_at, is_demo, item_type, engagement_read) "
                    "VALUES (?, ?, ?, ?, 'a post about bees and honey', ?, ?, ?, "
                    "datetime('now','-2 days'), ?, 'post', ?)",
                    (uid, "%s-%d" % (name, i), sid, aid, likes,
                     2 if read else 0, 1 if read else 0, demo, read))

    # A strong room, a room too thin to score, and a barely-readable room.
    group("Bakers", [(10, 1)] * 9 + [(150, 1)])
    group("Tiny Room", [(8, 1), (9, 1)])
    group("Murky", [(12, 1)] * 9 + [(0, 0)] * 14)

    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        found = words(tips.deep(user, "feed", {"groups": "/groups", "write": "/write"}))

    check("it has something to say", len(found) > 1, True)
    check("it names the strongest room and what typical means there",
          any("Bakers" in t and "typical post there scores" in t for t in found), True)
    check("it explains the room that cannot be scored",
          any("Tiny Room" in t and "cannot be scored" in t for t in found), True)
    check("  naming what it needs", any(str(outliers.MIN_SAMPLE) in t for t in found), True)
    check("it flags a room too little of which could be read",
          any("Murky" in t and "could be read" in t for t in found), True)
    check("nothing mentions a group that has no baseline as if it did",
          any("Tiny Room" in t and "typical post there scores" in t for t in found), False)

    print()
    print("and it says nothing rather than guessing")
    empty, _ = auth.create_user("empty@example.com", "a-long-enough-pass", "emptyone")
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = empty["id"]
        check("an account with nothing gets no deep tips", tips.deep(empty, "feed"), [])

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("every tip carries somewhere to go, or nothing")
    shaped = tips.for_page("feed", [9.0, 2.0], SOMEBODY, {"posts": 300})
    check("each one is words plus a destination",
          all(set(t) == {"text", "where"} for t in shaped), True)
    check("  and a missing destination is None, not a broken link",
          all(t["where"] is None or t["where"].startswith("/") for t in shaped), True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("it only says what is true of the person reading it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
