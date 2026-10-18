"""Judging a room, and knowing when not to.

"Leave this group" is the strongest thing this app says to anybody, so the tests
are mostly about when it refuses to say it.

The mistake that matters: a group where extraction failed looks exactly like a
dead group — a median near zero either way. Telling somebody to leave a busy
room because Tallgrass could not read it would be worse than saying nothing at
all, and it would be indistinguishable from the app being right.

  unreadable   below the readable floor there is NO verdict, only "can't tell"
  too thin     without enough measured posts there is no verdict either
  stale        nothing posted in a long time is dead, even if it once scored
  dead         a real, readable room with almost no engagement is dead
  samples      sample data is never rated and never offered for leaving
  evidence     every verdict carries the numbers it was made from
  no leaving   nothing here leaves a group; it reports and links

Run: python tests/rating.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import outliers  # noqa: E402
import rating    # noqa: E402

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def stats(posts=40, measured=None, readable=100, baseline=30.0,
          has_baseline=True, outliers_found=4, top=6.0):
    measured = posts if measured is None else measured
    return {
        "post_count": posts,
        "measured_count": measured,
        "measured_pct": readable,
        "baseline": baseline,
        "has_baseline": has_baseline,
        "outlier_count": outliers_found,
        "top_multiple": top,
    }


def main():
    GROUP = {"name": "A Room", "is_demo": False}
    recent = "2026-10-17 10:00:00"      # the day before "now" below
    NOW = None                          # real clock; the fixtures are recent

    print("a busy, readable room")
    v = rating.of(GROUP, stats(baseline=52.0), recent)
    check("is thriving", v["band"], "thriving")
    check("  and says what a typical post scores", "52" in v["why"][0], True)
    check("  carrying its numbers", v["numbers"]["baseline"], 52.0)
    check("  and is never offered for leaving", v["leave"], False)

    print()
    print("the bands in between")
    check("20 is steady", rating.of(GROUP, stats(baseline=20.0), recent)["band"], "steady")
    check("10 is quiet", rating.of(GROUP, stats(baseline=10.0), recent)["band"], "quiet")
    check("  and quiet is not offered for leaving",
          rating.of(GROUP, stats(baseline=10.0), recent)["leave"], False)

    print()
    print("a real, readable room with nothing happening in it")
    dead = rating.of(GROUP, stats(baseline=3.0, outliers_found=0), recent)
    check("is dead", dead["band"], "dead")
    check("  offered for leaving", dead["leave"], True)
    check("  and it says the number, not just the word",
          "3" in dead["why"][0] and str(outliers.MIN_BASELINE) in dead["why"][0], True)
    check("  and that it was readable, so this is the room not a failure",
          any("readable" in w for w in dead["why"]), True)

    print()
    print("THE MISTAKE THAT MATTERS: unreadable is not dead")
    blind = rating.of(GROUP, stats(baseline=2.0, readable=30, measured=12), recent)
    check("no verdict is issued", blind["band"], "unclear")
    check("  it is NOT called dead", blind["band"] == "dead", False)
    check("  it is NOT offered for leaving", blind["leave"], False)
    check("  and it says to scan it again",
          any("Scan it again" in w for w in blind["why"]), True)
    check("the floor is a real one", rating.NEEDS_READABLE_PCT > 50, True)

    print()
    print("and neither is 'too thin to score'")
    thin = rating.of(GROUP, stats(posts=5, measured=5, baseline=None,
                                  has_baseline=False), recent)
    check("no verdict", thin["band"], "new")
    check("  not offered for leaving", thin["leave"], False)
    check("  and it names what it needs",
          str(outliers.MIN_SAMPLE) in thin["why"][0], True)

    nothing = rating.of(GROUP, None, None)
    check("a source with no stats at all is not judged", nothing["band"], "new")
    check("  and not offered for leaving", nothing["leave"], False)

    print()
    print("a room nobody has posted in")
    old = "2026-01-01 09:00:00"          # far beyond the stale window
    stale = rating.of(GROUP, stats(baseline=45.0), old)
    check("is dead however well it once scored", stale["band"], "dead")
    check("  offered for leaving", stale["leave"], True)
    check("  saying how long it has been quiet",
          any("days" in w for w in stale["why"]), True)
    check("  and what it used to score",
          any("when it was active" in w for w in stale["why"]), True)
    check("the window is measured in weeks, not days", rating.STALE_DAYS >= 30, True)

    print()
    print("sample data is not a group you can leave")
    sample = rating.of({"name": "Samples", "is_demo": True},
                       stats(baseline=1.0, outliers_found=0), recent)
    check("it gets no verdict", sample["band"], "new")
    check("  and is never offered for leaving", sample["leave"], False)
    check("  and says what it is", "Sample data" in sample["why"][0], True)

    print()
    print("the list of what might be worth leaving")
    verdicts = [
        rating.of(GROUP, stats(baseline=52.0), recent),
        rating.of(GROUP, stats(baseline=3.0), recent),
        rating.of(GROUP, stats(baseline=12.0), recent),
        rating.of(GROUP, stats(baseline=2.0, readable=20, measured=9), recent),
        rating.of(GROUP, stats(posts=3, has_baseline=False), recent),
    ]
    ranked = rating.rank(verdicts)
    check("only rooms with a verdict are ranked", len(ranked), 3)
    check("  worst first", [v["band"] for v in ranked], ["dead", "quiet", "thriving"])
    check("  and the unsure ones are not quietly sorted in as bad",
          any(v["band"] in ("unclear", "new") for v in ranked), False)
    counts = rating.tally(verdicts)
    check("the tally counts every band", counts.get("unclear"), 1)
    check("  including the ones without a verdict", counts.get("new"), 1)

    print()
    print("the groups page shows it, against real rows")
    import logging, shutil, tempfile
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    import db, auth
    import app as appmod
    logging.disable(logging.INFO)
    db.init_db()
    boss, _ = auth.create_user("rate@example.com", "a-long-enough-pass", "rater")
    uid = boss["id"]

    def room(name, rows, when="-2 days"):
        """rows: (likes, readable) per post."""
        with db.get_db() as conn:
            sid = conn.execute(
                "INSERT INTO sources (user_id, fb_id, kind, name, url, last_capture) "
                "VALUES (?, ?, 'group', ?, ?, datetime('now'))",
                (uid, "fb:" + name, name,
                 "https://www.facebook.com/groups/" + name.lower().replace(" ", "-"))
            ).lastrowid
            for i, (likes, readable) in enumerate(rows):
                conn.execute(
                    "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, "
                    "comments, shares, posted_at, is_demo, item_type, engagement_read) "
                    "VALUES (?, ?, ?, 'words about bees', ?, ?, ?, datetime('now', ?), "
                    "0, 'post', ?)",
                    (uid, "%s-%d" % (name, i), sid, likes,
                     3 if readable else 0, 1 if readable else 0, when, readable))
        return sid

    room("Busy Room", [(40, 1)] * 9 + [(300, 1)])
    room("Ghost Town", [(1, 1)] * 10)
    room("Murky Room", [(2, 1)] * 9 + [(0, 0)] * 20)
    room("Old Room", [(60, 1)] * 10, when="-200 days")

    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/groups").get_data(as_text=True)

    check("the page renders", "Groups, profiles" in html, True)
    check("the busy room is rated", "Thriving" in html or "Steady" in html, True)
    check("the dead one is flagged", "Dead" in html, True)
    check("  and offered for leaving", "Worth leaving?" in html, True)
    check("  with a door to it",
          "facebook.com/groups/ghost-town" in html, True)
    check("the unreadable one says so", "Can&#39;t tell yet" in html or
          "Can't tell yet" in html, True)
    check("  and is NOT in the leaving list",
          html.index("Worth leaving?") < html.index("Murky Room")
          and "Murky Room" not in html.split("Worth leaving?")[1].split("</section>")[0],
          True)
    check("the stale room is in the leaving list",
          "Old Room" in html.split("Worth leaving?")[1].split("</section>")[0], True)
    check("and the page never offers to leave for you",
          "leave this group for you" in html.lower(), False)
    check("  it says so plainly",
          "never leaves a group for you" in html, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("nothing here leaves a group")
    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "rating.py"), encoding="utf-8").read()
    for forbidden in ("requests.post", "urlopen", "fetch(", "leave_group"):
        check("  no %s" % forbidden, forbidden in source, False)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("it judges a room only when the room can be read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
