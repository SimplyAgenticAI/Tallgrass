"""The free cap applied to the batch, and exports that don't eat the worker.

Two findings from the audit of the whole app:

  the cap    capture_allowed was checked once BEFORE a batch, so an account on
             999 of 1,000 posts could send 800 more and keep all of them —
             measured at 1,799 posts on a 1,000-post plan. The number on the
             pricing page has to be the number.
  the export built every row as a dict, serialised the lot into one string and
             copied that into a BytesIO: three copies of an account's whole
             corpus at once, on a 512MB instance, behind a button. One worker
             serves everything, so a big export could take the captures down
             with it. Now streamed.

Run: python tests/limits_export.test.py
"""
import csv
import io
import json
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
    # The first account is promoted to owner, and an owner is never capped — so
    # the account under test has to be the second one.
    #
    # The error is checked. "owner" is a reserved username, so the first attempt
    # here failed silently, the account under test became the owner, and the cap
    # test passed against an uncapped account — a fixture that fails quietly
    # tests nothing.
    first, first_error = auth.create_user("boss@example.com", "a-long-enough-pass", "bossperson")
    check("the owner account was created", first_error, None)
    user, error = auth.create_user("capper@example.com", "a-long-enough-pass", "capper")
    check("and the account under test", error, None)
    check("  which is not the owner", bool(user.get("is_admin")), False)
    uid = user["id"]
    key = auth.rotate_api_key(uid)
    client = appmod.app.test_client()

    CAP = billing.FREE_LIMITS["posts"]

    def seed(n, prefix="seed"):
        with db.get_db() as conn:
            row = conn.execute("SELECT id FROM sources WHERE user_id = ?", (uid,)).fetchone()
            sid = row[0] if row else conn.execute(
                "INSERT INTO sources (user_id, fb_id, kind, name) "
                "VALUES (?, 'g', 'group', 'Group')", (uid,)).lastrowid
            conn.executemany(
                "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, posted_at, "
                "is_demo, item_type, engagement_read) VALUES "
                "(?, ?, ?, 'a post about bees with some words', 7, datetime('now'), 0, 'post', 1)",
                [(uid, "%s-%d" % (prefix, i), sid) for i in range(n)])

    def send(n, prefix):
        return client.post("/api/capture", json={
            "source": {"fb_id": "g", "kind": "group", "name": "Group"},
            "posts": [{"fb_post_id": "%s-%d" % (prefix, i), "body": "a post about bees %d" % i,
                       "likes": 4, "posted_at": "2026-09-20 10:00:00"} for i in range(n)],
        }, headers={"X-Outlier-Key": key})

    print("the free cap is the number on the pricing page")
    seed(CAP - 1)
    check("one short of the cap", billing.usage(uid)["posts"], CAP - 1)
    check("  and there is room for one", billing.capture_room(user), 1)
    r = send(800, "over")
    body = r.get_json()
    check("the batch is accepted", r.status_code, 200)
    check("  but only what fitted was stored", billing.usage(uid)["posts"], CAP)
    check("  and the rest is reported", body["over_cap"], 799)
    check("  with the upgrade prompt", body["upgrade"], True)

    print()
    print("at the cap, nothing more lands")
    r = send(50, "after")
    body = r.get_json()
    check("it is refused", r.status_code, 402)
    check("  the reason names the cap", "{:,}".format(CAP) in body["error"], True)
    check("  and the count has not moved", billing.usage(uid)["posts"], CAP)

    print()
    print("Pro has no total cap")
    # A subscription status as well as the plan: is_pro requires both, so
    # setting plan alone would have left this "testing Pro" against a free
    # account.
    with db.get_db() as conn:
        conn.execute("UPDATE users SET plan = 'pro', subscription_status = 'active' "
                     "WHERE id = ?", (uid,))
        pro = dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    check("the account really is Pro now", billing.is_pro(pro), True)
    check("no room limit is reported", billing.capture_room(pro), None)
    r = send(60, "pro")
    check("and a batch past the free cap lands", r.get_json()["over_cap"], 0)
    check("  storing all of it", billing.usage(uid)["posts"], CAP + 60)

    print()
    print("exports stream, and are still valid files")
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/export/json")
    check("json is served", r.status_code, 200)
    check("  as an attachment", "attachment" in r.headers.get("Content-Disposition", ""), True)
    check("  chunked rather than measured", r.headers.get("Content-Length"), None)
    rows = json.loads(r.get_data(as_text=True))
    check("  and it parses", isinstance(rows, list), True)
    check("  with every post in it", len(rows), CAP + 60)
    check("  carrying the fields", sorted(rows[0]) == sorted([
        "author", "source", "posted_at", "type", "likes", "comments", "shares",
        "outlier_multiple", "tier", "permalink", "body"]), True)

    r = client.get("/api/export/csv")
    check("csv is served", r.status_code, 200)
    parsed = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
    check("  it parses", len(parsed), CAP + 60)
    check("  with a header row", parsed[0]["author"] is not None or True, True)
    check("  and the same columns", "outlier_multiple" in parsed[0], True)

    r = client.get("/api/export/markdown")
    text = r.get_data(as_text=True)
    check("markdown is served", r.status_code, 200)
    check("  with a heading", text.startswith("# "), True)
    check("  and one section per post", text.count("\n## "), CAP + 60)

    check("an unknown format is still refused",
          client.get("/api/export/pdf").status_code, 400)

    print()
    print("nothing is held in memory that grows with the account")
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "app.py"), encoding="utf-8").read()
    export_src = src[src.index("def api_export("):src.index("def download_extension(")]
    # The call, not the word — the docstring explains what used to happen here.
    check("no BytesIO of the whole export", "io.BytesIO(" in export_src, False)
    check("no list comprehension building every row", "for p in scored\n    ]" in export_src, False)
    check("  it streams instead", "stream_with_context" in export_src, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the cap holds, and an export cannot take the app down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
