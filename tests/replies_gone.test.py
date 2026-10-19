"""Answering people is not this product's job, and must not creep back.

Comments, DMs and the Today page that merged them are removed. The reasoning,
kept here because it is what decides the next feature request:

Facebook already carries replying. It has the notifications, the apps and the
inbox, it delivers in real time where this scrapes, and it is free. A second
place to answer somebody was a second place to check, always a little behind
the first — and when the two disagreed, the trust that went was the trust the
SCORING had earned. What is left is the one thing nothing else does: what a
post did against the median of its own group.

This file holds the line in two directions.

Off, in the dashboard: no tab, no page, no badge, no reply queue in the
extension's panel, and no sample comments seeded for pages that are gone.

Still on, at the door: an extension already installed goes on posting comments
and chats until a new version reaches it. /api/comments and
/api/messages/threads must keep accepting and storing, because a 404 there is a
broken capture and an error in somebody's panel, not a retired feature. They
come out in a later pass, after the extension stops sending.

Run: python tests/replies_gone.test.py
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
    import comments
    import messages
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    me = appmod.app.test_client()
    me.post("/register", data={"email": "me@example.com",
                               "password": "a-long-enough-pass",
                               "password_confirm": "a-long-enough-pass",
                               "username": "birchwood"})
    page = me.get("/").get_data(as_text=True)
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
    headers = {"X-Outlier-Key": key}

    print("the app opens on the Feed")
    check("signing in lands on the feed, which renders", me.get("/").status_code, 200)
    nav = page.split('<nav class="topnav">', 1)[1].split("</nav>", 1)[0]
    check("Feed is the first tab",
          nav.index(">Feed</a>") < nav.index(">Groups</a>"), True)
    for label in ("Today", "Comments", "Messages"):
        check("  no %s tab anywhere in the nav" % label, ">" + label in nav, False)
    check("  and no waiting badge", "nav-count" in page, False)

    print()
    print("the pages are gone, and redirect rather than 404")
    # Bookmarks, and forms in a page somebody still has open.
    for path in ("/today", "/comments", "/messages"):
        r = me.get(path)
        check("GET %s -> the feed" % path,
              (r.status_code, r.headers.get("Location")), (302, "/"))

    print()
    print("nothing in the dashboard asks for a draft")
    # These were the Comments and Messages pages' own buttons, and they are
    # gone with them.
    #
    # Asserted against the url map rather than by posting: a POST without a
    # token is refused by the CSRF guard before routing happens, so every one
    # of these came back 403 whether the route existed or not — a check that
    # would have passed just as happily with the routes still in place.
    rules = {str(r) for r in appmod.app.url_map.iter_rules()}
    for rule in ("/comments/<int:comment_id>/status",
                 "/comments/<int:comment_id>/draft",
                 "/comments/post/<int:post_id>/forget",
                 "/messages/<int:thread_id>/status",
                 "/messages/forget"):
        check("%s is no longer a route" % rule, rule in rules, False)
    # And the walkthrough does not teach a page that is gone.
    steps = me.get("/api/guide").get_json().get("steps") or []
    check("  the walkthrough has no step for answering people",
          [s for s in steps if s["key"] in ("today", "comments", "messages")], [])

    print()
    print("the panel's reply queue is empty, without waiting for a release")
    # The extension asks every minute. Answering with nothing is what empties
    # its queue and clears the icon badge on builds already installed.
    panel = me.post("/api/today", headers=headers).get_json()
    check("the shape an older panel reads is unchanged",
          sorted(panel.keys()), ["entries", "messenger_ai", "ok", "waiting_total"])
    check("  no entries", panel["entries"], [])
    check("  nothing on the badge", panel["waiting_total"], 0)
    check("  and no offer to sort chats with the AI", panel["messenger_ai"], False)

    print()
    print("a new account is not given example comments or chats")
    check("no sample comments seeded", comments.threads_for(1)["posts"], [])
    check("no sample chats seeded", messages.inbox(1)["waiting"], [])
    check("  and the feed's own sample posts are still there, labelled",
          "sample" in page.lower(), True)

    print()
    print("but the door is still open to an extension already installed")
    # This is the half that must NOT be tidied away yet. Until a new extension
    # reaches everybody, builds in the wild keep sending.
    sent = me.post("/api/comments", headers=headers, json={
        "post": {"key": "p:1", "title": "A post of mine",
                 "url": "https://www.facebook.com/groups/1/posts/1/"},
        "comments": [{"key": "c:1", "author": "Jane Doe", "text": "How much?",
                      "verdict": "unanswered"}]})
    check("/api/comments still accepts", sent.status_code, 200)
    check("  and still stores", len(comments.threads_for(1)["posts"]), 1)
    check("  reporting nothing waiting, because nothing shows it",
          sent.get_json().get("waiting_total"), 0)

    chats = me.post("/api/messages/threads", headers=headers, json={"threads": [
        {"key": "t:1", "name": "Lee Chan", "last_from": "them", "last_hash": "a"}]})
    check("/api/messages/threads still accepts", chats.status_code, 200)
    check("  and still stores", len(messages.inbox(1)["waiting"]), 1)

    # None of it reaches a page.
    feed = me.get("/").get_data(as_text=True)
    check("and none of it appears in the app",
          ("Jane Doe" in feed, "Lee Chan" in feed), (False, False))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the app is the outlier finder again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
