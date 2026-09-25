"""The walkthrough: what it says, to whom, and when it stops.

  never lies    a step is only offered while its job is undone — nobody is
                walked to an extension they already installed
  points at
  real things   every target is a selector built from a live route, and every
                route it names exists
  runs once     the page asks for it only until it has been seen; Settings can
                ask for it again
  private       one account's state is never another's, and it needs a session

Run: python tests/guide.test.py
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


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import auth
    import guide
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("walk@example.com", "a-long-enough-pass", "walker")
    uid = user["id"]
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = "known-token"
    CSRF = {"X-CSRF-Token": "known-token"}

    def keys():
        return [s["key"] for s in client.get("/api/guide").get_json()["steps"]]

    print("a brand new account")
    state = client.get("/api/guide").get_json()
    check("it runs unasked", state["run"], True)
    check("the feed comes first, then the extension",
          [s["key"] for s in state["steps"]][:2], ["feed", "extension"])
    check("no groups step before anything is captured", "groups" in keys(), False)
    check("no today step before any comments", "today" in keys(), False)
    check("every step has words and a target",
          all(s["title"] and s["body"] and s["target"] for s in state["steps"]), True)

    print()
    print("every target names a route that exists")
    with appmod.app.test_request_context("/"):
        urls = appmod._guide_urls()
    for name, path in urls.items():
        check("  %s -> %s" % (name, path),
              client.get(path).status_code in (200, 302), True)
    check("targets are selectors on those routes",
          all(s["target"].startswith('a[href="') for s in state["steps"]), True)

    print()
    print("what it stops saying once the work is done")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET api_key_prefix = 'abcd1234' WHERE id = ?", (uid,))
        sid = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) VALUES (?, 'g1', 'group', 'G')",
            (uid,)).lastrowid
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, likes, posted_at, is_demo, "
            "item_type, engagement_read) VALUES (?, 'p1', ?, 9, datetime('now'), 0, 'post', 1)",
            (uid, sid))
    after = keys()
    check("the extension step is gone", "extension" in after, False)
    check("and the groups step has arrived", "groups" in after, True)
    check("write is still offered, nothing has been remixed", "write" in after, True)
    with db.get_db() as conn:
        conn.execute("INSERT INTO remixes (user_id, post_id, output) VALUES (?, 1, 'x')", (uid,))
    check("until something has", "write" in keys(), False)
    check("the playbook is always last", keys()[-1], "playbook")

    print()
    print("seen once, then only when asked")
    check("the page is told to run it", appmod.app.test_request_context and
          client.get("/settings").get_data(as_text=True).count('data-guide="1"'), 1)
    check("a post without a token is refused",
          client.post("/api/guide", json={}).status_code, 403)
    check("  and nothing was recorded", guide.seen(uid), False)
    check("marking it seen answers ok",
          client.post("/api/guide", json={}, headers=CSRF).get_json()["ok"], True)
    check("  and it is recorded", guide.seen(uid), True)
    check("the page no longer runs it",
          'data-guide="0"' in client.get("/settings").get_data(as_text=True), True)
    check("  but the steps are still there to ask for",
          len(client.get("/api/guide").get_json()["steps"]) > 0, True)
    client.post("/api/guide", json={"again": True}, headers=CSRF)
    check("Settings can put it back", guide.seen(uid), False)

    print()
    print("it belongs to one account")
    other, _ = auth.create_user("other@example.com", "a-long-enough-pass", "otherone")
    check("a second account starts fresh", guide.seen(other["id"]), False)
    anon = appmod.app.test_client()
    check("and there is nothing to see signed out",
          anon.get("/api/guide").status_code in (302, 401), True)
    check("nor anything to mark",
          anon.post("/api/guide", json={}).status_code in (302, 401, 403), True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("a walkthrough that points at real things and knows what you've done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
