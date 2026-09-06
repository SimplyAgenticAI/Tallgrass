"""Email that goes out because of what somebody did, or stopped doing.

Fifteen people signed up, handed over an address, and never heard from this
app once. `mailer.send` had exactly one caller — the password reset — so the
only message the product could produce was one you had to ask for. An account
that stalled on the install stalled in silence, and the first and last signal
was that they never came back.

Two messages, and deliberately only two:

  welcome  Sent at signup. Says what they now have (a working dashboard full
           of sample data) and what the one remaining step is.
  nudge    Sent once, days later, and ONLY to somebody who still has not
           captured a real post. It names the thing that actually stops
           people — the Developer-mode install — and offers a hand.

There was briefly a third, sent when somebody's own captures first produced an
outlier. It was removed on the operator's call: two emails from a product
somebody just signed up to is the edge of welcome, and a third arriving
because a threshold tripped is where onboarding starts to feel like a
sequence running rather than a person writing. The machinery to add another
kind is still here — a key in KINDS, an entry in DEFAULTS — if that judgement
ever changes.

The switches and the copy live in the database, not the environment. A switch
you want to flip the moment an email reads wrong should not need a redeploy,
and copy you cannot edit without one is copy nobody improves.

Three rules this module will not break:

  Sent once.       Claimed in the database BEFORE the send (db.claim_outreach),
                   because any page load can start a sweep and two of them can
                   overlap. Claimed-then-failed is released for a retry.
  Never to
  somebody who     email_optout is checked on every path. Password resets
  said no.         ignore it, correctly — those are asked for.
  Off until
  switched on.     Nothing sends while the master switch is off, whatever the
                   individual ones say. A deploy must not be able to email
                   every dormant account by surprise, before anybody has read
                   the copy.
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

KINDS = (WELCOME, NUDGE)

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
DEFAULT_ON = {WELCOME: True, NUDGE: True}


def kind_on(kind):
    """This message's OWN switch, ignoring the master one.

    Kept separate from kind_enabled because the admin page needs to show what
    the button did. Folding the master switch into the only available answer
    meant that with sending paused, turning an individual message on saved
    correctly and still displayed as off — so the button never changed and
    there was no way to turn it back off again.
    """
    stored = db.get_setting(_key(kind, "on"), "")
    if stored:
        return stored == "on"
    return DEFAULT_ON.get(kind, False)


def kind_enabled(kind):
    """Whether this message may ACTUALLY be sent right now.

    Both switches have to be on: the master one is a kill switch for all
    automated email, and kind_on is the per-message choice underneath it.
    """
    return enabled() and kind_on(kind)


def set_kind_enabled(kind, on):
    db.set_setting(_key(kind, "on"), "on" if on else "off")
    return kind_on(kind)


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
# Both end by asking for a reply, because at this size a reply is worth more
# than a click — the thing you cannot get from analytics is somebody telling
# you which step they gave up on.
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
            "Facebook. It's on the Chrome Web Store, so it's one click:\n\n"
            "{store}\n\n"
            "Then open the dashboard again and it connects itself. Nothing to "
            "copy, nothing to paste.\n\n"
            "The moment your first real scan lands, the sample data hides "
            "itself and everything you see is yours.\n\n"
            "If you get stuck, reply to this email. A real person reads it."
        ),
    },
    NUDGE: {
        "subject": "The Tallgrass install just got a lot easier",
        "body": (
            "You signed up for Tallgrass a while back and haven't captured "
            "anything yet. I'm fairly sure I know why, and it wasn't you.\n\n"
            "To install the extension you had to download a zip, unzip it "
            "somewhere permanent, turn on Developer mode and drag a folder "
            "into Chrome. That's a lot to ask, and almost nobody finished "
            "it.\n\n"
            "It's on the Chrome Web Store now. One click:\n\n"
            "{store}\n\n"
            "Then open the dashboard and it connects itself — no key to "
            "copy, no folder to keep, and it updates on its own from here.\n\n"
            "{dashboard}\n\n"
            "If you try it and something still doesn't work, reply and tell "
            "me where it broke. Knowing where people get stuck is genuinely "
            "useful to me."
        ),
    },
    # The third one, and the one that was missing.
    #
}

# What an editable body may refer to. Substituted by plain replacement rather
# than str.format, so a stray brace typed into the copy cannot raise on send.
TOKENS = {
    "{dashboard}": "the dashboard's address",
    "{install}": "the install instructions page",
    "{store}": "the Chrome Web Store listing",
}

LABELS = {
    WELCOME: "Welcome",
    NUDGE: "Nudge",
}

NOTES = {
    WELCOME: "Sent the moment somebody signs up.",
    NUDGE: "Sent once, %d–%d days after signing up, and only to somebody who "
           "still has not captured a real post." % (NUDGE_AFTER_DAYS,
                                                    NUDGE_BEFORE_DAYS),
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


def app_store_url():
    """The Chrome Web Store listing, read from app.py where it is defined.

    Imported inside the function because app.py imports THIS module, so a
    module-level import would be a cycle. By the time any email is rendered
    app is long since in sys.modules, and this is a dictionary lookup.

    Copying the URL into a second file would have been simpler to read and
    wrong the first time the listing is re-published under a new slug.
    """
    try:
        import app
        return app.EXTENSION_STORE_URL
    except Exception:
        # A message that arrives with a broken link is worse than one that
        # sends people the long way round, and the Capture page always works.
        return ""


def render(text, base_url, facts=None):
    """Fill the tokens in. Never raises on odd copy."""
    values = {
        "{dashboard}": base_url,
        "{install}": "%scapture" % base_url,
        # The store listing itself, for copy that wants to send somebody
        # straight there. {install} still points at the Capture page, which is
        # the right destination when the message is walking them through it —
        # this is the one for "here, click this."
        #
        # Falls back to the Capture page rather than to an empty string: a
        # token that vanishes leaves "install it here:" followed by nothing,
        # which reads as a broken email rather than a longer route.
        "{store}": app_store_url() or ("%scapture" % base_url),
    }
    # `facts` is how a message would carry something about the specific
    # account — a number, a group name. Nothing needs it today; the parameter
    # stays because it is the seam a per-account message would use.
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
        "tokens": TOKENS,
        "emails": [
            {
                "kind": kind,
                "label": LABELS[kind],
                "sent": summary["sent"].get(kind, 0),
                # What the button did, and what is actually happening. They
                # differ whenever the master switch is off, and saying so is
                # the difference between "paused" and "you clicked nothing".
                "on": kind_on(kind),
                "sending": kind_enabled(kind),
                "note": NOTES.get(kind, ""),
                **get_template(kind),
            }
            for kind in KINDS
        ],
    }
