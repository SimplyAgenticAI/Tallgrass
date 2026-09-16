"""Messenger chats: the right two lists, done that stays done, and no words kept.

The Messages page is only worth anything if it is right about who is waiting
and never keeps what anybody wrote. So: a chat they spoke last in is waiting;
one you spoke last in shows as gone quiet only after a few days; Done holds
until a genuinely new message arrives; nothing from one account reaches
another; and no column anywhere holds message text.

Run: python tests/messages_store.test.py
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


def sign_up(client, email, username):
    return client.post("/register", data={
        "email": email, "password": "a-long-enough-pass",
        "password_confirm": "a-long-enough-pass", "username": username})


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def chats(jane_hash="h1"):
    return {"threads": [
        {"key": "t:1", "name": "Jane Doe", "url": "https://www.facebook.com/messages/t/1/",
         "last_from": "them", "last_at": ago(0.1), "signal": "opportunity", "last_hash": jane_hash},
        {"key": "t:2", "name": "Mark Twain", "url": "https://www.facebook.com/messages/t/2/",
         "last_from": "me", "last_at": ago(5), "last_hash": "h2"},
        {"key": "t:3", "name": "Sara Lee", "last_from": "me", "last_at": ago(1), "last_hash": "h3"},
        {"key": "t:4", "name": "Tom Hanks", "last_from": "them", "last_at": ago(2),
         "unread": True, "last_hash": "h4"},
        {"key": "t:5", "name": "No Time", "last_from": "me", "last_at": None, "last_hash": "h5"},
        {"key": "t:6", "name": "Bad", "last_from": "someone", "last_hash": "h6"},
    ]}


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import messages
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    me = appmod.app.test_client()
    sign_up(me, "me@example.com", "birchwood")
    me.get("/messages")
    with me.session_transaction() as s:
        key = s["fresh_api_key"]
        csrf = s.get("csrf_token")

    def save(payload, api_key=key):
        return me.post("/api/messages/threads", json=payload, headers={"X-Outlier-Key": api_key})

    print("the two lists")
    check("needs a key", save(chats(), api_key="olk_wrong").status_code, 401)
    body = save(chats()).get_json()
    check("valid chats saved, a bad one skipped", body["saved"], 5)
    inbox = messages.inbox(1)
    check("waiting: they spoke last", [t["name"] for t in inbox["waiting"]], ["Jane Doe", "Tom Hanks"])
    check("  opportunity first", inbox["waiting"][0]["signal"], "opportunity")
    check("gone quiet: only after a few days", [t["name"] for t in inbox["quiet"]], ["Mark Twain"])
    check("a chat with no readable time is never called quiet",
          "No Time" in [t["name"] for t in inbox["quiet"]], False)
    check("replied: you spoke last, recently, or at a time nobody could read",
          sorted(t["name"] for t in inbox["replied"]), ["No Time", "Sara Lee"])
    check("the response counts them",
          (body["waiting"], body["replied"], body["quiet"], body["opportunities"]), (2, 2, 1, 1))

    print()
    print("a rescan never doubles anything")

    def rows():
        with db.get_db() as conn:
            return conn.execute("SELECT COUNT(*) FROM message_threads WHERE user_id = 1").fetchone()[0]

    save(chats())
    save(chats())
    check("the same chat list three times is five chats", rows(), 5)
    live_update = {"threads": [{"key": "t:1", "name": "Jane Doe", "last_from": "them",
                                "last_at": ago(0), "last_hash": "h1"}]}
    save(live_update)
    check("the open-chat watcher updates the same chat, not a new one", rows(), 5)

    print()
    print("a chat moves on its own")
    live = {"threads": [{"key": "t:4", "name": "Tom Hanks", "last_from": "me",
                         "last_at": ago(0), "last_hash": "me-reply"}]}
    save(live)
    lists = messages.inbox(1)
    check("answering it moves it to replied, no Done needed",
          ("Tom Hanks" in [t["name"] for t in lists["replied"]],
           "Tom Hanks" in [t["name"] for t in lists["waiting"]]), (True, False))
    live["threads"][0].update(last_from="them", last_hash="their-answer")
    save(live)
    check("their answer moves it back to waiting",
          "Tom Hanks" in [t["name"] for t in messages.inbox(1)["waiting"]], True)

    print()
    print("done holds until the chat moves")
    jane = inbox["waiting"][0]
    me.post("/messages/%d/status" % jane["id"], data={"status": "done", "csrf_token": csrf})
    check("done hides it", [t["name"] for t in messages.inbox(1)["waiting"]], ["Tom Hanks"])
    save(chats())
    check("the same last message keeps it done",
          [t["name"] for t in messages.inbox(1)["waiting"]], ["Tom Hanks"])
    save(chats(jane_hash="h-new"))
    check("a new message brings it back",
          [t["name"] for t in messages.inbox(1)["waiting"]], ["Jane Doe", "Tom Hanks"])

    print()
    print("yours only, and no words")
    other = appmod.app.test_client()
    sign_up(other, "other@example.com", "willow")
    other.get("/messages")
    with other.session_transaction() as s:
        other_csrf = s.get("csrf_token")
    check("another account sees none of it",
          "Jane Doe" in other.get("/messages").get_data(as_text=True), False)
    other.post("/messages/%d/status" % jane["id"], data={"status": "done", "csrf_token": other_csrf})
    check("and cannot change it", messages.inbox(1)["waiting"][0]["status"], "open")
    with db.get_db() as conn:
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(message_threads)")]
    check("no column could hold message text",
          [c for c in columns if c in ("text", "body", "snippet", "message", "last_message")], [])

    print()
    print("drafting the next message")
    asked = []

    def fake(name, msgs, instructions=""):
        asked.append((name, msgs))
        return "Hi %s! The full package is [price] — want me to send details?" % name.split(" ")[0], None

    appmod.replies.draft_message = fake
    convo = {"name": "Jane Doe", "messages": [
        {"from": "them", "text": "How much for the full website package?"}]}
    check("needs a key", me.post("/api/messages/draft", json=convo,
                                 headers={"X-Outlier-Key": "olk_wrong"}).status_code, 401)
    result = me.post("/api/messages/draft", json=convo, headers={"X-Outlier-Key": key}).get_json()
    check("a draft comes back", result.get("reply"),
          "Hi Jane! The full package is [price] — want me to send details?")
    check("  written from the conversation sent", asked[-1][1][0]["text"],
          "How much for the full website package?")
    with db.get_db() as conn:
        dump = "\n".join(conn.iterdump())
    check("  and the conversation is stored nowhere", "full website package" in dump, False)

    print()
    print("the page")
    html = me.get("/messages").get_data(as_text=True)
    check("renders all three lists",
          all(s in html for s in ("Waiting on you", "Replied — waiting on them", "Gone quiet")), True)
    check("marks the opportunity", "Opportunity" in html, True)
    check("links to the chat", "https://www.facebook.com/messages/t/1/" in html, True)
    check("nav has Messages", ">Messages</a>" in html, True)
    me.post("/messages/forget", data={"csrf_token": csrf})
    check("forget clears every chat", messages.inbox(1, show_done=True)["waiting"], [])

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the right chats, and nothing anyone wrote")
    return 0


if __name__ == "__main__":
    sys.exit(main())
