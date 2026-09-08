"""Ranking posts you went looking for.

This scores the OPPOSITE way to everything else in the product, and the tests
exist mostly to stop somebody helpfully making it consistent:

  - fewer comments is BETTER, not worse
  - a one-like post can be the best result on the page
  - nothing is scored against a median, and nothing here may touch one

The last of those is the one that would do real damage. A search result was
selected because it contains a keyword, so it is a biased sample of its group
by construction. Filed into `posts` it would drag every baseline it touched,
silently, and surface months later looking like a scoring bug.

Run: python tests/opportunities.test.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def ago(hours):
    return (datetime.now(timezone.utc)
            - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def main():
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
    import opportunities as opp

    def rank(body, comments=0, hours=2):
        return opp.score({"body": body, "comments": comments,
                          "posted_at": ago(hours) if hours is not None else None})[0]

    print("the shape of asking beats the shape of talking")

    asked = rank("Anyone know a good web designer? Ours is embarrassing.", 2, 3)
    chatter = rank("I love our new website, the team did great.", 8, 2)
    viral = rank("Websites are dead, everything is social now.", 420, 1)

    check("an outright request scores high", asked >= 85, True)
    check("praise for a website is not an opportunity", chatter < 25, True)
    check("nor is a hot take about websites", viral < 25, True)

    # Intent multiplies rather than adds, and this is why. Adding gave chatter
    # 60.0 and the hot take 53.2 — both "worth a look" — because freshness and
    # an empty thread paid out in full while intent scored almost nothing. Half
    # the list would have been things nobody wanted anything in.
    check("a fresh empty-thread post with no intent still ranks low",
          rank("I love our new website, the team did great.", 0, 1) < 25, True)

    print()
    print("fewer replies is better, which is backwards from everywhere else")

    quiet = rank("Can anyone recommend someone to build a site?", 0, 2)
    busy = rank("Can anyone recommend someone to build a site?", 60, 2)
    check("the same ask beats itself when nobody has answered", quiet > busy, True)
    check("  and a scrum is still worth something, just less",
          0 < busy < quiet, True)

    print()
    print("recency decides whether answering is worth doing at all")

    now = rank("Looking to hire someone to build a website.", 0, 2)
    days = rank("Looking to hire someone to build a website.", 0, 96)
    check("this morning beats four days ago", now > days, True)
    check("past the window it is closed, not weak",
          rank("Looking to hire someone to build a website.", 0, 24 * 15), 0.0)
    check("  however perfect the request",
          opp.score({"body": "Can anyone recommend a web designer? Budget ready.",
                     "comments": 0, "posted_at": ago(24 * 20)})[0], 0.0)

    # Unknown is not new. Undated posts floating to the top of the list would
    # be the first thing anybody noticed and the last thing they could explain.
    undated = rank("Looking for a web developer, any recommendations?", 1, None)
    check("an undated post does not outrank a known-fresh one",
          undated < rank("Looking for a web developer, any recommendations?", 1, 2),
          True)
    check("  but is not thrown away either", undated > 0, True)

    print()
    print("the scorer knows nothing about any particular trade")

    # The industry comes from the search the person ran, never from here.
    # Baking "website" into the patterns would make this work for one trade
    # and quietly fail for every other.
    plumber = rank("Can anyone recommend a plumber? Ours retired.", 0, 1)
    check("a plumbing request scores like any other request",
          plumber >= 85, True)

    print()
    print("every result says why it ranked")

    _score, label = opp.score({"body": "Anyone know a good designer?",
                               "comments": 1, "posted_at": ago(1)})
    check("an outright ask is labelled as one", label, "asking outright")
    check("money talk is labelled as money talk",
          opp.score({"body": "What's a fair budget for this?", "comments": 0,
                     "posted_at": ago(1)})[1], "ready to pay")
    check("and a bare mention says so",
          opp.score({"body": "Our website is blue.", "comments": 0,
                     "posted_at": ago(1)})[1], "mentions it")

    print()
    print("nothing here goes anywhere near a post baseline")

    import db
    db.init_db()
    with db.get_db() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
        check("opportunities is its own table", "fb_post_id" in cols, True)
        check("  and carries the search that found it", "query" in cols, True)
        check("  and a status, which posts do not have", "status" in cols, True)
        # The one that matters. An opportunity has no source_id, so it cannot
        # be joined into a group's median even by accident.
        check("  and NO source_id to be filed under", "source_id" in cols, False)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("opportunities rank the other way round, on purpose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
