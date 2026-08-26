"""The things that cost money or lose data.

Three blindspots found by scanning rather than by anything failing: nothing
metered AI generation, nothing copied the database, and nothing stopped the
server fetching a link into its own network. None of them would have announced
themselves — the first sign of each would have been a bill, an empty database,
or a breach.

The backup tests matter most, because a backup system that is quietly broken
is worse than none: you believe you are covered.

Run: python tests/safety.test.py
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
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-the-owners-key"

    import db
    import auth
    import billing
    import backup
    import app as appmod
    from flask import session

    logging.disable(logging.INFO)
    db.init_db()
    owner, _ = auth.create_user("owner@example.com", "a-long-enough-pass", "birchwood")
    member, _ = auth.create_user("member@example.com", "a-long-enough-pass", "fernlake")

    print("only calls the OWNER pays for are metered")
    with appmod.app.test_request_context("/"):
        session["user_id"] = member["id"]
        user = auth.current_user()
        # A user spending their own money is nobody else's problem.
        check("their own key is never metered",
              billing.ai_allowed(user, "saved")[0], True)
        check("the owner's key starts allowed",
              billing.ai_allowed(user, "environment")[0], True)

        for _ in range(billing.AI_LIMITS["free"]):
            db.record_ai_call(user["id"], "graphic")

        allowed, reason = billing.ai_allowed(user, "environment")
        check("free stops at its cap", allowed, False)
        check("  and says what to do about it", "own API key" in reason, True)
        check("their own key STILL is not metered",
              billing.ai_allowed(user, "saved")[0], True)

    # Pro gets a bigger ceiling, not an infinite one. In its own request
    # context: current_user() caches on `g`, so an upgrade applied mid-request
    # is not re-read until the next one — which is correct, and would make
    # this assertion test the cache rather than the limit.
    billing.apply_subscription(member["id"], plan="pro",
                               subscription_status="active")
    with appmod.app.test_request_context("/"):
        session["user_id"] = member["id"]
        upgraded = auth.current_user()
        check("upgrading lifts it",
              billing.ai_allowed(upgraded, "environment")[0], True)
        check("  but Pro is a ceiling, not infinity",
              billing.AI_LIMITS["pro"] > billing.AI_LIMITS["free"], True)

    with appmod.app.test_request_context("/"):
        session["user_id"] = owner["id"]
        check("the instance owner is never metered",
              billing.ai_allowed(auth.current_user(), "environment")[0], True)

    print()
    print("usage is recorded, so abuse is visible before the bill")
    summary = db.ai_usage_summary()
    check("the spender is listed", summary[0]["email"], "member@example.com")
    check("with their count", summary[0]["calls"], billing.AI_LIMITS["free"])

    print()
    print("the database is copied, and the copies are real")
    for _ in range(3):
        path, error = backup.run()
        check("a snapshot is written", error, None)
        check("  and is not empty", os.path.getsize(path) > 0, True)

    print()
    print("retention keeps the NEWEST, not whatever sorts last")
    # The bug this pins: the stamp is second-resolution, so a second snapshot
    # in the same second gets a "-1" suffix — and "-1.db" sorts BEFORE ".db".
    # Ordering by name made prune delete the file it had just written.
    for _ in range(12):
        path, error = backup.run()
        check("rapid snapshot %s" % os.path.basename(path or ""),
              error is None and os.path.exists(path), True)

    kept = backup.listing()
    check("exactly KEEP are retained", len(kept), backup.KEEP)
    check("every retained file exists and is non-empty",
          all(k["bytes"] > 0 for k in kept), True)
    check("latest() agrees with the listing",
          os.path.basename(backup.latest()), kept[0]["name"])

    print()
    print("a snapshot can actually be opened")
    # A backup nobody has opened is a rumour.
    import sqlite3
    conn = sqlite3.connect(backup.latest())
    try:
        rows = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()
    check("it contains the accounts", rows, 2)

    print()
    print("only an admin can take or read one")
    boss = appmod.app.test_client()
    with boss.session_transaction() as s:
        s["user_id"] = owner["id"]
        s["csrf_token"] = "t"
    stranger = appmod.app.test_client()
    with stranger.session_transaction() as s:
        s["user_id"] = member["id"]
        s["csrf_token"] = "t"

    check("the owner may back up",
          boss.post("/api/admin/backup", headers={"X-CSRF-Token": "t"}).status_code, 200)
    check("a member may not",
          stranger.post("/api/admin/backup", headers={"X-CSRF-Token": "t"}).status_code, 403)

    name = backup.listing()[0]["name"]
    check("the owner may download", boss.get("/admin/backup/" + name).status_code, 200)
    check("a member may not", stranger.get("/admin/backup/" + name).status_code, 403)

    print()
    print("the backup path cannot be walked out of")
    for bad in ("../outlier.db", "..\\outlier.db", "/etc/passwd", ".hidden", ""):
        check("refuses %r" % bad, backup.path_for(bad), None)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the money is capped and the data is copied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
