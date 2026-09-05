"""Email the product sends on its own.

Fifteen people signed up and heard nothing, because `mailer.send` had exactly
one caller — the password reset. There are now two more: a welcome at signup
and a single nudge to somebody who never captured anything.

Automatic email is the one feature whose failure mode is worse than not
shipping it. Sending twice, sending to somebody who said no, or sending the
moment a deploy lands are each more damaging than silence, so those are what
these tests are mostly about:

  once      the claim is taken BEFORE the send, so two overlapping sweeps
            cannot both decide it is unsent
  retried   but a claim whose send FAILED is given back, or one bad minute at
            the provider costs somebody their only welcome
  never     opting out is honoured everywhere except a password reset, which
  uninvited is asked for
  off       the sweep sends nothing at all unless OUTREACH is on

Run: python tests/outreach.test.py
"""
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []
SENT = []


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
    # Enough for mailer.is_configured() to be true without anything leaving
    # this machine — every send below is captured, never delivered.
    os.environ["SMTP_USER"] = "sender@example.com"
    os.environ["SMTP_PASS"] = "app-password"
    os.environ["OUTREACH"] = "on"

    import db
    import auth
    import mailer
    import outreach
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    # Capture instead of deliver. Returns whatever `outcome` currently says, so
    # a test can make the provider fail on demand.
    outcome = {"ok": True, "error": None}

    def fake_send(to, subject, body, headers=None):
        SENT.append({"to": to, "subject": subject, "body": body,
                     "headers": headers or {}})
        return outcome["ok"], outcome["error"]

    mailer.send = fake_send

    print("signing up says hello, exactly once")
    user, _ = auth.create_user("newbie@example.com", "a-long-enough-pass",
                               "birchwood")
    sent, reason = outreach.welcome(user, "https://tallgrassapp.com/")
    check("the welcome goes out", sent, True)
    check("to them", SENT[-1]["to"], "newbie@example.com")
    check("and it points at the install",
          "capture" in SENT[-1]["body"], True)
    check("and at what they already have",
          "sample" in SENT[-1]["body"].lower(), True)

    before = len(SENT)
    sent, reason = outreach.welcome(user, "https://tallgrassapp.com/")
    check("a second attempt sends nothing", sent, False)
    check("  and says why", reason, "already sent")
    check("  and really did not send", len(SENT), before)

    print()
    print("every message carries a way out")
    # Not decoration. Somebody who cannot find an unsubscribe uses the spam
    # button instead, and a sender reputation is far easier to keep than to
    # repair.
    check("an unsubscribe link is in the body",
          "unsubscribe/" in SENT[0]["body"], True)
    check("and in the headers, where Gmail reads it",
          "List-Unsubscribe" in SENT[0]["headers"], True)

    print()
    print("the opt-out token proves ownership and nothing else")
    token = outreach.unsubscribe_token(user["id"])
    check("it resolves to its own account",
          outreach.user_id_for_token(token), user["id"])
    check("a tampered signature does not",
          outreach.user_id_for_token(token[:-1] + ("a" if token[-1] != "a" else "b")),
          None)
    # The obvious forgery: change whose account it is and keep the signature.
    other_id = user["id"] + 1
    forged = "%d-%s" % (other_id, token.split("-", 1)[1])
    check("nor does swapping the account id",
          outreach.user_id_for_token(forged), None)
    check("nor does nonsense", outreach.user_id_for_token("hello"), None)
    check("nor does nothing at all", outreach.user_id_for_token(""), None)

    print()
    print("a failed send gives the claim back")
    # A provider having a bad minute must not cost somebody their only
    # welcome. The claim is taken before the send precisely so two callers
    # cannot both send — which makes releasing it on failure the other half of
    # that being correct rather than merely safe.
    second, _ = auth.create_user("second@example.com", "a-long-enough-pass",
                                 "fernlake")
    outcome["ok"], outcome["error"] = False, "provider said no"
    sent, reason = outreach.welcome(second, "https://tallgrassapp.com/")
    check("it reports the failure", sent, False)
    check("  with the provider's reason", reason, "provider said no")

    outcome["ok"], outcome["error"] = True, None
    sent, _ = outreach.welcome(second, "https://tallgrassapp.com/")
    check("and the next attempt CAN send", sent, True)

    print()
    print("nobody who opted out is emailed again")
    third, _ = auth.create_user("third@example.com", "a-long-enough-pass",
                                "hollowbrook")
    db.set_email_optout(third["id"], True)
    with db.get_db() as conn:
        third = dict(conn.execute("SELECT * FROM users WHERE id = ?",
                                  (third["id"],)).fetchone())
    before = len(SENT)
    sent, reason = outreach.welcome(third, "https://tallgrassapp.com/")
    check("no welcome", sent, False)
    check("  and it says why", reason, "opted out")
    check("  and nothing was sent", len(SENT), before)

    print()
    print("the nudge finds people who are stuck, and only them")
    with db.get_db() as conn:
        # Signed up today: not stuck, just new.
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('today@example.com', 'x', datetime('now'))")
        # Signed up four days ago and captured nothing. This is the one.
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('stuck@example.com', 'x', "
                     "datetime('now', '-4 days'))")
        # Same age, but they got going — so there is nothing to nudge about.
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('working@example.com', 'x', "
                     "datetime('now', '-4 days'))")
        working = conn.execute(
            "SELECT id FROM users WHERE email = 'working@example.com'"
        ).fetchone()["id"]
        conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                     "VALUES (?, 'group:real', 'group', 'Real')", (working,))
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
            "post_type, posted_at, is_demo) SELECT ?, 'r1', id, 'b', 'text', "
            "'2026-09-01T00:00:00', 0 FROM sources WHERE user_id = ?",
            (working, working))
        # Long gone. Nudging this one is cold mail, not onboarding.
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('ancient@example.com', 'x', "
                     "datetime('now', '-200 days'))")
        # Runs the place. Does not need onboarding from their own product.
        conn.execute("INSERT INTO users (email, password_hash, created_at, "
                     "is_admin) VALUES ('boss@example.com', 'x', "
                     "datetime('now', '-4 days'), 1)")
        # Holds posts, but only the ones the app put there itself at signup.
        # Sample rows are not evidence that anybody did anything, so this
        # account is every bit as stuck as one with nothing at all — and the
        # query has to say so, or seeding the demo would have quietly switched
        # the nudge off for every new account in the same commit that
        # introduced it.
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('samples@example.com', 'x', "
                     "datetime('now', '-4 days'))")
        samples = conn.execute(
            "SELECT id FROM users WHERE email = 'samples@example.com'"
        ).fetchone()["id"]
        conn.execute("INSERT INTO sources (user_id, fb_id, kind, name) "
                     "VALUES (?, 'demo-group-ecom', 'group', '[DEMO] A')",
                     (samples,))
        conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
            "post_type, posted_at, is_demo) SELECT ?, 'd1', id, 'b', 'text', "
            "'2026-09-01T00:00:00', 1 FROM sources WHERE user_id = ?",
            (samples, samples))

    waiting = [u["email"] for u in outreach.dormant()]
    check("the stalled account is queued", "stuck@example.com" in waiting, True)
    check("somebody who signed up today is not",
          "today@example.com" in waiting, False)
    check("somebody already capturing is not",
          "working@example.com" in waiting, False)
    check("somebody from 200 days ago is not",
          "ancient@example.com" in waiting, False)
    check("the admin is not", "boss@example.com" in waiting, False)
    check("but an account holding only SAMPLES still is",
          "samples@example.com" in waiting, True)

    print()
    print("a sweep sends one each, and never sends again")
    before = len(SENT)
    count = outreach.sweep("https://tallgrassapp.com/")
    check("it sent to everyone waiting", count, len(waiting))
    check("  one message each", len(SENT) - before, len(waiting))
    check("  and the nudge names the real blocker",
          "Developer mode" in SENT[-1]["body"], True)

    check("a second sweep sends nothing",
          outreach.sweep("https://tallgrassapp.com/"), 0)
    check("  because nobody is left waiting", outreach.dormant(), [])

    print()
    print("the sweep does NOTHING unless it is switched on")
    # A deploy must not be able to email every dormant account by surprise.
    with db.get_db() as conn:
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('later@example.com', 'x', "
                     "datetime('now', '-4 days'))")
    check("somebody is waiting", len(outreach.dormant()), 1)

    os.environ["OUTREACH"] = ""
    before = len(SENT)
    check("but the switch is off", outreach.enabled(), False)
    check("so the sweep sends nothing",
          outreach.sweep("https://tallgrassapp.com/"), 0)
    check("  really nothing", len(SENT), before)
    os.environ["OUTREACH"] = "on"
    check("and back on, it sends",
          outreach.sweep("https://tallgrassapp.com/"), 1)

    print()
    print("the unsubscribe page works without being signed in")
    # Somebody reading their email is not necessarily signed in here, and
    # making them sign in to stop email is an unsubscribe in name only.
    anon = appmod.app.test_client()
    token = outreach.unsubscribe_token(user["id"])
    response = anon.get("/unsubscribe/" + token)
    check("it opens", response.status_code, 200)
    with db.get_db() as conn:
        opted = conn.execute("SELECT email_optout FROM users WHERE id = ?",
                             (user["id"],)).fetchone()["email_optout"]
    check("and they are opted out", bool(opted), True)

    # A mail scanner following the link is a real thing, so undoing it must be
    # on the page itself rather than behind a sign-in.
    check("the undo is offered", "resubscribe=1" in response.get_data(as_text=True),
          True)
    anon.get("/unsubscribe/%s?resubscribe=1" % token)
    with db.get_db() as conn:
        opted = conn.execute("SELECT email_optout FROM users WHERE id = ?",
                             (user["id"],)).fetchone()["email_optout"]
    check("and it puts them back", bool(opted), False)

    check("a forged token is a 404",
          anon.get("/unsubscribe/999-notarealsignature").status_code, 404)

    print()
    print("a reset still reaches somebody who opted out")
    # They asked for that one, in the moment, because they cannot get in.
    # Refusing it would lock them out of their own account to honour a
    # preference about marketing.
    db.set_email_optout(user["id"], True)
    raw, found = auth.create_reset_token("newbie@example.com")
    check("the token is still issued", bool(raw and found), True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("two emails, sent once, only to people who want them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
