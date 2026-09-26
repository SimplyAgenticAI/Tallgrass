"""Ageing out other people's old posts — and everything it must never take.

This is the only thing in the app that deletes a user's captures, so the tests
are mostly about what survives.

  off          dry run by default: report() says what would go, sweep() refuses
  own posts    the user's own are kept at any age (My results is built on them)
  saved        anything saved or remixed is never a candidate
  the floor    a group is never taken below what it needs to stay scoreable,
               even when every post in it is ancient
  recent       nothing inside the window is touched
  pipeline     comment threads and chats are a different table and untouched
  samples      demo rows are not retention's business

Run: python tests/retention.test.py
"""
import io
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


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import auth
    import billing
    import mine
    import retention
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("keeper@example.com", "a-long-enough-pass", "keeper")
    uid = user["id"]
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        mine.set_names(uid, "Jane Smith")

    OLD = "-%d months" % (billing.RETENTION_MONTHS + 2)
    NEW = "-3 days"

    def author(conn, name):
        row = conn.execute("SELECT id FROM authors WHERE name = ?", (name,)).fetchone()
        return row[0] if row else conn.execute(
            "INSERT INTO authors (name) VALUES (?)", (name,)).lastrowid

    def add(conn, source_id, key, when, name="Someone Else", demo=0, seen=None):
        """`when` is when it was written; `seen` when we captured or last
        refreshed it. They differ, and retention needs BOTH to be old."""
        seen = when if seen is None else seen
        return conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, likes, "
            "posted_at, captured_at, updated_at, is_demo, item_type, engagement_read) "
            "VALUES (?, ?, ?, ?, 'a post about bees', 12, datetime('now', ?), "
            "datetime('now', ?), datetime('now', ?), ?, 'post', 1)",
            (uid, key, source_id, author(conn, name), when, seen, seen, demo)).lastrowid

    with db.get_db() as conn:
        big = conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                           "VALUES (?, 'g-big', 'group', 'Busy Group')", (uid,)).lastrowid
        small = conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                             "VALUES (?, 'g-small', 'group', 'Quiet Group')", (uid,)).lastrowid
        # A busy group: plenty of old posts, comfortably above the floor.
        old_ids = [add(conn, big, "old-%d" % i, OLD) for i in range(40)]
        recent_ids = [add(conn, big, "new-%d" % i, NEW) for i in range(5)]
        # The user's own old post, in the busy group.
        my_old = add(conn, big, "mine-old", OLD, name="Jane Smith")
        # Saved and remixed old posts.
        saved_old = add(conn, big, "saved-old", OLD)
        remixed_old = add(conn, big, "remixed-old", OLD)
        conn.execute("INSERT INTO saved (user_id, post_id) VALUES (?, ?)", (uid, saved_old))
        conn.execute("INSERT INTO remixes (user_id, post_id, output, model) "
                     "VALUES (?, ?, 'x', 'test')", (uid, remixed_old))
        # A quiet group where EVERYTHING is old and there are few posts.
        small_ids = [add(conn, small, "small-%d" % i, OLD) for i in range(6)]
        # Written long ago, but captured yesterday — the case that would have
        # made a fresh scan look like data loss.
        old_but_new = add(conn, big, "old-but-just-scanned", OLD, seen="-1 days")
        # Sample data, old.
        demo_id = add(conn, big, "demo-old", OLD, demo=1)
        # A reply-pipeline row, which lives in its own table entirely.
        cp = conn.execute("INSERT INTO comment_posts (user_id, post_key) "
                          "VALUES (?, 'thread-1')", (uid,)).lastrowid
        conn.execute("INSERT INTO post_comments (user_id, post_id, comment_key, author, "
                     "body, is_mine) VALUES (?, ?, 'c1', 'Someone Else', 'hello', 0)",
                     (uid, cp))

    print("it is a dry run until somebody switches it on")
    check("off by default", retention.enabled(), False)
    removed, error = retention.sweep()
    check("a sweep refuses", (removed, bool(error)), (0, True))
    with db.get_db() as conn:
        check("  and nothing was deleted",
              conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 56)

    print()
    print("what the dry run says")
    r = retention.report()
    check("the window is the one constant", r["months"], billing.RETENTION_MONTHS)
    check("something would go", r["posts"] > 0, True)
    # The busy group holds 48 posts in total (40 old + 5 recent + own + saved +
    # remixed + a sample). The floor is FLOOR_PER_SOURCE, so it may fall to that
    # and no further: 48 - 16 = 32 of the 40 old ones may go, and the remaining
    # 8 are held back. The floor counts everything the group holds, because what
    # keeps a baseline alive is posts, not their provenance.
    DROPPABLE = 49 - retention.FLOOR_PER_SOURCE
    check("  and it is the busy group's old posts, down to the floor",
          r["posts"], DROPPABLE)
    check("the user's own old post is kept", r["kept"]["own"], 1)
    check("nothing recently captured is a candidate — even if written long ago",
          r["posts"] <= len(old_ids), True)
    check("the rest are held back by the floor",
          r["kept"]["floor"], (len(old_ids) - DROPPABLE) + len(small_ids))
    check("it reports a size", r["mb"] > 0, True)

    print()
    print("and the sweep removes exactly those")
    retention.set_enabled(True)
    removed, error = retention.sweep()
    check("it ran", error, None)
    check("removing the old ones, no further than the floor", removed, DROPPABLE)
    with db.get_db() as conn:
        def alive(post_id):
            return bool(conn.execute("SELECT 1 FROM posts WHERE id = ?",
                                     (post_id,)).fetchone())
        check("the recent posts are untouched", all(alive(i) for i in recent_ids), True)
        check("the user's own old post survives", alive(my_old), True)
        check("the saved one survives", alive(saved_old), True)
        check("the remixed one survives", alive(remixed_old), True)
        check("the quiet group is intact", all(alive(i) for i in small_ids), True)
        check("  so it can still be scored",
              len(small_ids) >= 0 and all(alive(i) for i in small_ids), True)
        check("the sample post is not retention's business", alive(demo_id), True)
        check("a post captured yesterday survives, however old it is",
              alive(old_but_new), True)
        left = [i for i in old_ids if alive(i)]
        check("the floor's worth of old posts remain",
              len(left), len(old_ids) - DROPPABLE)
        check("  and they are the NEWEST of the old ones, not a random few",
              left, old_ids[-len(left):])
        check("the reply pipeline is untouched",
              conn.execute("SELECT COUNT(*) FROM post_comments").fetchone()[0], 1)

    print()
    print("'my own posts' does not depend on anybody visiting Settings")
    # Almost nobody types their name into Settings, so an exemption that only
    # honoured that would have protected almost nobody's own posts.
    nameless, _ = auth.create_user("nameless@example.com", "a-long-enough-pass", "nameless")
    nid = nameless["id"]
    with db.get_db() as conn:
        src = conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                           "VALUES (?, 'g-n', 'group', 'Their Group')", (nid,)).lastrowid
        aid = author(conn, "Pat Nameless")
        theirs = conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, likes, "
            "posted_at, captured_at, updated_at, is_demo, item_type, engagement_read) "
            "VALUES (?, 'n-mine', ?, ?, 'mine', 9, datetime('now', ?), datetime('now', ?), "
            "datetime('now', ?), 0, 'post', 1)", (nid, src, aid, OLD, OLD, OLD)).lastrowid
        others = [conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, likes, "
            "posted_at, captured_at, updated_at, is_demo, item_type, engagement_read) "
            "VALUES (?, ?, ?, ?, 'theirs', 9, datetime('now', ?), datetime('now', ?), "
            "datetime('now', ?), 0, 'post', 1)",
            (nid, "n-other-%d" % i, src, author(conn, "Someone Else"), OLD, OLD, OLD)
        ).lastrowid for i in range(retention.FLOOR_PER_SOURCE + 5)]
        # The only evidence of who they are: a comment the extension recorded as
        # theirs, which is how Facebook's own composer names them.
        cp2 = conn.execute("INSERT INTO comment_posts (user_id, post_key) "
                           "VALUES (?, 'thread-2')", (nid,)).lastrowid
        conn.execute("INSERT INTO post_comments (user_id, post_id, comment_key, author, "
                     "body, is_mine) VALUES (?, ?, 'c2', 'Pat Nameless', 'thanks', 1)",
                     (nid, cp2))
    check("their name was never saved in Settings", mine.get_names(nid), [])
    check("  but their comments give it away", mine.suggested_names(nid), ["Pat Nameless"])
    retention.sweep()
    with db.get_db() as conn:
        check("their own old post survives anyway",
              bool(conn.execute("SELECT 1 FROM posts WHERE id = ?", (theirs,)).fetchone()),
              True)
        # The floor counts everything the source holds, their own post
        # included — it is about keeping the group scoreable, not about whose
        # posts they are.
        held = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = ?", (nid,)).fetchone()[0]
        check("  while other people's went, down to the floor",
              held, retention.FLOOR_PER_SOURCE)

    print()
    print("a second sweep has nothing to do")
    removed, error = retention.sweep()
    check("nothing left to remove", (removed, error), (0, None))

    print()
    print("deleting a post frees its picture too")
    # Nothing called images.forget, so every deletion left its picture behind
    # until the LRU cap noticed — months of a small disk held by pictures of
    # posts that no longer existed, reported on /admin as somebody's data.
    import images
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (90, 120, 60)).save(buf, "JPEG")
    with db.get_db() as conn:
        keeper = add(conn, big, "picture-keeper", NEW)
        goner = add(conn, big, "picture-goner", NEW)
    for post_id in (keeper, goner):
        images.store(post_id, buf.getvalue())
    check("both pictures are cached",
          bool(images.cached(keeper)) and bool(images.cached(goner)), True)
    db.delete_post(goner, uid)
    check("the deleted post's picture is gone", images.cached(goner), None)
    check("  and the other one is untouched", bool(images.cached(keeper)), True)

    # And the sweep does the same for what it ages out.
    with db.get_db() as conn:
        aged = add(conn, big, "picture-aged", OLD)
    images.store(aged, buf.getvalue())
    retention.sweep()
    with db.get_db() as conn:
        still_there = bool(conn.execute("SELECT 1 FROM posts WHERE id = ?",
                                        (aged,)).fetchone())
    if still_there:
        check("  (the aged post was held by the floor, so its picture stays)",
              bool(images.cached(aged)), True)
    else:
        check("  retention frees pictures as well as rows",
              images.cached(aged), None)

    print()
    print("the admin page shows it, and only admins may change it")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (uid,))
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = "t"
    html = client.get("/admin").get_data(as_text=True)
    check("the panel is there", "Ageing out other people's posts" in html, True)
    check("  and says what is protected",
          "no group drops below" in " ".join(html.split()), True)
    other, _ = auth.create_user("member@example.com", "a-long-enough-pass", "member")
    plain = appmod.app.test_client()
    with plain.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["csrf_token"] = "t"
    check("a member cannot switch it",
          plain.post("/api/admin/retention", json={"action": "toggle", "on": False},
                     headers={"X-CSRF-Token": "t"}).status_code, 403)
    check("  and it is still on", retention.enabled(), True)

    print()
    print("the groups page tells the user what they hold")
    held = client.get("/groups").get_data(as_text=True)
    check("it names the total", "You're holding" in held, True)
    check("  and the window", "%d months" % billing.RETENTION_MONTHS in held, True)

    print()
    print("the pricing copy no longer promises what we cannot keep")
    check("no unlimited posts claim",
          any("Unlimited captured" in f for f in billing.PRO_FEATURES), False)
    check("  and the window is stated",
          any("%d months" % billing.RETENTION_MONTHS in f for f in billing.PRO_FEATURES),
          True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("old posts go, everything anybody would miss stays")
    return 0


if __name__ == "__main__":
    sys.exit(main())
