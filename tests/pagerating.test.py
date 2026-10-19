"""A busy page must never be called dead.

Reported from real use: a Page with thousands of reactions and thousands of
shares on its posts was labelled Dead and listed as worth leaving.

The mechanism, found in the capture path rather than the rating path. The
extension marked a post as "engagement read" when it had read ANY number off
it — including a video play count:

    engagementRead = likes || comments || shares || video_plays

But plays count toward nothing. Weighted engagement is reactions + comments×3
+ shares×5, and video_plays appears in neither it nor total_engagement. So a
video post whose reaction bar had not rendered yet, but whose "52K plays" line
had, was recorded as measured with an engagement of zero.

A video-first page is mostly those posts. They dragged the median to zero,
which is exactly the failure outliers.engagement_known exists to prevent — and
because they counted as READ, the "only 40% of this could be read, so no
verdict" guard never fired. The page scored below the floor and was called
dead, with a why-line insisting it was "not a reading failure".

Two fixes, tested here. A plays-only row is no longer measured, which repairs
every page already captured. And no source whose best post cleared ALIVE_PEAK
is ever called dead, whatever the median says — a contradiction that large is
evidence of a reading failure, not of a dead room. The second is the one that
would have caught this without knowing the cause, so it also catches the next
extraction bug nobody has found yet.

Run: python tests/pagerating.test.py
"""
import os
import re
import sys
import shutil
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


def iso(hours):
    return (datetime.now(timezone.utc) -
            timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    import app
    import rating
    import outliers

    c = app.app.test_client()
    tok = re.search(r'name="csrf_token" value="([^"]+)"',
                    c.get("/register").get_data(as_text=True)).group(1)
    c.post("/register", data={"email": "page@example.com",
                              "password": "hunter2hunter2",
                              "password_confirm": "hunter2hunter2",
                              "csrf_token": tok}, follow_redirects=True)
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"',
                     c.get("/account").get_data(as_text=True)).group(1)
    key = c.post("/api/account/connect",
                 headers={"X-CSRF-Token": tok2}).get_json()["api_key"]

    def send(fb_id, name, posts, kind="page"):
        return c.post("/api/capture",
                      json={"source": {"fb_id": fb_id, "kind": kind,
                                       "name": name, "url": "u"},
                            "posts": posts},
                      headers={"X-Outlier-Key": key})

    # ------------------------------------------------- the reported shape
    #
    # A big video-first page, captured the way the extension really captures
    # one: most posts are reels whose play count read and whose reaction bar
    # did not, a handful read completely and they are enormous.
    reels = [{"fb_post_id": "v%d" % i, "body": "Reel %d" % i,
              "likes": 0, "comments": 0, "shares": 0,
              "video_plays": 52000 + i * 900, "has_video": 1,
              "item_type": "post", "author_name": "Alex",
              "posted_at": iso(6 + i * 20),
              # What the extension sent: a number WAS read off this post.
              "engagement_read": 1} for i in range(14)]
    whole = [{"fb_post_id": "p%d" % i, "body": "Post %d" % i,
              "likes": 2400 + i * 300, "comments": 180, "shares": 220,
              "item_type": "post", "author_name": "Alex",
              "posted_at": iso(10 + i * 26),
              "engagement_read": 1} for i in range(6)]
    send("page:hormozi", "Alex Hormozi", reels + whole)

    # The verdict for that source, built from the stored rows through the same
    # two functions the groups page uses.
    import db
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id FROM sources WHERE fb_id = 'page:hormozi'").fetchone()
        source = {"is_demo": 0, "kind": "page"}
    rows = [r for r in app._scoring_rows(user_id=row["user_id"])
            if r["source_id"] == row["id"]]
    stats = outliers.source_stats(rows)
    newest = max((r["posted_at"] or "" for r in rows), default="") or None
    verdict = rating.of(source, stats, newest)

    print("the page that was called dead")
    check("captured as expected", len(rows), 20)
    check("it is not called dead", verdict["band"] == "dead", False)
    check("  and is not offered for leaving", verdict["leave"], False)
    check("  the reels are not counted as measured posts",
          stats["measured_count"], 6)
    check("  so the median describes the posts that were read",
          stats["raw_baseline"] > 1000, True)
    # Six measured posts is below MIN_SAMPLE, so there is still no verdict —
    # and that is the honest answer. "20 captured, 6 measured" tells the
    # operator what to do about it; "Dead" told them to leave.
    check("  and the verdict says how little was measured, not that it is dead",
          verdict["band"], "new")
    check("  naming both numbers",
          "20 posts captured, 6 measured" in " ".join(verdict["why"]), True)
    check("  and the unread reels are reported as unread",
          stats["unread_count"], 14)

    # The groups page itself, where the suggestion was shown.
    page = c.get("/groups").get_data(as_text=True)
    check("the leave list does not name it",
          re.search(r'class="leave-list".{0,6000}Alex Hormozi', page, re.S)
          is not None, False)

    # ------------------------------------------- the arithmetic underneath
    print()
    print("a play count is not engagement")
    plays_only = {"likes": 0, "comments": 0, "shares": 0,
                  "video_plays": 52000, "engagement_read": 1}
    check("a plays-only row is not counted as measured",
          outliers.engagement_known(plays_only), False)
    check("  because plays count toward nothing",
          outliers.weighted_engagement(plays_only), 0)

    # A post that really got nothing still counts. Without this the feature
    # cannot work at all: a dead group is made of exactly these rows, and
    # dropping them would leave nothing to take a median of.
    read_zeros = {"likes": 0, "comments": 0, "shares": 0,
                  "video_plays": 0, "engagement_read": 1}
    check("a post read as genuinely zero is still measured",
          outliers.engagement_known(read_zeros), True)

    # One real count is enough, even alongside plays.
    some = {"likes": 0, "comments": 3, "shares": 0,
            "video_plays": 52000, "engagement_read": 1}
    check("plays alongside a real count are no obstacle",
          outliers.engagement_known(some), True)

    # Legacy rows predate the flag and are judged on their numbers alone.
    check("a legacy row with plays only is not measured",
          outliers.engagement_known({"likes": 0, "comments": 0, "shares": 0,
                                     "video_plays": 9000,
                                     "engagement_read": None}), False)

    # ------------------------------------------------------- the safety veto
    print()
    print("a contradiction that large is a reading failure, not a dead room")
    # Built directly, so this holds even if the capture path breaks in some
    # new way nobody has thought of: a median under the floor, and one post
    # that plainly did thousands.
    stats = {"post_count": 20, "measured_count": 20, "measured_pct": 100,
             "baseline": 2.0, "has_baseline": True, "outlier_count": 0,
             "top_multiple": None, "top_engagement": 4300.0}
    verdict = rating.of({"is_demo": 0, "kind": "page"}, stats, iso(5))
    check("not dead", verdict["band"] == "dead", False)
    check("  and never suggested for leaving", verdict["leave"], False)
    check("  it says it cannot tell", verdict["band"], "unclear")
    check("  and names the post that contradicts the median",
          any("4300" in w or "4,300" in w for w in verdict["why"]), True)

    # The same veto must not rescue a room that really is finished.
    dead = {"post_count": 20, "measured_count": 20, "measured_pct": 100,
            "baseline": 2.0, "has_baseline": True, "outlier_count": 0,
            "top_multiple": None, "top_engagement": 9.0}
    verdict = rating.of({"is_demo": 0, "kind": "group"}, dead, iso(5))
    check("a genuinely dead group is still dead", verdict["band"], "dead")
    check("  and still offered for leaving", verdict["leave"], True)

    # Staleness, too. A page nobody has posted to in months, whose best post
    # did thousands, is a page we captured a slice of — not a dead one.
    stale = {"post_count": 20, "measured_count": 20, "measured_pct": 100,
             "baseline": 60.0, "has_baseline": True, "outlier_count": 1,
             "top_multiple": 3.1, "top_engagement": 5200.0}
    verdict = rating.of({"is_demo": 0, "kind": "page"}, stale, iso(24 * 90))
    check("stale but huge is not dead", verdict["band"] == "dead", False)
    check("  and not offered for leaving", verdict["leave"], False)

    stale_small = {"post_count": 20, "measured_count": 20, "measured_pct": 100,
                   "baseline": 11.0, "has_baseline": True, "outlier_count": 0,
                   "top_multiple": 1.4, "top_engagement": 40.0}
    verdict = rating.of({"is_demo": 0, "kind": "group"}, stale_small, iso(24 * 90))
    check("a small stale group is still dead", verdict["band"], "dead")

    # ------------------------------------------------- a room really being dead
    #
    # Until now this shape came out as "Not enough yet": the engagement test
    # needed a baseline, and a baseline is only issued when the median clears
    # the floor the test was looking under. So the rooms this feature exists to
    # find were never named.
    print()
    print("a room that really is finished")
    finished = {"post_count": 20, "measured_count": 20, "measured_pct": 100,
                "baseline": None, "raw_baseline": 2.0, "has_baseline": False,
                "blocker": "low-baseline", "outlier_count": 0,
                "top_multiple": None, "top_engagement": 41.0}
    verdict = rating.of({"is_demo": 0, "kind": "group"}, finished, iso(10))
    check("read in full and nothing moved: dead", verdict["band"], "dead")
    check("  and worth leaving", verdict["leave"], True)
    check("  the best post is named, not just the median",
          any("41" in w for w in verdict["why"]), True)

    # The same shape with one big post in it is the reported bug again.
    busy = dict(finished, top_engagement=1240.0)
    verdict = rating.of({"is_demo": 0, "kind": "page"}, busy, iso(10))
    check("one big post and it is not dead", verdict["band"], "unclear")
    check("  nor worth leaving", verdict["leave"], False)

    # And a room that simply could not be read is still not judged.
    unread = dict(finished, measured_count=4, measured_pct=20,
                  blocker="unreadable")
    verdict = rating.of({"is_demo": 0, "kind": "group"}, unread, iso(10))
    check("unreadable is still not dead", verdict["band"] == "dead", False)
    check("  and still never worth leaving", verdict["leave"], False)

    # ------------------------------------------------- the floor is published
    print()
    check("the alive-peak floor is a named constant",
          isinstance(rating.ALIVE_PEAK, int), True)
    check("  and it is around a hundred, as reported",
          50 <= rating.ALIVE_PEAK <= 200, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("busy pages are not called dead")
    return 0


if __name__ == "__main__":
    sys.exit(main())
