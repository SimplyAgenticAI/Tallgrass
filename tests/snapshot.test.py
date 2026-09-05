"""Real captures, frozen into the sample set new accounts are given.

The written sample set's engagement numbers are invented — at one point tuned
by hand until the distribution produced a breakout, because the original did
not contain one. That makes the Write page's promise ("the number is what that
post actually did") false on demo data. A snapshot of real captures makes it
true again.

The round trip is what these tests care about: export what was captured, seed
it into a different account, and get back posts that score the same and read
as current. Plus the three properties that are easy to lose:

  ages nothing   times are offsets from export, reconstructed against signup,
                 or a snapshot reads as eight months stale by spring
  one copy       pictures are shared, not written into every account's cache
  still scoped   a shared picture is still only served to the account whose
                 post it is

Run: python tests/snapshot.test.py
"""
import io
import json
import logging
import os
import shutil
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


def a_photo():
    from PIL import Image
    image = Image.new("RGB", (200, 150), (60, 120, 90))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    return buffer.getvalue()


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    os.environ["ADMIN_EMAILS"] = "boss@example.com"

    import db
    import auth
    import images
    import outliers
    import demo_snapshot
    import demo_data
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    boss, _ = auth.create_user("boss@example.com", "a-long-enough-pass", "birchwood")

    print("the operator captures a page, the way anybody would")
    now = datetime.now(timezone.utc)
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO sources (id, user_id, fb_id, kind, name, url, "
            "member_count) VALUES (1, ?, 'page:real', 'page', "
            "'A Real Public Page', 'https://facebook.com/realpage', 12000)",
            (boss["id"],))
        author = db.upsert_author(conn, name="The Page Itself")
        # A believable spread: mostly ordinary, one clear breakout. The exact
        # numbers matter because the whole point is that they survive the trip.
        counts = [900, 55, 38, 61, 44, 50, 47, 58, 42, 40]
        for index, likes in enumerate(counts):
            posted = now - timedelta(days=index + 1, hours=3)
            db.upsert_post(conn, 1, author, {
                "fb_post_id": "real-%d" % index,
                "body": "A real post, number %d, with real words in it." % index,
                "post_type": "photo" if index == 0 else "text",
                "posted_at": posted.strftime("%Y-%m-%dT%H:%M:%S"),
                "likes": likes, "comments": likes // 8, "shares": likes // 20,
                "engagement_read": 1,
                "permalink": "https://facebook.com/realpage/posts/%d" % index,
            }, user_id=boss["id"])

    # The breakout has a picture, already downscaled into the cache the way a
    # real one would be by the time anybody exported it.
    with db.get_db() as conn:
        breakout_id = conn.execute(
            "SELECT id FROM posts WHERE fb_post_id = 'real-0'").fetchone()["id"]
    images.store(breakout_id, a_photo())
    check("its picture is cached", bool(images.cached(breakout_id)), True)

    print()
    print("exporting freezes it, pictures and all")
    snapshot = demo_snapshot.build([1], boss["id"], note="one public page")
    check("one source", len(snapshot["sources"]), 1)
    check("every post came along", len(snapshot["sources"][0]["posts"]), 10)
    check("the picture rode along",
          sum(1 for p in snapshot["sources"][0]["posts"] if p.get("image")), 1)
    check("and the real engagement did too",
          sorted(p["likes"] for p in snapshot["sources"][0]["posts"]),
          sorted(counts))

    print()
    print("times are offsets, not dates")
    # A snapshot of absolute timestamps reads as eight months stale by spring.
    # This is the property that keeps a frozen demo looking current.
    ages = [p["hours_ago"] for p in snapshot["sources"][0]["posts"]]
    check("every post carries an age", all(a is not None for a in ages), True)
    check("and no post carries a date",
          any("posted_at" in p for p in snapshot["sources"][0]["posts"]), False)

    print()
    print("a snapshot on disk replaces the written set")
    path = os.path.join(tmp, "committed_snapshot.json")
    demo_snapshot.save(snapshot, path)
    demo_snapshot.SNAPSHOT_PATH = path
    check("it loads back", bool(demo_snapshot.load()), True)

    reader, _ = auth.create_user("reader@example.com", "a-long-enough-pass",
                                 "fernlake")
    written = demo_data.seed_demo_data(reader["id"])
    check("the reader is seeded from it", written, 10)

    with db.get_db() as conn:
        seeded = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE user_id = ? AND is_demo = 1",
            (reader["id"],)).fetchone()["n"]
        invented = conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE user_id = ? "
            "AND name LIKE '[DEMO]%'", (reader["id"],)).fetchone()["n"]
    check("with the real posts", seeded, 10)
    check("and none of the written ones", invented, 0)
    with db.get_db() as conn:
        unmarked = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE user_id = ? AND is_demo = 0",
            (reader["id"],)).fetchone()["n"]
    # Real posts, but not THEIR posts. They are still sample data and the feed
    # still has to retire them the moment a genuine capture lands.
    check("every one still marked as sample", unmarked, 0)

    print()
    print("the numbers survive the trip")
    # The whole justification for this feature: what the demo shows has to be
    # what actually happened, or it is the written set with extra steps.
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = reader["id"]
        scored = outliers.score_posts(appmod._scoring_rows())
    check("all ten score", len(scored), 10)
    check("the breakout is still the breakout",
          max(s["outlier_multiple"] for s in scored) > 5, True)
    check("and its likes are untouched",
          max(s["likes"] for s in scored), 900)

    print()
    print("and they read as posted recently, not last spring")
    with db.get_db() as conn:
        newest = conn.execute(
            "SELECT MAX(posted_at) AS t FROM posts WHERE user_id = ?",
            (reader["id"],)).fetchone()["t"]
    age_days = (datetime.now(timezone.utc)
                - datetime.fromisoformat(newest).replace(tzinfo=timezone.utc)).days
    check("the newest post is days old, not months", age_days < 3, True)

    print()
    print("one copy of each picture, shared by everyone")
    # Ninety images per account is the entire disk by a few hundred users.
    third, _ = auth.create_user("third@example.com", "a-long-enough-pass",
                                "hollowbrook")
    check("a second account is seeded too",
          demo_data.seed_demo_data(third["id"]), 10)
    stored = [f for f in os.listdir(demo_snapshot.IMAGE_DIR) if f.endswith(".jpg")]
    check("  and still exactly one picture on disk", len(stored), 1)

    print()
    print("but it is still only served to whoever owns the post")
    # The marker decides WHERE the bytes come from. It must not decide whether
    # the caller may have them — that is the ownership query, and a shared file
    # is exactly the kind of shortcut that quietly skips it.
    with db.get_db() as conn:
        their_photo = conn.execute(
            "SELECT id FROM posts WHERE user_id = ? AND image_url LIKE 'demo:%'",
            (reader["id"],)).fetchone()["id"]

    owner = appmod.app.test_client()
    with owner.session_transaction() as s:
        s["user_id"] = reader["id"]
    stranger = appmod.app.test_client()
    with stranger.session_transaction() as s:
        s["user_id"] = third["id"]

    check("the owner gets it", owner.get("/img/%d" % their_photo).status_code, 200)
    check("  as an image",
          owner.get("/img/%d" % their_photo)
          .headers["Content-Type"].startswith("image/"), True)
    check("another account cannot, shared file or not",
          stranger.get("/img/%d" % their_photo).status_code, 404)

    print()
    print("a missing or broken snapshot falls back, it does not break signup")
    demo_snapshot.SNAPSHOT_PATH = os.path.join(tmp, "nothing-here.json")
    check("no snapshot loads as None", demo_snapshot.load(), None)
    fourth, _ = auth.create_user("fourth@example.com", "a-long-enough-pass",
                                 "willowmere")
    check("and the written set is used instead",
          demo_data.seed_demo_data(fourth["id"]) > 0, True)

    broken = os.path.join(tmp, "broken.json")
    io.open(broken, "w", encoding="utf-8").write("{not json at all")
    demo_snapshot.SNAPSHOT_PATH = broken
    check("unparseable is None too", demo_snapshot.load(), None)

    wrong = os.path.join(tmp, "wrong.json")
    io.open(wrong, "w", encoding="utf-8").write(
        json.dumps({"format": 999, "sources": [{"fb_id": "x", "posts": []}]}))
    demo_snapshot.SNAPSHOT_PATH = wrong
    check("so is a format from the future", demo_snapshot.load(), None)

    print()
    print("a source with nothing in it is REPORTED, not silently dropped")
    # This is the bug the first real export had: five sources were chosen, four
    # were empty, three posts came out, and it looked like it had worked. A
    # snapshot under MIN_SAMPLE seeds a feed that ranks nothing.
    demo_snapshot.SNAPSHOT_PATH = path
    with db.get_db() as conn:
        # Not a fixed id — the accounts seeded above already hold sources, so
        # whichever number this lands on is the one to use.
        empty_id = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) "
            "VALUES (?, 'group:empty', 'group', 'Never Scanned')",
            (boss["id"],)).lastrowid
    mixed = demo_snapshot.build([1, empty_id], boss["id"])
    check("the usable source is kept", len(mixed["sources"]), 1)
    check("the empty one is reported", len(mixed["skipped"]), 1)
    check("  by name", mixed["skipped"][0]["name"], "Never Scanned")
    check("  with a reason", mixed["skipped"][0]["reason"], "nothing captured yet")

    print()
    print("a source whose posts have NO dates still works")
    # posted_at is nullable: the extension stores null when it cannot read a
    # timestamp off the page, which happens on some profile layouts. A whole
    # profile used to be refused over it — "no readable post dates", true and
    # useless when the posts themselves are perfectly good. Their age now
    # comes from when the scan ran, which is a different fact but a real one.
    with db.get_db() as conn:
        undated_id = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) "
            "VALUES (?, 'profile:undated', 'profile', 'No Timestamps')",
            (boss["id"],)).lastrowid
        for index in range(10):
            conn.execute(
                "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
                "post_type, posted_at, captured_at, likes, engagement_read, "
                "is_demo) VALUES (?, ?, ?, 'A dateless but real post.', "
                "'text', NULL, datetime('now', ?), ?, 1, 0)",
                (boss["id"], "undated-%d" % index, undated_id,
                 "-%d hours" % (index + 1), 60 + index * 7))

    rescued = demo_snapshot.build([undated_id], boss["id"])
    check("the source is kept, not refused", len(rescued["sources"]), 1)
    check("  with all its posts", len(rescued["sources"][0]["posts"]), 10)
    check("  every one carrying an age",
          all(p["hours_ago"] is not None
              for p in rescued["sources"][0]["posts"]), True)
    check("  and it says where the ages came from",
          rescued["sources"][0]["from_capture"], 10)
    check("nothing was skipped", rescued["skipped"], [])

    print()
    print("but a post with no date at ALL is reported with the raw values")
    # Belt and braces: if captured_at were somehow unusable too, the report has
    # to say what it actually saw rather than just that something failed.
    with db.get_db() as conn:
        broken_id = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) "
            "VALUES (?, 'group:nodates', 'group', 'No Dates At All')",
            (boss["id"],)).lastrowid
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
            "post_type, posted_at, captured_at, likes, engagement_read) "
            "VALUES (?, 'broken-1', ?, 'b', 'text', 'not a date', "
            "'also not a date', 50, 1)", (boss["id"], broken_id))
    broken = demo_snapshot.build([broken_id], boss["id"])
    check("it is skipped", len(broken["skipped"]), 1)
    check("  saying no usable dates",
          broken["skipped"][0]["reason"], "no usable dates on any post")
    check("  and showing what it saw",
          "not a date" in (broken["skipped"][0]["samples"] or [""])[0], True)

    print()
    print("saving publishes it — no download, no commit, no deploy")
    demo_snapshot.LIVE_PATH = os.path.join(tmp, "live.json")
    published, skipped = demo_snapshot.publish([1, empty_id], boss["id"], limit=8)
    check("it reports what it saved", published["sources"], 1)
    check("  honouring the per-source cap", published["posts"], 8)
    check("  and still names what it skipped", len(skipped), 1)
    check("the file is on the disk", os.path.isfile(demo_snapshot.LIVE_PATH), True)

    # The pictures were written at save time, not left as base64 for the first
    # signup to pay for.
    saved = json.load(io.open(demo_snapshot.LIVE_PATH, encoding="utf-8"))
    carried = [p for s in saved["sources"] for p in s["posts"]]
    check("no image bytes are left in the file",
          any("image" in p for p in carried), False)
    check("but a picture is still referenced",
          any(p.get("image_ref") for p in carried), True)

    fifth, _ = auth.create_user("fifth@example.com", "a-long-enough-pass",
                                "alderway")
    check("and a new account is seeded from it",
          demo_data.seed_demo_data(fifth["id"]), 8)
    with db.get_db() as conn:
        has_picture = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE user_id = ? "
            "AND image_url LIKE 'demo:%'", (fifth["id"],)).fetchone()["n"]
    check("  pictures and all", has_picture > 0, True)

    print()
    print("publishing nothing usable refuses rather than emptying the demo")
    # Saving an empty snapshot would replace a working sample set with one that
    # ranks nothing, which is worse than changing nothing at all.
    empty, why = demo_snapshot.publish([empty_id], boss["id"])
    check("it declines", empty, None)
    check("  and says which source and why", why[0]["name"], "Never Scanned")
    check("the previous snapshot is untouched",
          demo_snapshot.summary()["posts"], 8)

    print()
    print("and it can be put back")
    check("clearing removes it", demo_snapshot.clear(), True)
    demo_snapshot.SNAPSHOT_PATH = os.path.join(tmp, "nothing-here.json")
    check("  falling back to the written set",
          demo_snapshot.load(), None)

    print()
    print("the export is the operator's own captures and nobody else's")
    demo_snapshot.SNAPSHOT_PATH = path
    demo_snapshot.SNAPSHOT_PATH = path
    check("another account's source exports nothing",
          demo_snapshot.build([1], reader["id"])["sources"], [])

    admin_client = appmod.app.test_client()
    with admin_client.session_transaction() as s:
        s["user_id"] = reader["id"]
        s["csrf_token"] = "t"
    check("and a non-admin cannot export at all",
          admin_client.post("/admin/demo-snapshot",
                            data={"source_id": "1", "csrf_token": "t"}
                            ).status_code, 403)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("real posts in, real numbers out, one copy of each picture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
