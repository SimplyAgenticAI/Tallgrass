"""Email the product sends on its own.

Fifteen people signed up and heard nothing, because `mailer.send` had exactly
one caller — the password reset. There are now two more: a welcome at signup
and a single nudge to somebody who never captured anything, both switchable
and editable from the admin page.

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
  off       the sweep sends nothing at all while the switch is off
  editable  the copy can be rewritten from /admin without the unsubscribe
            link going with it, and a stray brace cannot break a send

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
    check("and it points at the store listing",
          outreach.app_store_url() in SENT[-1]["body"], True)
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
    # The nudge exists to get somebody past the install, so it has to carry the
    # one-click route. And it must never again TELL anyone to sideload: the
    # store listing was approved on 6 September 2026 specifically to delete
    # that, and a nudge that walks people back to chrome://extensions would
    # rebuild the wall the whole exercise was about. Naming Developer mode in
    # the past tense is fine and the current copy does — it is the instruction
    # that must not come back, so the address is what is checked.
    check("  and the nudge carries the one-click install",
          outreach.app_store_url() in SENT[-1]["body"], True)
    check("  and never sends anybody to sideload it",
          "chrome://extensions" in SENT[-1]["body"], False)

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
    print("the switch is a button, not a redeploy")
    # It lived in the environment, which meant turning it off the moment an
    # email read wrong required a restart of the service.
    outreach.set_enabled(False)
    check("off stays off even with OUTREACH=on in the environment",
          outreach.enabled(), False)
    check("  and the sweep sends nothing",
          outreach.sweep("https://tallgrassapp.com/"), 0)
    outreach.set_enabled(True)
    check("back on again", outreach.enabled(), True)

    print()
    print("each message has its own switch under the master one")
    # Somebody who signs up and scans the same afternoon would otherwise get a
    # welcome and a congratulations within the hour, which reads as a sequence
    # running rather than a person writing.
    check("welcome is on by default",
          outreach.kind_enabled(outreach.WELCOME), True)
    check("  and so is the nudge", outreach.kind_enabled(outreach.NUDGE), True)

    outreach.set_kind_enabled(outreach.NUDGE, False)
    with db.get_db() as conn:
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('offswitch@example.com', 'x', "
                     "datetime('now', '-4 days'))")
    before = len(SENT)
    outreach.sweep("https://tallgrassapp.com/")
    check("a switched-off nudge sends nothing", len(SENT), before)
    # Skipped is not the same as spent: they must still be owed it.
    check("  and the person is still queued for it",
          "offswitch@example.com" in [u["email"] for u in outreach.dormant()],
          True)
    outreach.set_kind_enabled(outreach.NUDGE, True)
    outreach.sweep("https://tallgrassapp.com/")
    check("switching it back on delivers it",
          any(m["to"] == "offswitch@example.com" for m in SENT[before:]), True)

    print()
    print("the master switch beats every individual one")
    outreach.set_enabled(False)
    check("welcome is off too", outreach.kind_enabled(outreach.WELCOME), False)
    # But its OWN switch is untouched, and that is what the button shows.
    # Folding the master switch into the only available answer meant that with
    # sending paused, turning a message on saved correctly and still displayed
    # as off — so the button never changed and there was no way back.
    check("  while its own switch still reads on",
          outreach.kind_on(outreach.WELCOME), True)
    outreach.set_kind_enabled(outreach.NUDGE, True)
    check("  and one turned on while paused reads on",
          outreach.kind_on(outreach.NUDGE), True)
    check("    even though nothing is being sent",
          outreach.kind_enabled(outreach.NUDGE), False)
    master, _ = auth.create_user("master@example.com", "a-long-enough-pass",
                                 "stonebridge")
    sent, reason = outreach.welcome(master, "https://tallgrassapp.com/")
    check("  so a signup gets nothing", sent, False)
    check("  and says why", reason, "this email is switched off")
    # And it did not burn the claim on the way past.
    outreach.set_enabled(True)
    sent, _ = outreach.welcome(master, "https://tallgrassapp.com/")
    check("switching back on, they still get it", sent, True)

    print()
    print("the copy can be edited, and put back")
    original = outreach.get_template(outreach.NUDGE)
    check("starts as the original", original["edited"], False)
    outreach.set_template(outreach.NUDGE, "My own subject",
                          "My own words, and the link: {install}")
    edited = outreach.get_template(outreach.NUDGE)
    check("the edit sticks", edited["subject"], "My own subject")
    check("  and is marked as edited", edited["edited"], True)

    with db.get_db() as conn:
        conn.execute("INSERT INTO users (email, password_hash, created_at) "
                     "VALUES ('edited@example.com', 'x', "
                     "datetime('now', '-4 days'))")
    before = len(SENT)
    outreach.sweep("https://tallgrassapp.com/")
    check("the sent email uses the new copy",
          SENT[-1]["subject"], "My own subject")
    check("  with its tokens filled in",
          "https://tallgrassapp.com/capture" in SENT[-1]["body"], True)
    # Editable copy must not be able to remove the way out.
    check("  and the unsubscribe link is STILL there",
          "unsubscribe/" in SENT[-1]["body"], True)

    outreach.reset_template(outreach.NUDGE)
    check("reset restores the original",
          outreach.get_template(outreach.NUDGE)["subject"],
          outreach.DEFAULTS[outreach.NUDGE]["subject"])

    print()
    print("a stray brace in the copy does not blow up a send")
    # str.format would raise on this and take the sweep down with it, which is
    # why substitution is plain replacement.
    outreach.set_template(outreach.WELCOME, "Braces {oops} here",
                          "A body with {a stray brace} and {dashboard}.")
    brace, _ = auth.create_user("brace@example.com", "a-long-enough-pass",
                                "marshfield")
    sent, reason = outreach.welcome(brace, "https://tallgrassapp.com/")
    check("it still sends", sent, True)
    check("  leaving the unknown token alone",
          "{a stray brace}" in SENT[-1]["body"], True)
    check("  and filling the real one",
          "https://tallgrassapp.com/" in SENT[-1]["body"], True)
    outreach.reset_template(outreach.WELCOME)

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
    print("two emails, sent once each, only to people who want them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
