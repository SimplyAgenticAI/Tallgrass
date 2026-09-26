"""Runaway guards on capture.

Nothing rate-limited ingest at all. A looping extension, a retry storm or a bad
build could write until the disk filled, and the first symptom would have been
every account's captures failing at once — including the accounts that had done
nothing wrong.

These are guards, not product limits: an order of magnitude above a real scan.
What they must never do is lose a legitimate batch quietly.

  per request   an oversized batch is truncated and the remainder REPORTED
  per hour      a ceiling per account, counted from captures (so re-sends of
                posts already stored count, which is what a retry storm is)
  refused       once nothing may be stored, the answer is a 429 that says why
  honest        the response always says how many were cut, so a short batch is
                never mistaken for a complete one
  normal use    a real-sized scan is untouched

Run: python tests/ingest_guard.test.py
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
    import billing
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("scanner@example.com", "a-long-enough-pass", "scanner")
    uid = user["id"]
    # Pro, so the free post cap is not what is being tested here.
    with db.get_db() as conn:
        conn.execute("UPDATE users SET plan = 'pro' WHERE id = ?", (uid,))
    raw_key, _ = auth.issue_api_key(uid) if hasattr(auth, "issue_api_key") else (None, None)
    if not raw_key:
        raw_key = auth.rotate_api_key(uid) if hasattr(auth, "rotate_api_key") else None
    check("an API key could be issued", bool(raw_key), True)

    client = appmod.app.test_client()

    def send(n, source="g1"):
        return client.post("/api/capture", json={
            "source": {"fb_id": source, "kind": "group", "name": "Group"},
            "posts": [{"fb_post_id": "%s-%d" % (source, i), "body": "A post about bees %d" % i,
                       "likes": 5, "comments": 1, "shares": 0,
                       "posted_at": "2026-09-20 10:00:00"} for i in range(n)],
        }, headers={"X-Outlier-Key": raw_key})

    print("a normal scan is untouched")
    r = send(80)
    body = r.get_json()
    check("it is accepted", r.status_code, 200)
    check("every post is received", body["received"], 80)
    check("nothing was throttled", body["throttled"], 0)

    print()
    print("an oversized batch is cut, not dropped")
    r = send(billing.INGEST_PER_REQUEST + 250, source="g2")
    body = r.get_json()
    check("it still succeeds", r.status_code, 200)
    check("the ceiling is what landed", body["received"], billing.INGEST_PER_REQUEST)
    check("and the remainder is reported", body["throttled"], 250)

    print()
    print("the hourly ceiling")
    used = db.posts_ingested_since(uid, hours=1)
    check("what has arrived is counted", used, 80 + billing.INGEST_PER_REQUEST)
    room, seen = billing.ingest_burst(uid, 500)
    check("there is room left", room, 500)
    check("  and it knows what was used", seen, used)

    # Pretend the account has already sent the hour's worth. Written as capture
    # rows because that is where the count comes from — a retry storm re-sends
    # posts that are already stored, so counting the posts table would miss it.
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO captures (user_id, source_id, post_count, new_count) "
            "VALUES (?, NULL, ?, 0)", (uid, billing.INGEST_PER_HOUR))
    room, _seen = billing.ingest_burst(uid, 100)
    check("no room once the hour is spent", room, 0)

    r = send(50, source="g3")
    body = r.get_json()
    check("a further batch is refused", r.status_code, 429)
    check("  and says what is happening", "repeating" in body["error"], True)
    check("  and nothing was stored", body.get("ok"), False)

    print()
    print("an old storm does not count against today")
    with db.get_db() as conn:
        conn.execute("UPDATE captures SET created_at = datetime('now', '-3 hours') "
                     "WHERE post_count = ?", (billing.INGEST_PER_HOUR,))
    check("the hour has moved on",
          db.posts_ingested_since(uid, hours=1) < billing.INGEST_PER_HOUR, True)
    r = send(20, source="g4")
    check("capture works again", r.status_code, 200)

    print()
    print("the operator can see who holds the most")
    rows = db.biggest_accounts(8)
    check("the account is listed", rows[0]["email"], "scanner@example.com")
    check("  with its post count",
          rows[0]["posts"] >= billing.INGEST_PER_REQUEST, True)
    check("  and an approximate size", rows[0]["approx_bytes"] > 0, True)

    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (uid,))
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/admin").get_data(as_text=True)
    check("and the admin page shows it", "Who is holding the most" in html, True)
    check("  with the hourly ceiling named",
          "{:,}".format(billing.INGEST_PER_HOUR) in html, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("a runaway is stopped and named, a real scan is not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
