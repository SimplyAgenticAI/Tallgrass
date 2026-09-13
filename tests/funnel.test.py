"""The funnel has to say where people actually stopped.

Fifteen signups and nobody paying, with only "made an account" and "captured a
post" on record. A funnel that miscounts is worse than none, because it points
the next fix at the wrong step. So these tests walk a real account through the
real routes and insist each step lands once, in order, and that the numbers
cannot contradict themselves — more people capturing than connecting, or the
owner's own testing counted as a customer.

Run: python tests/funnel.test.py
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
        "email": email,
        "password": "a-long-enough-pass",
        "password_confirm": "a-long-enough-pass",
        "username": username,
    })


def post(n, likes):
    return {
        "fb_post_id": "p%d" % n,
        "body": "post number %d" % n,
        "author_name": "Author %d" % n,
        "post_type": "text",
        "posted_at": "2026-08-01T00:00:00",
        "likes": likes, "comments": 0, "shares": 0,
        "engagement_read": 1,
    }


def step(report, key):
    return [s for s in report["steps"] if s["key"] == key][0]


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import funnel
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    owner = appmod.app.test_client()
    sign_up(owner, "owner@example.com", "meadowlark")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'owner@example.com'")
        owner_id = conn.execute(
            "SELECT id FROM users WHERE email = 'owner@example.com'").fetchone()[0]

    print("a new account is a signup and nothing more")
    newbie = appmod.app.test_client()
    sign_up(newbie, "newbie@example.com", "birchwood")
    with newbie.session_transaction() as s:
        key = s["fresh_api_key"]
    with db.get_db() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE email = 'newbie@example.com'").fetchone()[0]
    r = funnel.report()
    check("one signup, the owner is not a customer", step(r, "signup")["count"], 1)
    check("nobody has gone to install", step(r, "store_click")["count"], 0)
    check("the leak is signup to install", r["leak"]["from"], "Signed up")

    print()
    print("the install button is counted on its way out")
    newbie.get("/")                       # sample data only: no outlier of theirs
    check("sample breakouts are not their outlier",
          step(funnel.report(), "outlier_seen")["count"], 0)
    response = newbie.get("/go/store")
    check("it redirects", response.status_code, 302)
    check("  to the store", response.headers["Location"], appmod.EXTENSION_STORE_URL)
    check("the click is recorded", step(funnel.report(), "store_click")["count"], 1)
    signed_out = appmod.app.test_client().get("/go/store")
    check("a signed-out click still reaches the store", signed_out.status_code, 302)
    # Tests run as a local dashboard, which has no store button to render, so
    # the hosted template is checked at the source.
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "templates", "_install_steps.html"),
              encoding="utf-8") as handle:
        steps_html = handle.read()
    check("the store button goes through it", "url_for('go_store')" in steps_html, True)

    print()
    print("the extension connecting, capturing, and scoring")
    response = newbie.post("/api/extension/key",
                           headers={"X-Tallgrass-Extension": "1", "X-Outlier-Key": key})
    check("key handshake ok", response.status_code, 200)
    check("connected is recorded", step(funnel.report(), "connected")["count"], 1)

    # Twelve ordinary posts and one that did twenty times better.
    posts = [post(n, 10) for n in range(12)] + [post(99, 200)]
    response = newbie.post("/api/capture", json={
        "source": {"fb_id": "group:g", "kind": "group", "name": "A Group"},
        "posts": posts}, headers={"X-Outlier-Key": key})
    check("capture accepted", response.status_code, 200)
    check("first capture is recorded", step(funnel.report(), "first_capture")["count"], 1)

    newbie.get("/")
    r = funnel.report()
    check("their own breakout is an outlier seen", step(r, "outlier_seen")["count"], 1)
    check("no activation leak left", r["leak"], None)
    check("a recorded step has a time", step(r, "connected")["median"], "<1h")

    print()
    print("first time only")
    with db.get_db() as conn:
        conn.execute("UPDATE funnel_events SET first_at = '2026-01-01 00:00:00' "
                     "WHERE user_id = ? AND step = 'store_click'", (uid,))
    funnel._recorded.clear()              # as a fresh process would be
    newbie.get("/go/store")
    with db.get_db() as conn:
        rows = conn.execute("SELECT first_at FROM funnel_events "
                            "WHERE user_id = ? AND step = 'store_click'", (uid,)).fetchall()
    check("one row", len(rows), 1)
    check("  keeping the first time", rows[0][0], "2026-01-01 00:00:00")

    print()
    print("buying is its own chain")
    newbie.get("/pricing")
    r = funnel.report()
    check("pricing view recorded", step(r, "pricing_view")["count"], 1)
    check("not a checkout", step(r, "checkout")["count"], 0)
    check("per-account table shows both chains",
          r["furthest"][uid],
          funnel.STEPS[4][1] + " · Opened pricing")

    browser = appmod.app.test_client()
    sign_up(browser, "browser@example.com", "willow")
    browser.get("/pricing")
    r = funnel.report()
    with db.get_db() as conn:
        bid = conn.execute(
            "SELECT id FROM users WHERE email = 'browser@example.com'").fetchone()[0]
    check("opening pricing does not imply installing",
          step(r, "store_click")["count"], 1)
    check("  but does count as a pricing view", step(r, "pricing_view")["count"], 2)
    check("  and says so per account", r["furthest"][bid],
          "Signed up · Opened pricing")

    print()
    print("history is recovered, and a later step implies the earlier ones")
    veteran = appmod.app.test_client()
    sign_up(veteran, "veteran@example.com", "oakley")
    with db.get_db() as conn:
        vid = conn.execute(
            "SELECT id FROM users WHERE email = 'veteran@example.com'").fetchone()[0]
        sid = conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                           "VALUES (?, 'group:old', 'group', 'Old')", (vid,)).lastrowid
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, likes, captured_at, "
            "is_demo, item_type) VALUES (?, 'old-1', ?, 5, '2026-08-20 10:00:00', 0, 'post')",
            (vid, sid))
        conn.execute("INSERT INTO users (email, password_hash, plan, stripe_subscription_id) "
                     "VALUES ('payer@example.com', 'x', 'pro', 'sub_1')")
        conn.execute("DELETE FROM funnel_events WHERE user_id = ?", (vid,))
    db.set_setting(funnel.BACKFILLED_KEY, "")
    funnel.backfill_once()
    r = funnel.report()
    check("the old capture is recovered", step(r, "first_capture")["count"], 2)
    check("  which proves a connection", step(r, "connected")["count"], 2)
    check("  and an install", step(r, "store_click")["count"], 2)
    check("  but no outlier was seen", step(r, "outlier_seen")["count"], 1)
    check("a paying account is recovered", step(r, "paid")["count"], 1)
    check("  implying checkout", step(r, "checkout")["count"], 1)
    check("never more capturing than connecting",
          step(r, "first_capture")["count"] <= step(r, "connected")["count"], True)
    flagged = funnel.backfill_once()
    check("the backfill runs once", flagged, 0)

    print()
    print("the owner stays out, and the page renders")
    owner.get("/go/store")
    check("owner clicks are not counted", step(funnel.report(), "store_click")["count"], 2)
    with db.get_db() as conn:
        check("  though they are stored", conn.execute(
            "SELECT COUNT(*) FROM funnel_events WHERE user_id = ?", (owner_id,)
        ).fetchone()[0] >= 1, True)
    page = owner.get("/admin")
    body = page.get_data(as_text=True)
    check("admin renders", page.status_code, 200)
    check("  with the funnel", "Biggest leak" in body, True)
    check("  and how far each account got", "Got to" in body, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the funnel counts what happened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
