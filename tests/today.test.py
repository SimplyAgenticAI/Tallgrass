"""Today: one queue of everyone waiting, and a count that agrees with it.

The queue is only useful if it holds exactly the people still waiting —
unanswered comments and chats where they spoke last — with likely
opportunities first, and never your own comments, answered ones, or chats set
aside. The count on the navigation and the extension icon must be the same
number the page shows.

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
    me.get("/today")
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
        csrf = s.get("csrf_token")
    headers = {"X-Outlier-Key": key}

    print("a new account")
    first = me.get("/today").get_data(as_text=True)
    check("the page shows labelled examples", "These are examples" in first, True)
    check("  and no red count for them", 'class="nav-count"' in first, False)

    body = me.post("/api/comments", headers=headers, json={
        "post": {"key": "p:1", "title": "New website packages"},
        "comments": [
            {"key": "c:1", "author": "Jane Doe", "text": "How much for the full package?", "verdict": "unanswered"},
            {"key": "c:2", "author": "Tom Hanks", "text": "Love this", "verdict": "unanswered"},
            {"key": "c:3", "author": "Ana Ruiz", "text": "Thanks!", "verdict": "answered"},
            {"key": "c:4", "author": "Jeff Randle", "text": "Thanks all", "verdict": "yours", "mine": True},
            {"key": "c:5", "author": "Sara Lee", "text": "Is this for real?", "verdict": "unknown",
             "hidden_replies": 1},
        ]}).get_json()
    check("saving comments reports everyone waiting, for the icon", body.get("waiting_total"), 3)
    body = me.post("/api/messages/threads", headers=headers, json={"threads": [
        {"key": "t:1", "name": "Lee Chan", "last_from": "them", "last_at": ago(1),
         "signal": "opportunity", "last_hash": "a", "url": "https://www.facebook.com/messages/t/1/"},
        {"key": "t:2", "name": "Mark Twain", "last_from": "me", "last_at": ago(2), "last_hash": "b"},
        {"key": "t:3", "name": "Old Friend", "last_from": "them", "last_at": ago(30), "last_hash": "c"},
    ]}).get_json()
    check("  and so does saving chats", body.get("waiting_total"), 5)

    print()
    print("the queue")
    q = today.queue(1)
    names = [i["who"] for i in q["entries"]]
    check("everyone waiting, nobody else", sorted(names),
          sorted(["Jane Doe", "Tom Hanks", "Sara Lee", "Lee Chan", "Old Friend"]))
    check("opportunities first, from comments and chats alike", set(names[:2]), {"Jane Doe", "Lee Chan"})
    check("  then questions", names[2], "Sara Lee")
    check("the count agrees with the list", today.waiting_count(1), len(q["entries"]))
    check("  and splits by kind", (q["comments"], q["messages"], q["opportunities"]), (3, 2, 2))

    html = me.get("/today").get_data(as_text=True)
    check("the page lists them", all(n in html for n in ("Jane Doe", "Lee Chan", "Old Friend")), True)
    check("comments can be drafted from here", 'data-suggest="' in html, True)
    check("the nav shows the count", 'class="nav-count"' in html and ">5</span>" in html, True)

    print()
    print("done from Today stays on Today")
    tom = [i for i in q["entries"] if i["who"] == "Tom Hanks"][0]
    friend = [i for i in q["entries"] if i["who"] == "Old Friend"][0]
    r1 = me.post("/comments/%d/status?next=today" % tom["id"], data={"status": "done", "csrf_token": csrf})
    r2 = me.post("/messages/%d/status?next=today" % friend["id"], data={"status": "done", "csrf_token": csrf})
    check("back to Today after each", [r1.headers.get("Location"), r2.headers.get("Location")],
          ["/today", "/today"])
    check("and both are gone from the queue", today.waiting_count(1), 3)

    print()
    print("yours only")
    other = appmod.app.test_client()
    other.post("/register", data={"email": "o@example.com", "password": "a-long-enough-pass",
                                  "password_confirm": "a-long-enough-pass", "username": "willow"})
    theirs = other.get("/today").get_data(as_text=True)
    check("another account sees only its own examples, none of mine",
          ("These are examples" in theirs, "Jane Doe" in theirs, "Lee Chan" in theirs),
          (True, False, False))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("one queue, one count, and they agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
