"""What broke out since you were last here.

Comments and DMs were the only thing in this product anybody opened DAILY -
scoring is a weekly habit, replying was an hourly one - so removing them left
no reason to come back between scans. This is the replacement, and it says the
one thing nothing else can: these posts cleared the median of their own group,
and they arrived since you last looked.

Most of this file is about the watermark, because that is where a "since you
were last here" card goes wrong. Three ways, all tested:

  - It must not announce on a first visit. "Since you were last here" means
    nothing when there was no last time, and forty-seven posts named at
    somebody who just arrived is noise.
  - It must clear itself. If the card survives a reload it is not "since you
    were last here", it is a permanent banner.
  - It must not advance past a post it could not announce. A post captured
    before its group had a baseline is unscoreable, so unannounceable; moving
    the mark past it on sight would mean it becomes a breakout in silence.
    That one is the subtle bug, and it is the last test here.

Run: python tests/since.test.py
"""
import logging
import os
import re
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
    import sage
    import since
    import outliers
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    # ------------------------------------------------- the rules, in isolation
    print("what counts as news")

    def row(**kw):
        base = {"id": 1, "is_demo": 0, "item_type": "post", "has_baseline": True,
                "outlier_multiple": 4.0, "tier": "breakout",
                "captured_at": "2026-10-20 12:00:00"}
        base.update(kw)
        return base

    MARK = "2026-10-19 00:00:00"
    check("a breakout captured since the mark is news",
          since.whats_new([row()], MARK)["count"], 1)
    check("one captured before it is not",
          since.whats_new([row(captured_at="2026-10-18 00:00:00")], MARK)["count"], 0)
    check("a sample post is never news",
          since.whats_new([row(is_demo=1)], MARK)["count"], 0)
    check("an ordinary post is not news",
          since.whats_new([row(tier="normal")], MARK)["count"], 0)
    # The accuracy rule this app is built on: no multiple, no claim.
    check("a post with no usable baseline is not news",
          since.whats_new([row(has_baseline=False)], MARK)["count"], 0)
    check("  nor is one with no multiple, whatever its tier",
          since.whats_new([row(outlier_multiple=None)], MARK)["count"], 0)
    check("a comment row from an older version is not news",
          since.whats_new([row(item_type="comment")], MARK)["count"], 0)

    print()
    print("on a first visit it says nothing")
    check("no mark, no card", since.whats_new([row(), row()], None)["count"], 0)
    check("  and no watermark to store either",
          since.whats_new([row()], "")["watermark"], None)

    print()
    print("the best ones first, and only a few of them")
    many = [row(id=i, outlier_multiple=float(i)) for i in range(1, 9)]
    out = since.whats_new(many, MARK)
    check("every one is counted", out["count"], 8)
    check("  but only %d are named" % since.TOP_N, len(out["items"]), since.TOP_N)
    check("  biggest multiple first",
          [i["outlier_multiple"] for i in out["items"]], [8.0, 7.0, 6.0])

    print()
    print("one timestamp format, because this was silently dead without it")
    # The mark was written as "2026-10-20T18:00:00" by pipeline.now_utc() while
    # captured_at comes from SQLite as "2026-10-20 18:00:00". The space at
    # index ten sorts BEFORE the "T", so every post looked older than the mark,
    # nothing was ever new, and the card never appeared - with no error.
    check("a T-shaped mark still compares correctly",
          since.whats_new([row(captured_at="2026-10-20 18:05:00")],
                          "2026-10-20T18:00:00")["count"], 1)
    check("  and does not report a post from before it",
          since.whats_new([row(captured_at="2026-10-20 17:55:00")],
                          "2026-10-20T18:00:00")["count"], 0)
    check("the clock it writes is the one the rows use",
          " " in since.now_mark() and "T" not in since.now_mark(), True)

    print()
    print("the watermark is the newest one ANNOUNCED, never the clock")
    out = since.whats_new([row(id=1, captured_at="2026-10-20 09:00:00"),
                           row(id=2, captured_at="2026-10-20 15:00:00")], MARK)
    check("it is the newest of them", out["watermark"], "2026-10-20 15:00:00")
    # The subtle one. A post that cannot be announced must not move the mark,
    # or it becomes a breakout in silence once its group can be scored.
    out = since.whats_new([row(id=1, captured_at="2026-10-20 09:00:00"),
                           row(id=2, captured_at="2026-10-20 23:00:00",
                               has_baseline=False, outlier_multiple=None)], MARK)
    check("an unscoreable post does not drag it forward",
          out["watermark"], "2026-10-20 09:00:00")

    # ------------------------------------------------------- on the real feed
    print()
    print("on the feed")
    me = appmod.app.test_client()
    me.post("/register", data={"email": "me@example.com",
                               "password": "a-long-enough-pass",
                               "password_confirm": "a-long-enough-pass",
                               "username": "birchwood"})
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
    headers = {"X-Outlier-Key": key}

    first = me.get("/").get_data(as_text=True)
    check("a brand new account is told nothing",
          "broke out" in " ".join(first.split()), False)

    def capture(prefix, big):
        """A group with a readable baseline, plus one post that clears it."""
        posts = [{"fb_post_id": "%s-%d" % (prefix, i), "body": "Ordinary post %d" % i,
                  "likes": 20, "comments": 2, "shares": 1, "item_type": "post",
                  "author_name": "A", "engagement_read": 1,
                  "posted_at": "2026-10-10T10:00:00"} for i in range(outliers.MIN_SAMPLE + 2)]
        posts.append({"fb_post_id": "%s-big" % prefix,
                      "body": "The one that ran away with it", "likes": big,
                      "comments": 40, "shares": 30, "item_type": "post",
                      "author_name": "B", "engagement_read": 1,
                      "posted_at": "2026-10-19T10:00:00"})
        return me.post("/api/capture",
                       json={"source": {"fb_id": "g1", "kind": "group",
                                        "name": "Beekeepers", "url": "u"},
                             "posts": posts}, headers=headers)

    capture("a", 900)

    # The mark is rewound a minute first, so this asserts the feature and not
    # the clock. Without it the capture lands in the same second as the first
    # page view above, and captured_at has one-second resolution - see since.py
    # on why the comparison is strictly greater-than.
    with db.get_db() as conn:
        conn.execute("UPDATE user_settings SET value = datetime('now', '-1 minute') "
                     "WHERE user_id = 1 AND key = ?", (since.MARK,))
    page = me.get("/").get_data(as_text=True)
    # Matched on collapsed whitespace: the heading is built from two template
    # lines, so the words are there with a newline between them.
    flat = " ".join(page.split())
    check("after a scan, the card names it", "broke out" in flat, True)
    check("  and says how long it has been", "broke out since" in flat, True)
    check("  with the post in it", "ran away with it" in page, True)
    check("  and a multiple, not a vague claim",
          bool(re.search(r'class="wn-mult">[0-9.]+×', page)), True)

    again = " ".join(me.get("/").get_data(as_text=True).split())
    check("it clears itself on the next look", "broke out" in again, False)

    # Nothing new must leave the mark alone, so a post captured while its
    # group was unscoreable is still waiting when the group can be scored.
    def stored_mark():
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id = 1 AND key = ?",
                (since.MARK,)).fetchone()
        return row["value"] if row else None

    before = stored_mark()
    me.get("/")
    check("a quiet visit leaves the mark alone", stored_mark(), before)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the daily reason to look, and it tells the truth about when")
    return 0


if __name__ == "__main__":
    sys.exit(main())
