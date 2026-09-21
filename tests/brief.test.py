"""The weekly brief — the one email for people already using the product.

What must hold:

  off       it ships switched off, so a deploy cannot start mailing anyone
  weekly    one per person per week, however many sweeps run
  honest    a multiple is only printed where there is a real baseline; demo
            posts never count; nobody idle for a month is mailed
  opt-out   honoured, like every other automatic email
  content   copy edited to drop {summary} still carries the summary

Run: python tests/brief.test.py
"""
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []
SENT = []
BASE = "https://tallgrassapp.com/"


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
    os.environ["SMTP_USER"] = "sender@example.com"
    os.environ["SMTP_PASS"] = "app-password"
    os.environ["OUTREACH"] = "on"

    import db
    import auth
    import mailer
    import outreach
    import brief
    import app as appmod  # noqa: F401 - registers app for app_store_url

    logging.disable(logging.INFO)
    db.init_db()

    def fake_send(to, subject, body, headers=None):
        SENT.append({"to": to, "subject": subject, "body": body})
        return True, None
    mailer.send = fake_send

    def briefs(to=None):
        return [m for m in SENT if "Tallgrass week" in m["subject"]
                and (to is None or m["to"] == to)]

    def make_user(email, name, days_old=5):
        user, _ = auth.create_user(email, "a-long-enough-pass", name)
        with db.get_db() as conn:
            conn.execute("UPDATE users SET created_at = datetime('now', ?) "
                         "WHERE id = ?", ("-%d days" % days_old, user["id"]))
        return user

    def add_posts(user_id, group, likes, seen="-0 days", demo=0):
        with db.get_db() as conn:
            sid = conn.execute(
                "INSERT INTO sources (user_id, fb_id, kind, name) "
                "VALUES (?, ?, 'group', ?)",
                (user_id, "group:%s:%s" % (user_id, group), group)).lastrowid
            ids = []
            for i, n in enumerate(likes):
                ids.append(conn.execute(
                    "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
                    "likes, posted_at, captured_at, updated_at, is_demo, "
                    "item_type, engagement_read) VALUES "
                    "(?, ?, ?, ?, ?, datetime('now', '-1 days'), "
                    "datetime('now', ?), datetime('now', ?), ?, 'post', 1)",
                    (user_id, "%s-%s-%d" % (user_id, group, i), sid,
                     "Post number %d about sourdough starters" % i, n,
                     seen, seen, demo)).lastrowid)
        return ids

    print("ships switched off")
    active = make_user("active@example.com", "activeone")
    ids = add_posts(active["id"], "Bread Club", [10] * 9 + [80])
    check("the brief's own switch is off by default",
          outreach.kind_on(outreach.BRIEF), False)
    outreach.sweep(BASE)
    check("so a sweep sends no brief", len(briefs()), 0)

    print()
    print("an active account gets its top post, with a real multiple")
    outreach.set_kind_enabled(outreach.BRIEF, True)
    outreach.sweep(BASE)
    mine = briefs("active@example.com")
    check("one brief went out", len(mine), 1)
    body = mine[0]["body"] if mine else ""
    check("it names the breakout multiple", "8.0×" in body, True)
    check("and the group", "Bread Club" in body, True)
    check("and links the post", ("%spost/%d" % (BASE, ids[-1])) in body, True)
    check("the headline is in the subject",
          "8.0× in Bread Club" in (mine[0]["subject"] if mine else ""), True)
    check("the footer says what unsubscribing stops",
          "weekly brief" in body.split("—")[-1], True)

    print()
    print("once a week, however many sweeps run")
    outreach.sweep(BASE)
    outreach.sweep(BASE)
    check("still one", len(briefs("active@example.com")), 1)
    check("the admin count reads 1",
          [e["sent"] for e in outreach.status()["emails"]
           if e["kind"] == outreach.BRIEF], [1])

    print()
    print("never a multiple without a baseline")
    thin = make_user("thin@example.com", "thinone")
    add_posts(thin["id"], "Tiny Group", [3, 40, 5])
    facts = brief.compose(thin["id"], BASE)
    check("a brief is still written", bool(facts), True)
    check("with no × anywhere in it", "×" in (facts or {}).get("summary", "x×"), False)
    check("and it says the week was quiet",
          "nothing stood clear" in (facts or {}).get("summary", ""), True)

    print()
    print("who is left alone")
    demo = make_user("demo@example.com", "demoone")
    add_posts(demo["id"], "Sample", [10] * 9 + [90], demo=1)
    fresh = make_user("fresh@example.com", "freshone", days_old=0)
    add_posts(fresh["id"], "New Group", [10] * 9 + [90])
    gone = make_user("gone@example.com", "goneone")
    add_posts(gone["id"], "Old Group", [10] * 9 + [90], seen="-40 days")
    opted = make_user("opted@example.com", "optedone")
    add_posts(opted["id"], "Their Group", [10] * 9 + [90])
    db.set_email_optout(opted["id"], True)
    due = {u["email"] for u in outreach.brief_due()}
    check("sample posts alone earn nothing", "demo@example.com" in due, False)
    check("nobody in their first days", "fresh@example.com" in due, False)
    check("nobody idle for a month", "gone@example.com" in due, False)
    check("  and compose agrees", brief.compose(gone["id"], BASE), None)
    check("nobody who opted out", "opted@example.com" in due, False)
    check("the thin account is due", "thin@example.com" in due, True)

    print()
    print("stale numbers get a rescan prompt instead of a top list")
    stale = make_user("stale@example.com", "staleone")
    add_posts(stale["id"], "Quiet Group", [10] * 9 + [90], seen="-10 days")
    facts = brief.compose(stale["id"], BASE)
    check("it asks for a scan", "haven't scanned" in (facts or {}).get("summary", ""), True)
    check("and lists no old breakout as this week's",
          "×" in (facts or {}).get("summary", "×"), False)

    print()
    print("edited copy cannot drop the content")
    outreach.set_template(outreach.BRIEF, "Your Tallgrass week", "Hi there.")
    ok, _ = outreach.send_test_brief(dict(active), BASE)
    check("a test sends even though it was already sent this week", ok, True)
    check("it is marked as a test", SENT[-1]["subject"].startswith("[Test]"), True)
    check("and the summary came back", "Bread Club" in SENT[-1]["body"], True)
    outreach.set_kind_enabled(outreach.BRIEF, False)
    ok, _ = outreach.send_test_brief(dict(active), BASE)
    check("tests still send with the brief switched off", ok, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("a weekly brief, once a week, only true numbers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
