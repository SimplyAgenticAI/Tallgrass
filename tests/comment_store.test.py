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

    def fake_draft(post_title, author, comment, replies=None, instructions="", relationship=""):
        asked.append({"title": post_title, "author": author, "comment": comment,
                      "replies": replies, "instructions": instructions,
                      "relationship": relationship})
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
    print("drafts use your reply kit, your own voice, and a tone")
    check("the kit saves", me.post("/api/reply-kit", json={
        "booking": "https://cal.example/intro", "pricing": "Websites from $1,500"},
        headers={"X-CSRF-Token": csrf}).get_json().get("has_kit"), True)
    save({"post": {"key": "p:1"}, "comments": [
        {"key": "c:111", "author": "Jane Doe", "text": "How much?", "verdict": "answered"},
        {"key": "c:777", "parent_key": "c:111", "author": "Jeff Randle", "mine": True,
         "text": "Hey Jane! Shot you a message with the details just now."}]})
    import replies as replies_mod
    import sage as sage_mod
    from flask import g
    with appmod.app.test_request_context():
        g.user = {"id": 1, "email": "me@example.com"}
        prompt = replies_mod._prompt("New website packages", "Mark Twain", "Logos too?", [], "")
        check("the kit is in the prompt", "Websites from $1,500" in prompt and "cal.example/intro" in prompt, True)
        check("  as facts to use instead of a blank", "instead of a [blank]" in prompt, True)
        check("your own past reply is there as a voice example",
              "Shot you a message with the details" in prompt, True)
        check("  but never a draft", "Sending you a message now" in prompt, False)
        check("another account's kit is its own",
              sage_mod.get_kit()["pricing"], "Websites from $1,500")
    with appmod.app.test_request_context():
        g.user = {"id": 2, "email": "other@example.com"}
        check("  (the other account has none)", sage_mod.kit_summary(), "")

    me.post("/comments/%d/draft" % jane["id"],
            json={"instructions": "Rewrite this draft and make it noticeably shorter"},
            headers={"X-CSRF-Token": csrf})
    check("a tone reaches the draft as the user's direction",
          asked[-1]["instructions"], "Rewrite this draft and make it noticeably shorter")
    settings_html = me.get("/settings").get_data(as_text=True)
    check("Settings shows the reply kit, filled in",
          "Your reply kit" in settings_html and "Websites from $1,500" in settings_html, True)

    print()
    print("they wrote again after your reply")
    save({"post": {"key": "p:back"}, "comments": [
        {"key": "c:5001", "author": "Rae Wu", "text": "Resend please?", "verdict": "unanswered",
         "came_back": True}]})
    rae = [t for p in comments.threads_for(1)["posts"] for t in p["threads"] if t["author"] == "Rae Wu"][0]
    check("is stored, so the page can say why", bool(rae["came_back"]), True)
    check("  and says it", "wrote again after your last reply" in me.get("/comments").get_data(as_text=True), True)

    print()
    print("Open goes to the post, never the commenter")
    profile = "https://www.facebook.com/dana.brooks?comment_id=Y29tbWVudDo5ODc2NV80NDQ0"
    save({"post": {"key": "p:links", "url": "https://www.facebook.com/me/posts/77"},
          "comments": [{"key": "c:4444", "author": "Dana Brooks", "text": "How much?",
                        "verdict": "unanswered", "url": profile}]})
    with db.get_db() as conn:
        stored = conn.execute("SELECT url FROM post_comments WHERE comment_key = 'c:4444'").fetchone()["url"]
    check("a profile link sent by an older extension is not stored as the comment's link", stored, None)
    with db.get_db() as conn:
        conn.execute("UPDATE post_comments SET url = ? WHERE comment_key = 'c:4444'", (profile,))
    dana = [t for p in comments.threads_for(1)["posts"] for t in p["threads"] if t["author"] == "Dana Brooks"][0]
    check("one already stored is not offered as its link", dana["url"], None)
    html = me.get("/comments").get_data(as_text=True)
    check("  so the page's Open falls back to the post", profile in html, False)
    check("  which is there", "https://www.facebook.com/me/posts/77" in html, True)
    check("a real post link is kept",
          comments.post_link("https://www.facebook.com/me/posts/77?comment_id=4444"),
          "https://www.facebook.com/me/posts/77?comment_id=4444")

    print()
    print("message them")
    save({"post": {"key": "p:dm", "title": "Website packages"}, "comments": [
        {"key": "c:8001", "author": "Dana Price", "text": "How much for 5 pages?", "verdict": "unanswered",
         "author_url": "https://www.facebook.com/dana.price?comment_id=Y29t"},
        {"key": "c:8002", "author": "Not A Person", "text": "Spam", "verdict": "unanswered",
         "author_url": "https://evil.test/x"}]})
    rows = {t["author"]: t for p in comments.threads_for(1)["posts"] for t in p["threads"]}
    check("a commenter's profile becomes a Messenger link",
          rows["Dana Price"]["dm_url"], "https://www.facebook.com/messages/t/dana.price")
    check("  anything that isn't a Facebook profile is never kept", rows["Not A Person"]["dm_url"], None)
    html = me.get("/comments").get_data(as_text=True)
    check("  the page offers Message them, carrying what they said",
          'data-handoff-text="How much for 5 pages?"' in html and ">Message them</a>" in html, True)
    check("the server's rules match the extension's",
          [comments.messenger_link(u) for u in (
              "https://www.facebook.com/profile.php?id=10001234",
              "https://www.facebook.com/groups/cats/user/555/",
              "https://www.facebook.com/dana/posts/123")],
          ["https://www.facebook.com/messages/t/10001234", "https://www.facebook.com/messages/t/555", None])

    import replies as replies_real
    from flask import g
    captured = {}
    real_anthropic = replies_real._anthropic
    replies_real._anthropic = lambda cfg, prompt, system=None: (captured.update(prompt=prompt) or ("Hi Dana!", None))
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    with appmod.app.test_request_context():
        g.user = {"id": 1}
        text, err = replies_real.draft_message(
            "Dana Brooks", [], context={"name": "Dana Brooks", "text": "How much for 5 pages?",
                                        "title": "Website packages"})
    os.environ.pop("ANTHROPIC_API_KEY", None)
    replies_real._anthropic = real_anthropic
    check("a first DM can be drafted from the comment alone", (text, err), ("Hi Dana!", None))
    check("  and knows what they said and where",
          "How much for 5 pages?" in captured["prompt"] and "Website packages" in captured["prompt"]
          and "this is the first message" in captured["prompt"], True)

    print()
    print("a comment that gains its Facebook id is not stored twice")
    save({"post": {"key": "p:links"}, "comments": [
        {"key": "h:kim", "author": "Kim Park", "text": "Do you deliver to Austin?", "verdict": "unanswered"},
        {"key": "h:kimr", "parent_key": "h:kim", "author": "Jeff Randle", "text": "We do!", "mine": True}]})
    save({"post": {"key": "p:links"}, "comments": [
        {"key": "c:9999", "author": "Kim Park", "text": "Do you deliver to Austin?", "verdict": "answered"}]})
    with db.get_db() as conn:
        kims = conn.execute("SELECT comment_key FROM post_comments WHERE author = 'Kim Park'").fetchall()
        reply_parent = conn.execute(
            "SELECT parent_key FROM post_comments WHERE comment_key = 'h:kimr'").fetchone()["parent_key"]
    check("one comment, now under its Facebook id", [r["comment_key"] for r in kims], ["c:9999"])
    check("  and its reply still points at it", reply_parent, "c:9999")

    print()
    print("the page")
    html = me.get("/comments").get_data(as_text=True)
    check("renders", "Unanswered" in html or "Check replies" in html, True)
    check("names the post", "New website packages" in html, True)
    check("says a reply is folded", "tell if you answered" in html, True)
    check("nav says Extension, not Capture", ">Extension</a>" in html and ">Capture</a>" not in html, True)
    check("nav has Comments", ">Comments</a>" in html, True)
    nav = html.split('<nav class="topnav">', 1)[1].split("</nav>", 1)[0]
    in_view = nav.split("<details", 1)[0]
    check("five links in view: Today, Feed, Groups, Write, Sage",
          [label for label in ("Today", "Feed", "Groups", "Write", "Sage", "Library", "Comments", "Settings")
           if ">" + label in in_view], ["Today", "Feed", "Groups", "Write", "Sage"])
    check("  Comments, Messages, Library and Playbook under More",
          all(">" + l + "</a>" in nav for l in ("Comments", "Messages", "Library", "Playbook")), True)
    account_menu = html.split("account-menu", 1)[1].split("</details>", 1)[0]
    check("  Extension, Settings, Health and Feedback in the account menu",
          all(">" + l + "</a>" in account_menu for l in ("Account", "Extension", "Settings", "Health", "Feedback")), True)
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
