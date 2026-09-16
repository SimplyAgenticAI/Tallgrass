"""Saved comments stay put, and stay yours.

The Comments page is a to-do list of people waiting on an answer. Two ways it
could quietly betray that: a second read of the same post undoing a "Done" (so
the list never gets shorter), or a comment scrolled out of view on the second
read vanishing (so the one you needed is gone). And like every capture, one
account's comments must never reach another's.

Run: python tests/comment_store.test.py
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
    return client.post("/register", data={
        "email": email, "password": "a-long-enough-pass",
        "password_confirm": "a-long-enough-pass", "username": username})


def thread(extra=None):
    items = [
        {"key": "c:111", "author": "Jane Doe", "text": "How much?", "verdict": "answered",
         "url": "https://www.facebook.com/me/posts/1?comment_id=111"},
        {"key": "c:222", "parent_key": "c:111", "author": "Jeff Randle",
         "text": "Sent a DM", "mine": True},
        {"key": "c:333", "author": "Mark Twain", "text": "Logos too?", "verdict": "unanswered"},
        {"key": "c:444", "author": "Sara Lee", "text": "Great", "verdict": "unknown",
         "hidden_replies": 2},
    ]
    return {"post": {"key": "p:1", "url": "https://www.facebook.com/me/posts/1",
                     "title": "New website packages", "more_comments": False},
            "comments": items + (extra or [])}


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import comments
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    me = appmod.app.test_client()
    sign_up(me, "me@example.com", "birchwood")
    me.get("/comments")                    # the CSRF token is made on first render
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
        csrf = s.get("csrf_token")

    def save(payload, api_key=key):
        return me.post("/api/comments", json=payload, headers={"X-Outlier-Key": api_key})

    print("saving a thread")
    check("needs a key", save(thread(), api_key="olk_wrong").status_code, 401)
    check("needs a post", save({"comments": []}).status_code, 400)
    response = save(thread())
    body = response.get_json()
    check("accepted", response.status_code, 200)
    check("four rows stored", body["comments"], 4)
    check("all new the first time", body["new"], 4)
    check("verdicts counted for comments only",
          body["verdicts"], {"unanswered": 1, "unknown": 1, "answered": 1, "yours": 0})

    data = comments.threads_for(1)
    post = data["posts"][0]
    check("one post", len(data["posts"]), 1)
    check("unanswered listed first", post["threads"][0]["author"], "Mark Twain")
    check("the reply sits under its comment",
          [r["author"] for t in post["threads"] for r in t["replies"]], ["Jeff Randle"])

    print()
    print("a second read")
    mark = [t for t in post["threads"] if t["author"] == "Mark Twain"][0]
    page = me.post("/comments/%d/status" % mark["id"],
                   data={"status": "done", "csrf_token": csrf})
    check("done is accepted", page.status_code, 302)
    partial = thread()
    partial["comments"] = [c for c in partial["comments"] if c["key"] != "c:444"]
    body = save(partial).get_json()
    check("nothing new", body["new"], 0)
    data = comments.threads_for(1, show_done=True)
    by = {t["author"]: t for t in data["posts"][0]["threads"]}
    check("done survives a re-read", by["Mark Twain"]["status"], "done")
    check("a comment missing from the re-read is kept", "Sara Lee" in by, True)
    check("done is hidden by default",
          "Mark Twain" in [t["author"] for t in comments.threads_for(1)["posts"][0]["threads"]],
          False)
    check("a made-up verdict is not trusted as unanswered",
          save({"post": {"key": "p:2"}, "comments": [
              {"key": "c:9", "author": "X Y", "text": "hi", "verdict": "urgent"}]}
               ).get_json()["verdicts"]["unknown"], 1)

    print()
    print("a rescan never doubles anything")

    def counts():
        with db.get_db() as conn:
            return (conn.execute("SELECT COUNT(*) FROM comment_posts WHERE user_id = 1").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM post_comments WHERE user_id = 1").fetchone()[0])

    before = counts()
    save(thread())
    save(thread())
    check("the same read three times is the same rows", counts(), before)

    # The same post opened another way: a different address, the same comments.
    elsewhere = thread()
    elsewhere["post"] = {"key": "p:photo-98765", "url": "https://www.facebook.com/photo/?fbid=98765"}
    body = save(elsewhere).get_json()
    check("a post reached by another address is the same post", counts(), before)
    check("  and nothing in it is new", body["new"], 0)

    # A comment Facebook gave no id, read cut short and then in full.
    cut_short = {"post": {"key": "p:1"}, "comments": [
        {"key": "h:aaa", "author": "Lee Chan", "verdict": "unanswered",
         "text": "Do you ship to Canada and how long does it usually … See more"}]}
    in_full = {"post": {"key": "p:1"}, "comments": [
        {"key": "h:bbb", "author": "Lee Chan", "verdict": "unanswered",
         "text": "Do you ship to Canada and how long does it usually take to arrive?"}]}
    save(cut_short)
    after_first = counts()
    check("a comment read cut short, then in full, is one comment",
          (save(in_full).get_json()["new"], counts()), (0, after_first))
    save(cut_short)
    with db.get_db() as conn:
        stored = conn.execute("SELECT body FROM post_comments WHERE author = 'Lee Chan'").fetchall()
    check("  keeping the full words, even after another short read",
          [r["body"] for r in stored],
          ["Do you ship to Canada and how long does it usually take to arrive?"])
    two = {"post": {"key": "p:1"}, "comments": [
        {"key": "h:y1", "author": "Ana Ruiz", "text": "Yes", "verdict": "unanswered"},
        {"key": "h:y2", "author": "Ana Ruiz", "text": "Yes please", "verdict": "unanswered"}]}
    check("but two short comments that start alike stay two", save(two).get_json()["new"], 2)

    print()
    print("yours only")
    other = appmod.app.test_client()
    sign_up(other, "other@example.com", "willow")
    other.get("/comments")
    with other.session_transaction() as s:
        other_csrf = s.get("csrf_token")
    other_page = other.get("/comments").get_data(as_text=True)
    check("another account sees none of it", "Logos too?" in other_page, False)
    other.post("/comments/%d/status" % mark["id"],
               data={"status": "open", "csrf_token": other_csrf})
    check("and cannot change it",
          [t for t in comments.threads_for(1, show_done=True)["posts"][0]["threads"]
           if t["author"] == "Mark Twain"][0]["status"], "done")

    print()
    print("suggesting a reply")
    asked = []

    def fake_draft(post_title, author, comment, replies=None, instructions=""):
        asked.append({"title": post_title, "author": author, "comment": comment,
                      "replies": replies})
        return "Thanks %s! Sending you a message now." % (author or "").split(" ")[0], None

    appmod.replies.draft_reply = fake_draft

    jane = [t for t in comments.threads_for(1, show_done=True)["posts"][0]["threads"]
            if t["author"] == "Jane Doe"][0]
    result = me.post("/comments/%d/draft" % jane["id"], json={},
                     headers={"X-CSRF-Token": csrf}).get_json()
    check("the Comments page gets a draft", result.get("reply"),
          "Thanks Jane! Sending you a message now.")
    check("  written from the post and the comment",
          (asked[-1]["title"], asked[-1]["comment"]), ("New website packages", "How much?"))
    check("  knowing the replies already under it",
          [r["author"] for r in asked[-1]["replies"]], ["Jeff Randle"])
    check("  and it is kept",
          comments.context_for(1, comment_id=jane["id"])["draft"],
          "Thanks Jane! Sending you a message now.")
    check("another account cannot draft on it",
          other.post("/comments/%d/draft" % jane["id"], json={},
                     headers={"X-CSRF-Token": other_csrf}).status_code, 404)

    def api_draft(body, api_key=key):
        return me.post("/api/comments/draft", json=body, headers={"X-Outlier-Key": api_key})

    check("Facebook's draft needs a key",
          api_draft({"comment": {"text": "hi"}}, api_key="olk_wrong").status_code, 401)
    result = api_draft({"post": {"key": "p:1"}, "comment": {"key": "c:333", "text": "ignored"}}).get_json()
    check("a saved comment is drafted from what was saved",
          (result.get("reply"), asked[-1]["comment"]),
          ("Thanks Mark! Sending you a message now.", "Logos too?"))
    check("  and the draft shows on the Comments page",
          "Thanks Mark! Sending you a message now." in
          me.get("/comments?done=1").get_data(as_text=True), True)
    result = api_draft({"post": {"key": "p:new", "title": "Fresh post"},
                        "comment": {"key": "c:999", "author": "Ana Ruiz", "text": "Book a call?"},
                        "replies": [{"author": "Tom Hanks", "text": "Me too"}]}).get_json()
    check("an unsaved comment is drafted from what the page sent",
          (result.get("reply"), asked[-1]["title"], asked[-1]["comment"]),
          ("Thanks Ana! Sending you a message now.", "Fresh post", "Book a call?"))

    print()
    print("the page")
    html = me.get("/comments").get_data(as_text=True)
    check("renders", "Unanswered" in html or "Check replies" in html, True)
    check("names the post", "New website packages" in html, True)
    check("says a reply is folded", "tell if you answered" in html, True)
    check("nav says Extension, not Capture", ">Extension</a>" in html and ">Capture</a>" not in html, True)
    check("nav has Comments", ">Comments</a>" in html, True)
    check("the extension page still lives at /capture",
          me.get("/capture").status_code, 200)

    pid = comments.threads_for(1)["posts"][0]["id"]
    me.post("/comments/post/%d/forget" % pid, data={"csrf_token": csrf})
    with db.get_db() as conn:
        left = conn.execute("SELECT COUNT(*) FROM post_comments WHERE post_id = ?",
                            (pid,)).fetchone()[0]
    check("forget removes the post's comments", left, 0)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("saved comments stay put, and stay yours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
