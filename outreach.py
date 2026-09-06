"""Email that goes out because of what somebody did, or stopped doing.

Fifteen people signed up, handed over an address, and never heard from this
app once. `mailer.send` had exactly one caller — the password reset — so the
only message the product could produce was one you had to ask for. An account
that stalled on the install stalled in silence, and the first and last signal
was that they never came back.

Three messages, one per thing worth saying:

  welcome    Sent at signup. Says what they now have (a working dashboard full
             of sample data) and what the one remaining step is.
  nudge      Sent once, days later, and ONLY to somebody who still has not
             captured a real post. It names the thing that actually stops
             people — the Developer-mode install — and offers a hand.
  first_win  Sent once, when their OWN data first produces a real outlier. It
             leads with their number, because that is the moment the product
             has proved itself and the moment they decide whether it is worth
             paying for. Sample data never triggers it: congratulating
             somebody on a number this app generated for them would be the
             emptiest message it could send.

Nobody gets a fourth. There is no drip and no re-engagement campaign — these
are the three moments where there is something true to say, and a fourth would
be sending mail because a scheduler exists.

The switch and the copy both live in the database, not the environment. A
switch you want to flip the moment an email reads wrong should not need a
redeploy, and copy you cannot edit without one is copy nobody improves.

Three rules this module will not break:

  Sent once.       Claimed in the database BEFORE the send (db.claim_outreach),
                   because any page load can start a sweep and two of them can
                   overlap. Claimed-then-failed is released for a retry.
  Never to
  somebody who     email_optout is checked on every path. Password resets
  said no.         ignore it, correctly — those are asked for.
  Off until
  switched on.     The sweep does nothing unless OUTREACH=on. A deploy must
                   not be able to email every dormant account by surprise,
                   before anybody has read the copy.
"""

import hashlib
import hmac
import logging
import os
import threading

import db
import mailer

log = logging.getLogger("tallgrass.outreach")

WELCOME = "welcome"
NUDGE = "nudge"
FIRST_WIN = "first_win"

KINDS = (WELCOME, NUDGE, FIRST_WIN)

# How long to leave somebody alone before the nudge. Long enough that it is
# not nagging a person who is mid-install, short enough to arrive while they
# still remember signing up.
NUDGE_AFTER_DAYS = 2

# And the far edge. Somebody who signed up months ago and never returned is
# not stalled, they are gone, and a nudge to them is cold mail rather than
# onboarding. The existing dormant accounts sit inside this window; a year of
# them accumulating would not.
NUDGE_BEFORE_DAYS = 45

# Sent per sweep. The sweep runs off a page load, so this is the number of SMTP
# round trips one visitor's request can be responsible for — it happens on a
# thread, but a smaller batch still recovers better from a provider that starts
# rate-limiting halfway down the list.
BATCH = 5

# Minimum gap between sweeps, in seconds. Not daily: a batch of five would take
# three days to clear fifteen accounts, and the whole point is to reach the
# people who are already waiting.
SWEEP_INTERVAL = 900

SWEEP_KEY = "last_outreach_sweep"

# One sweep at a time in this process, so two simultaneous page loads cannot
# both start one. The database claim is what makes it safe across processes;
# this just avoids the wasted work.
_running = threading.Lock()


ENABLED_KEY = "outreach_enabled"


def enabled():
    """Whether the sweep may send anything.

    Kept in the database, so it is a button on the admin page rather than an
    environment variable and a redeploy. Something you will want to switch off
    the moment an email reads wrong should not require the service to restart.

    Default OFF, and deliberately. The welcome mail only ever affects somebody
    who just signed up and is watching for it. The sweep reaches backwards over
    every dormant account at once, and a deploy that does that on its own —
    before the operator has read the copy — is not a feature.

    OUTREACH in the environment still works, as the initial value for an
    install that has never touched the button.
    """
    stored = db.get_setting(ENABLED_KEY, "")
    if stored:
        return stored == "on"
    return (os.environ.get("OUTREACH") or "").strip().lower() in (
        "1", "on", "true", "yes")


def set_enabled(on):
    db.set_setting(ENABLED_KEY, "on" if on else "off")
    return enabled()


# Which messages are on when nobody has said otherwise.
#
# first_win starts OFF on purpose. Somebody who signs up and scans the same
# afternoon would otherwise get a welcome and a congratulations within the
# hour, which reads as a sequence running rather than a person writing — and
# the whole reason these are worth sending is that they do not read that way.
# It is worth having; it is not worth having by surprise.
DEFAULT_ON = {WELCOME: True, NUDGE: True, FIRST_WIN: False}

# And even switched on, first_win waits. The point of the email is that their
# own data proved something, which is not news ten minutes after signing up —
# it is the same event as the welcome, told twice.
FIRST_WIN_MIN_HOURS = 24


def kind_enabled(kind):
    """Whether this particular message may be sent.

    Both switches have to be on: the master one is a kill switch for all
    automated email, and this is the per-message choice underneath it.
    """
    if not enabled():
        return False
    stored = db.get_setting(_key(kind, "on"), "")
    if stored:
        return stored == "on"
    return DEFAULT_ON.get(kind, False)


def set_kind_enabled(kind, on):
    db.set_setting(_key(kind, "on"), "on" if on else "off")
    return kind_enabled(kind)


# ------------------------------------------------------------- unsubscribing

def unsubscribe_token(user_id):
    """A permanent, unguessable opt-out handle for one account.

    An HMAC rather than a stored token: an unsubscribe link has to keep working
    for as long as the email exists in somebody's inbox, which is forever, and
    a table of never-expiring tokens is a table that only grows. It carries no
    address, so the link is not worth anything to anyone who intercepts it
    beyond unsubscribing the person it already belongs to.
    """
    import auth
    signature = hmac.new(auth.get_secret_key().encode(),
                         ("unsubscribe:%s" % user_id).encode(),
                         hashlib.sha256).hexdigest()[:32]
    return "%s-%s" % (user_id, signature)


def user_id_for_token(token):
    """The account a token belongs to, or None. Constant-time compare."""
    try:
        raw_id, _ = (token or "").split("-", 1)
        user_id = int(raw_id)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(unsubscribe_token(user_id), token):
        return None
    return user_id


# ------------------------------------------------------------------ messages

# The starter copy. Editable from /admin, and these are what "Reset" restores.
#
# Written to be read by one person from another, not by a company at a list.
# All three end by asking for a reply, because at this size a reply is worth
# more than a click — the thing you cannot get from analytics is somebody
# telling you which step they gave up on.
DEFAULTS = {
    WELCOME: {
        "subject": "Your Tallgrass account is ready",
        "body": (
            "Your Tallgrass account is ready, and it already has something in "
            "it.\n\n"
            "Open the dashboard and you'll find sample groups already scored "
            "the way yours will be — every post ranked against the median of "
            "the group it came from, so a breakout in a small group outranks "
            "a mediocre post from a big page. Click into any of them, or try "
            "Write, which works on that data right now.\n\n"
            "That's the product. Have a look before you install anything:\n\n"
            "{dashboard}\n\n"
            "When you want it running on your own groups, there's one step "
            "left — the Chrome extension, which reads posts as you scroll "
            "Facebook:\n\n"
            "{install}\n\n"
            "The moment your first real scan lands, the sample data hides "
            "itself and everything you see is yours.\n\n"
            "If you get stuck, reply to this email. A real person reads it."
        ),
    },
    NUDGE: {
        "subject": "Stuck on the Tallgrass install?",
        "body": (
            "You signed up for Tallgrass a couple of days ago and haven't "
            "captured anything yet, so I wanted to check whether the install "
            "was the thing that stopped you. It usually is.\n\n"
            "It's the awkward part and I'd rather say so plainly: the "
            "extension has to be loaded by hand for now. Download a zip, "
            "unzip it somewhere permanent, turn on Developer mode at "
            "chrome://extensions, and drag the folder in. Five minutes if it "
            "goes well.\n\n"
            "The steps, with pictures:\n\n{install}\n\n"
            "If it went badly, or you got somewhere and it didn't work, reply "
            "and tell me where it broke. I'll either fix it or walk you "
            "through it — and knowing where people get stuck is genuinely "
            "useful to me.\n\n"
            "Your sample data is still there in the meantime, if you'd rather "
            "just look at what it does first:\n\n{dashboard}"
        ),
    },
    # The third one, and the one that was missing.
    #
    # Welcome greets somebody and nudge chases somebody who stalled. Neither
    # says anything to the person who actually got it working — who is the one
    # worth talking to, and the one about to decide whether this is worth
    # paying for. It fires once, when their own data first produces a real
    # outlier, and it leads with their number rather than a feature.
    FIRST_WIN: {
        "subject": "Your first outlier: {top_multiple}x",
        "body": (
            "Your first scan has scored.\n\n"
            "The best post Tallgrass found in {source} beat that group's "
            "median by {top_multiple}x. On its own that is just a number — "
            "what it means is that the post did {top_multiple} times what a "
            "normal post does in that specific group, which is the only "
            "comparison that tells you anything. A thousand reactions is "
            "ordinary in one group and extraordinary in another.\n\n"
            "Here it is:\n\n{dashboard}\n\n"
            "Then the part most people skip. Open that post and press Remix. "
            "Finding what worked is half of this; writing your own version of "
            "the thing that made it work is the half that puts something in "
            "your own feed.\n\n"
            "If the number looks wrong, or the post it picked seems off, "
            "reply and tell me — that is exactly the sort of thing I want to "
            "hear about early."
        ),
    },
}

# What an editable body may refer to. Substituted by plain replacement rather
# than str.format, so a stray brace typed into the copy cannot raise on send.
TOKENS = {
    "{dashboard}": "the dashboard's address",
    "{install}": "the install instructions page",
    "{top_multiple}": "their best post's multiple (first-outlier email only)",
    "{source}": "the group it came from (first-outlier email only)",
}

LABELS = {
    WELCOME: "Welcome",
    NUDGE: "Nudge",
    FIRST_WIN: "First outlier",
}

NOTES = {
    WELCOME: "Sent the moment somebody signs up.",
    NUDGE: "Sent once, %d–%d days after signing up, and only to somebody who "
           "still has not captured a real post." % (NUDGE_AFTER_DAYS,
                                                    NUDGE_BEFORE_DAYS),
    FIRST_WIN: "Sent once, when their own captures first produce a real "
               "outlier — never sooner than %d hours after signup, so it "
               "cannot land the same day as the welcome." % FIRST_WIN_MIN_HOURS,
}


def _key(kind, part):
    return "outreach_%s_%s" % (part, kind)


def get_template(kind):
    """The operator's copy for this email, or the starter copy."""
    default = DEFAULTS[kind]
    return {
        "subject": db.get_setting(_key(kind, "subject"), "") or default["subject"],
        "body": db.get_setting(_key(kind, "body"), "") or default["body"],
        "edited": bool(db.get_setting(_key(kind, "body"), "")),
    }


def set_template(kind, subject, body):
    db.set_setting(_key(kind, "subject"), (subject or "").strip())
    db.set_setting(_key(kind, "body"), (body or "").strip())
    return get_template(kind)


def reset_template(kind):
    db.set_setting(_key(kind, "subject"), "")
    db.set_setting(_key(kind, "body"), "")
    return get_template(kind)


def _footer(base_url, user_id):
    """Appended to every message, and deliberately not editable.

    A way out is not a stylistic choice. Somebody who cannot find one presses
    the spam button instead, and a sender reputation is far easier to keep
    than to repair — so this cannot be edited away by accident.
    """
    link = "%sunsubscribe/%s" % (base_url, unsubscribe_token(user_id))
    return ("\n\n—\nTallgrass, by MacRandle Acres\n"
            "No more emails about getting started: %s\n" % link)


def render(text, base_url, facts=None):
    """Fill the tokens in. Never raises on odd copy."""
    values = {
        "{dashboard}": base_url,
        "{install}": "%scapture" % base_url,
        "{top_multiple}": "",
        "{source}": "your group",
    }
    values.update(facts or {})
    for token, value in values.items():
        text = text.replace(token, str(value))
    return text


# -------------------------------------------------------------------- sending

def _send(user, kind, base_url, facts=None):
    """Claim, send, and release the claim if it failed. Returns (sent, reason)."""
    if user.get("email_optout"):
        return False, "opted out"
    if not mailer.is_configured():
        return False, "email is not configured"
    # Checked here rather than at each call site, so a message that is switched
    # off cannot be sent by any route — and, just as importantly, does not
    # claim its row. Somebody who was skipped while it was off is still owed it
    # if it is ever switched on.
    if not kind_enabled(kind):
        return False, "this email is switched off"

    if not db.claim_outreach(user["id"], kind):
        return False, "already sent"

    template = get_template(kind)
    subject = render(template["subject"], base_url, facts)
    body = render(template["body"], base_url, facts) + _footer(base_url, user["id"])

    link = "%sunsubscribe/%s" % (base_url, unsubscribe_token(user["id"]))
    ok, error = mailer.send(
        user["email"], subject, body,
        # Puts an unsubscribe control in Gmail's own interface, next to the
        # spam button. Somebody who cannot find a way out uses the other one,
        # and that is the difference between an opt-out and a spam complaint.
        headers={"List-Unsubscribe": "<%s>" % link})
    if not ok:
        # Give the claim back. A provider having a bad minute must not cost
        # somebody their only welcome email.
        db.release_outreach(user["id"], kind)
        log.warning("%s email failed for user %s: %s", kind, user["id"], error)
        return False, error

    log.info("sent %s email to user %s", kind, user["id"])
    return True, None


def welcome(user, base_url):
    """Say hello, once, at signup. Never raises."""
    try:
        return _send(dict(user), WELCOME, base_url)
    except Exception as exc:                  # noqa: BLE001
        log.warning("welcome email raised for user %s: %s",
                    (user or {}).get("id"), exc)
        return False, str(exc)


def welcome_async(user, base_url):
    """Say hello without making them wait for it.

    An SMTP round trip is a second or two, and spending it inside the signup
    request means the first thing the product does is feel slow. The claim in
    _send is what makes this safe to fire and forget.
    """
    try:
        threading.Thread(target=welcome, args=(dict(user), base_url),
                         daemon=True, name="outreach-welcome").start()
    except Exception:                         # noqa: BLE001 - never break signup
        log.warning("could not start welcome email thread", exc_info=True)


def dormant():
    """Accounts that signed up, never captured a real post, and are owed a nudge.

    Deliberately not user_health's `never` bucket, which is every account that
    has never captured — including one that signed up an hour ago and one that
    signed up in March. This is the narrower question of who is stalled right
    now and has not already been asked about it.
    """
    try:
        with db.get_db() as conn:
            return [dict(r) for r in conn.execute(
                """
                SELECT u.id, u.email, u.email_optout
                FROM users u
                WHERE COALESCE(u.is_admin, 0) = 0
                  AND COALESCE(u.email_optout, 0) = 0
                  AND u.created_at <= datetime('now', ?)
                  AND u.created_at >= datetime('now', ?)
                  AND NOT EXISTS (SELECT 1 FROM posts p
                                   WHERE p.user_id = u.id AND p.is_demo = 0)
                  AND NOT EXISTS (SELECT 1 FROM outreach o
                                   WHERE o.user_id = u.id AND o.kind = ?)
                ORDER BY u.created_at
                """,
                ("-%d days" % NUDGE_AFTER_DAYS,
                 "-%d days" % NUDGE_BEFORE_DAYS,
                 NUDGE)).fetchall()]
    except Exception:                         # noqa: BLE001
        return []


def winners():
    """Accounts whose own captures have produced a real outlier, unemailed.

    The cheap half is SQL: who has enough readable posts in one source to have
    a baseline at all. The expensive half — actually scoring them — is done
    per candidate below, because it is a handful of accounts rather than all
    of them, and the email is only worth sending if it can lead with a number.
    """
    try:
        with db.get_db() as conn:
            return [dict(r) for r in conn.execute(
                """
                SELECT u.id, u.email, u.email_optout
                FROM users u
                WHERE COALESCE(u.email_optout, 0) = 0
                  AND u.created_at <= datetime('now', ?)
                  AND EXISTS (
                      SELECT 1 FROM posts p
                      WHERE p.user_id = u.id AND p.is_demo = 0
                        AND p.engagement_read = 1
                      GROUP BY p.source_id HAVING COUNT(*) >= ?)
                  AND NOT EXISTS (SELECT 1 FROM outreach o
                                   WHERE o.user_id = u.id AND o.kind = ?)
                ORDER BY u.created_at
                """, ("-%d hours" % FIRST_WIN_MIN_HOURS,
                      _min_sample(), FIRST_WIN)).fetchall()]
    except Exception:                         # noqa: BLE001
        return []


def _min_sample():
    import outliers
    return outliers.MIN_SAMPLE


def best_post(user_id):
    """Their biggest real outlier, as (multiple, source name). None if none.

    Sample data is excluded: an email congratulating somebody on a number the
    app generated for them would be the emptiest message this product could
    send.
    """
    try:
        import app
        import outliers
        scored = outliers.score_posts(app._scoring_rows(user_id=user_id))
        real = [s for s in scored
                if not s["is_demo"] and s.get("outlier_multiple")]
        if not real:
            return None
        top = max(real, key=lambda s: s["outlier_multiple"])
        with db.get_db() as conn:
            row = conn.execute("SELECT name FROM sources WHERE id = ?",
                               (top["source_id"],)).fetchone()
        return top["outlier_multiple"], (row["name"] if row else "your group")
    except Exception:                         # noqa: BLE001
        log.warning("could not score user %s for first-win email", user_id,
                    exc_info=True)
        return None


def sweep(base_url, limit=BATCH):
    """Send what is due. Returns how many went out."""
    if not enabled() or not mailer.is_configured():
        return 0

    sent = 0
    if kind_enabled(NUDGE):
        for user in dormant()[:limit]:
            ok, _ = _send(user, NUDGE, base_url)
            if ok:
                sent += 1

    # Scoring is not free, so a switched-off message must not pay for it.
    for user in (winners()[:limit] if kind_enabled(FIRST_WIN) else []):
        best = best_post(user["id"])
        if not best:
            # They cleared the sample floor but nothing actually beat its
            # median yet. Not a failure — just not news, so nothing is
            # claimed and they stay eligible for when it is.
            continue
        multiple, source = best
        ok, _ = _send(user, FIRST_WIN, base_url,
                      facts={"{top_multiple}": multiple, "{source}": source})
        if ok:
            sent += 1

    return sent


def maybe_sweep(base_url):
    """Run a sweep if one is due, on a thread, never blocking the page.

    Same shape as the daily backup: no scheduler, no supervised worker, just a
    check on the way past. The thread is short-lived and does one batch — the
    objection to background threads in this app is to a permanent one that has
    to be watched, not to five SMTP calls that must not happen inside somebody
    else's page load.
    """
    if not enabled() or not mailer.is_configured():
        return
    try:
        import time
        last = float(db.get_setting(SWEEP_KEY, "0") or 0)
        if time.time() - last < SWEEP_INTERVAL:
            return
        if not _running.acquire(blocking=False):
            return
        # Stamped before the work, not after, so a sweep that dies partway
        # through does not leave the next page load starting another.
        db.set_setting(SWEEP_KEY, str(time.time()))

        def run():
            try:
                sweep(base_url)
            except Exception:                 # noqa: BLE001
                log.warning("outreach sweep failed", exc_info=True)
            finally:
                _running.release()

        threading.Thread(target=run, daemon=True,
                         name="outreach-sweep").start()
    except Exception:                         # noqa: BLE001 - never break a page
        try:
            _running.release()
        except RuntimeError:
            pass


def status():
    """What the admin page needs to say about all this."""
    summary = db.outreach_summary()
    on = enabled()
    return {
        "enabled": on,
        "configured": mailer.is_configured(),
        "optouts": summary["optouts"],
        "waiting": len(dormant()) if on and kind_enabled(NUDGE) else 0,
        "winners_waiting": len(winners()) if on and kind_enabled(FIRST_WIN) else 0,
        "tokens": TOKENS,
        "emails": [
            {
                "kind": kind,
                "label": LABELS[kind],
                "sent": summary["sent"].get(kind, 0),
                "on": kind_enabled(kind),
                "note": NOTES.get(kind, ""),
                **get_template(kind),
            }
            for kind in KINDS
        ],
    }
