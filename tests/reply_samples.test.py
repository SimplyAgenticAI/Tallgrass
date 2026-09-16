"""Example comments and chats: there on day one, gone the moment real ones arrive.

A new account's Today, Comments and Messages pages were empty descriptions of
features nobody had seen work. Examples fix that — and they are only safe if
they never pose as real: never in the red waiting badge, labelled everywhere,
replaced by the first real save in the same transaction, never used as the
owner's voice, and seeded once.

Also: the AI allowance meter appears where drafts are made, only when an
allowance actually applies.

Run: python tests/reply_samples.test.py
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


def db_user(db, user_id):
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def sign_up(client, email, username):
    client.post("/register", data={"email": email, "password": "a-long-enough-pass",
                                   "password_confirm": "a-long-enough-pass", "username": username})
    client.get("/today")
    with client.session_transaction() as s:
        return s["fresh_api_key"], s.get("csrf_token")


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)

    import db
    import today
    import comments
    import messages
    import reply_samples
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    print("a new account")
    me = appmod.app.test_client()
    key, csrf = sign_up(me, "new@example.com", "birchwood")
    uid = 1
    page = me.get("/today").get_data(as_text=True)
    check("Today shows examples, labelled", "These are examples" in page and "sample" in page, True)
    check("  with the example people in it", "Dana Brooks" in page and "Chris Alvarez" in page, True)
    check("the waiting badge does not count them", today.waiting_count(uid), 0)
    check("  so there is no red count in the nav", 'class="nav-count"' in page, False)
    check("Comments shows the example post",
          "wish I" in me.get("/comments").get_data(as_text=True), True)
    lists = messages.inbox(uid)
    check("Messages shows an example in every list",
          [len(lists["waiting"]), len(lists["replied"]), len(lists["quiet"])], [2, 1, 1])
    check("the example reply is never used as your voice", comments.recent_own_replies(uid), [])

    print()
    print("the first real save replaces them")
    me.post("/api/comments", headers={"X-Outlier-Key": key}, json={
        "post": {"key": "p:1", "title": "Real post"},
        "comments": [{"key": "c:1", "author": "Real Person", "text": "Price?", "verdict": "unanswered"}]})
    posts = comments.threads_for(uid)["posts"]
    check("example comments are gone, the real one is there",
          [p["title"] for p in posts], ["Real post"])
    check("  the example chats stay until real chats arrive",
          len(messages.inbox(uid)["waiting"]), 2)
    me.post("/api/messages/threads", headers={"X-Outlier-Key": key}, json={"threads": [
        {"key": "t:9", "name": "Real Chat", "last_from": "them", "last_hash": "x"}]})
    check("  and then they go too",
          [t["name"] for t in messages.inbox(uid)["waiting"]], ["Real Chat"])
    check("the badge now counts the real ones", today.waiting_count(uid), 2)

    print()
    print("seeded once")
    messages.forget_all(uid)
    for post in comments.threads_for(uid, show_done=True)["posts"]:
        comments.forget_post(uid, post["id"])
    me.get("/today")
    me.get("/comments")
    check("clearing everything does not bring the examples back",
          (len(comments.threads_for(uid)["posts"]), len(messages.inbox(uid)["waiting"])), (0, 0))

    print()
    print("an account already using it gets none")
    veteran = appmod.app.test_client()
    vkey, _ = sign_up(veteran, "vet@example.com", "oakley")
    with db.get_db() as conn:
        vid = conn.execute("SELECT id FROM users WHERE email = 'vet@example.com'").fetchone()[0]
        conn.execute("DELETE FROM user_settings WHERE user_id = ? AND key = ?", (vid, reply_samples.SEEDED_KEY))
        conn.execute("DELETE FROM comment_posts WHERE user_id = ?", (vid,))
        conn.execute("DELETE FROM message_threads WHERE user_id = ?", (vid,))
        conn.execute("INSERT INTO message_threads (user_id, thread_key, name, last_from) "
                     "VALUES (?, 't:real', 'Real', 'them')", (vid,))
    check("no examples beside real data", reply_samples.seed_once(vid), False)

    print()
    print("the AI allowance meter")
    # The first account on an install is its owner, and owners are never
    # metered — so the meter is checked on the second, an ordinary account.
    check("the first account is the owner", bool(db_user(db, uid)["is_admin"]), True)
    with db.get_db() as conn:
        vid_row = conn.execute("SELECT id FROM users WHERE email = 'vet@example.com'").fetchone()
    check("no meter when drafts do not run on a shared key",
          "AI drafts used this month" in veteran.get("/today").get_data(as_text=True), False)
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    html = veteran.get("/today").get_data(as_text=True)
    check("on the shared key, the allowance is shown", "0 of 40 AI drafts used this month" in html, True)
    for _ in range(38):
        db.record_ai_call(vid_row[0], "reply")
    check("  and warns when it is nearly gone",
          "2 left" in veteran.get("/comments").get_data(as_text=True), True)
    for _ in range(2):
        db.record_ai_call(vid_row[0], "reply")
    check("  and says what to do when it is gone",
          "reached this month" in veteran.get("/messages").get_data(as_text=True), True)
    check("the owner is never metered",
          "AI drafts used this month" in me.get("/today").get_data(as_text=True), False)
    os.environ.pop("ANTHROPIC_API_KEY", None)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("examples show the way, and step aside")
    return 0


if __name__ == "__main__":
    sys.exit(main())
