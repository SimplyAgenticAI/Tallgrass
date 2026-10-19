"""The reply queue: the unanswered comments on your posts, and a count.

The queue holds exactly the people still waiting on a reply to a comment, with
likely opportunities first, and never your own comments, answered ones, or ones
set aside. The count on the navigation and the extension icon must be the same
number the page shows.

Chats are NOT in it, and most of this file exists to hold that line.

Today used to merge unanswered comments and waiting Messenger chats. A merged
inbox competes with Facebook's own and loses on every axis that matters -
Facebook delivers in real time where this scrapes, and it has mobile apps,
labels and saved replies. The duplication was also a liability: when this said
three people were waiting and Facebook said five, the trust that went was the
trust the SCORING earned.

Comments stayed because they are a different bet. Facebook's Professional
Dashboard is Page-centric and gives a group poster no queue at all for comments
on their own posts, and only this app knows which post is an outlier.

The Today PAGE is gone as well, one step later. Once the chats had left it, it
was showing unanswered comments — which is what the Comments page already was,
so it was a second view of one list, the same duplication one level in. The tab
went, the app opens on the Feed, and Comments took the badge and the
opportunity-first ordering that was the only thing Today did better.

today.py itself stayed: the queue still feeds the extension's panel and the
count on the navigation, which is what this file tests.

So: chats keep their own page, the count counts what Comments shows, and
nothing here may quietly merge them again.

Run: python tests/today.test.py
"""
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


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import today
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    me = appmod.app.test_client()
    me.post("/register", data={"email": "me@example.com", "password": "a-long-enough-pass",
                               "password_confirm": "a-long-enough-pass", "username": "birchwood"})
    me.get("/comments")
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
        csrf = s.get("csrf_token")
    headers = {"X-Outlier-Key": key}

    print("a new account")
    first = me.get("/comments").get_data(as_text=True)
    check("the page shows labelled examples", "These are examples" in first, True)
    check("  and no red count for them", 'class="nav-count"' in first, False)

    body = me.post("/api/comments", headers=headers, json={
        # With a real post link, because the extension's panel only offers
        # entries it can open — and without one every comment was filtered out
        # of it, which left the panel queue showing nothing but chats.
        "post": {"key": "p:1", "title": "New website packages",
                 "url": "https://www.facebook.com/groups/1/posts/1/"},
        "comments": [
            {"key": "c:1", "author": "Jane Doe", "text": "How much for the full package?", "verdict": "unanswered"},
            {"key": "c:2", "author": "Tom Hanks", "text": "Love this", "verdict": "unanswered"},
            {"key": "c:3", "author": "Ana Ruiz", "text": "Thanks!", "verdict": "answered"},
            {"key": "c:4", "author": "Jeff Randle", "text": "Thanks all", "verdict": "yours", "mine": True},
            {"key": "c:5", "author": "Sara Lee", "text": "Is this for real?", "verdict": "unknown",
             "hidden_replies": 1},
        ]}).get_json()
    check("saving comments reports everyone waiting, for the icon", body.get("waiting_total"), 3)
    # Two chats waiting, one of them an opportunity. None of this may reach
    # Today, and the badge must not move.
    body = me.post("/api/messages/threads", headers=headers, json={"threads": [
        {"key": "t:1", "name": "Lee Chan", "last_from": "them", "last_at": ago(1),
         "signal": "opportunity", "last_hash": "a", "url": "https://www.facebook.com/messages/t/1/"},
        {"key": "t:2", "name": "Mark Twain", "last_from": "me", "last_at": ago(2), "last_hash": "b"},
        {"key": "t:3", "name": "Old Friend", "last_from": "them", "last_at": ago(30), "last_hash": "c"},
    ]}).get_json()
    check("  saving chats does not change it", body.get("waiting_total"), 3)

    print()
    print("the queue")
    q = today.queue(1)
    names = [i["who"] for i in q["entries"]]
    check("everyone waiting on a comment, nobody else", sorted(names),
          sorted(["Jane Doe", "Tom Hanks", "Sara Lee"]))
    check("the opportunity is first", names[0], "Jane Doe")
    check("  then questions", names[1], "Sara Lee")
    check("the count agrees with the list", today.waiting_count(1), len(q["entries"]))
    check("  and nothing is a chat", (q["comments"], q["messages"]), (3, 0))
    check("  not even the one that looked like an opportunity",
          [i for i in q["entries"] if i["kind"] != "comment"], [])

    # /today is gone. The URL still answers, because it is bookmarked and
    # older pages still post back to it.
    gone = me.get("/today")
    check("/today redirects rather than 404ing",
          (gone.status_code, gone.headers.get("Location")), (302, "/comments"))

    html = me.get("/comments").get_data(as_text=True)
    check("the page lists the comments", "Jane Doe" in html, True)
    check("  and names no chat", ("Lee Chan" in html, "Old Friend" in html), (False, False))
    check("  and does not send people to Messenger",
          "facebook.com/messages" in html, False)
    check("comments can be drafted from here", 'data-suggest="' in html, True)
    check("the nav count is what the page shows",
          'class="nav-count"' in html and ">3</span>" in html, True)
    check("  and the count sits on Comments, not on a page that is gone",
          'Comments\n      <span class="nav-count"' in html
          or 'Comments <span class="nav-count"' in html, True)
    check("there is no Today tab", ">Today" in html, False)

    # The one thing Today did better than this page, kept: an opportunity is
    # above the praise, across every post rather than within one.
    import comments as comments_mod
    data = comments_mod.threads_for(1)
    check("opportunities are ordered first here now",
          [t["author"] for t in data["posts"][0]["threads"]][:1], ["Jane Doe"])
    check("  and counted", data["totals"]["opportunities"], 1)

    # The chats did not vanish — they have their own page, which is the whole
    # point: one place for them, and it is not the one that competes.
    chats = me.get("/messages").get_data(as_text=True)
    check("the Messages page still has them",
          all(n in chats for n in ("Lee Chan", "Old Friend")), True)

    print()
    print("the queue in the extension's panel")
    panel = me.post("/api/today", headers=headers).get_json()
    check("needs a key", me.post("/api/today", headers={"X-Outlier-Key": "olk_wrong"}).status_code, 401)
    check("real people with somewhere to open, opportunities first",
          [e["who"] for e in panel["entries"]][:1], ["Jane Doe"])
    check("  only entries that can be opened", all(e["url"] for e in panel["entries"]), True)
    check("  no chats here either", [e for e in panel["entries"] if e["kind"] != "comment"], [])
    check("  and the total for the badge", panel["waiting_total"], 3)
    tom_id = [e["id"] for e in panel["entries"] if e["who"] == "Tom Hanks"][0]
    after = me.post("/api/today/done", headers=headers,
                    json={"kind": "comment", "id": tom_id}).get_json()
    check("Done from the panel returns the queue without them",
          ("Tom Hanks" in [e["who"] for e in after["entries"]], after["waiting_total"]), (False, 2))
    me.post("/comments/%d/status" % tom_id, data={"status": "open", "csrf_token": csrf})

    print()
    print("the pipeline: stage, note, snooze")
    import pipeline
    jane = [e for e in today.queue(1)["entries"] if e["who"] == "Jane Doe"][0]
    r = me.post("/pipeline/comment/%d" % jane["id"], data={
        "stage": "quoted", "note": "wants the 5-page site, ~$2k", "next": "today", "csrf_token": csrf})
    # next=today is still sent by a page somebody already had open, and it
    # lands on the list that holds the row rather than on nothing.
    check("saved from an older page, back to that row",
          r.headers.get("Location"), "/comments#comment-%d" % jane["id"])
    jane = [e for e in today.queue(1)["entries"] if e["who"] == "Jane Doe"][0]
    check("  stage and note stored", (jane["stage"], jane["note"]), ("quoted", "wants the 5-page site, ~$2k"))
    check("  and counted in the pipeline", pipeline.summary(1)["quoted"], 1)
    page = me.get("/comments").get_data(as_text=True)
    check("  shown on the page", "wants the 5-page site" in page, True)
    # The tally came across from Today with it: the stages were always
    # settable on this page, but where they add up was only ever shown
    # on the one that is gone.
    check("  and the pipeline tally came with it", "Pipeline:" in page, True)
    check("a made-up stage is not stored",
          (me.post("/pipeline/comment/%d" % jane["id"], data={"stage": "hot", "csrf_token": csrf}),
           [e for e in today.queue(1)["entries"] if e["who"] == "Jane Doe"][0]["stage"])[1], None)
    me.post("/pipeline/comment/%d" % jane["id"], data={"stage": "quoted", "csrf_token": csrf})

    # Snoozing, on a comment now. A chat's own snooze is the Messages page's
    # business and is tested in messages_store.test.py.
    sara = [e for e in today.queue(1)["entries"] if e["who"] == "Sara Lee"][0]
    before = today.waiting_count(1)
    me.post("/pipeline/comment/%d" % sara["id"], data={"snooze": "3", "csrf_token": csrf})
    check("snoozing takes them out of Today",
          "Sara Lee" in [e["who"] for e in today.queue(1)["entries"]], False)
    check("  and out of the waiting count", today.waiting_count(1), before - 1)
    me.post("/pipeline/comment/%d" % sara["id"], data={"snooze": "wake", "csrf_token": csrf})
    check("  and Unsnooze brings them back",
          "Sara Lee" in [e["who"] for e in today.queue(1)["entries"]], True)

    other_client = appmod.app.test_client()
    other_client.post("/register", data={"email": "x@example.com", "password": "a-long-enough-pass",
                                         "password_confirm": "a-long-enough-pass", "username": "rowan"})
    other_client.get("/today")
    with other_client.session_transaction() as s2:
        x_csrf = s2.get("csrf_token")
    other_client.post("/pipeline/comment/%d" % jane["id"], data={"stage": "lost", "csrf_token": x_csrf})
    check("another account cannot change it",
          [e for e in today.queue(1)["entries"] if e["who"] == "Jane Doe"][0]["stage"], "quoted")

    print()
    print("drafts know where the relationship stands")
    import replies
    asked = []

    def fake_reply(post_title, author, comment, replies=None, instructions="", relationship=""):
        asked.append(relationship)
        return "ok", None

    appmod.replies.draft_reply = fake_reply
    me.post("/comments/%d/draft" % jane["id"], json={}, headers={"X-CSRF-Token": csrf})
    check("a quoted lead's draft is told it is quoted, with the note",
          "Stage: Quoted" in asked[-1] and "wants the 5-page site" in asked[-1], True)
    with appmod.app.test_request_context():
        from flask import g
        g.user = {"id": 1}
        prompt = replies._prompt("Post", "Jane Doe", "How much?", [], "", pipeline.draft_context("quoted", "~$2k"))
    check("  and it reaches the prompt", "help them decide" in prompt and "~$2k" in prompt, True)

    print()
    print("done from Today stays on Today")
    tom = [i for i in q["entries"] if i["who"] == "Tom Hanks"][0]
    r1 = me.post("/comments/%d/status?next=today" % tom["id"], data={"status": "done", "csrf_token": csrf})
    check("back to the list after it, at that row",
          r1.headers.get("Location"), "/comments#c%d" % tom["id"])
    check("and they are gone from the queue", today.waiting_count(1), 2)

    print()
    print("yours only")
    other = appmod.app.test_client()
    other.post("/register", data={"email": "o@example.com", "password": "a-long-enough-pass",
                                  "password_confirm": "a-long-enough-pass", "username": "willow"})
    theirs = other.get("/comments").get_data(as_text=True)
    check("another account sees only its own examples, none of mine",
          ("These are examples" in theirs, "Jane Doe" in theirs), (True, False))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("one list of comments, one count, and they agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
