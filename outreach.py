"""Email that goes out because of what somebody did, or stopped doing.

Fifteen people signed up, handed over an address, and never heard from this
app once. `mailer.send` had exactly one caller — the password reset — so the
only message the product could produce was one you had to ask for. An account
that stalled on the install stalled in silence, and the first and last signal
was that they never came back.

Two messages, and deliberately only two:

  welcome  Sent at signup. Says what they now have (a working dashboard full
           of sample data) and what the one remaining step is.
  nudge    Sent once, a couple of days later, and ONLY to somebody who still
           has not captured a real post. It names the thing that actually
           stops people — the Developer-mode install — and offers a hand.

Nobody gets a third. There is no drip, no sequence, no re-engagement campaign:
this app has one thing to tell somebody who is stuck, and saying it twice is
the whole budget.

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


def enabled():
    """Whether the nudge sweep may send anything.

    Default OFF, and deliberately. The welcome mail only ever affects somebody
    who just signed up and is watching for it. The sweep reaches backwards over
    every dormant account at once, and a deploy that does that on its own —
    before the operator has read the copy — is not a feature.
    """
    return (os.environ.get("OUTREACH") or "").strip().lower() in (
        "1", "on", "true", "yes")


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

def _footer(base_url, user_id):
    link = "%sunsubscribe/%s" % (base_url, unsubscribe_token(user_id))
    return ("\n\n—\nTallgrass, by MacRandle Acres\n"
            "No more emails about getting started: %s\n" % link)


def _welcome_body(base_url, user_id):
    return (
        "Your Tallgrass account is ready, and it already has something in it.\n\n"
        "Open the dashboard and you'll find three sample groups with about "
        "ninety posts, scored exactly the way yours will be — each one ranked "
        "against the median of the group it came from, so a breakout in a "
        "small group outranks a mediocre post from a big page. Click into any "
        "of them, or try Write, which works on that data right now.\n\n"
        "That's the product. Have a look before you install anything.\n\n"
        "%s\n\n"
        "When you want it running on your own groups, there's one step left: "
        "the Chrome extension, which is what reads posts as you scroll "
        "Facebook. It takes a few minutes and the instructions are here:\n\n"
        "%scapture\n\n"
        "The moment your first real scan lands, the sample data hides itself "
        "and everything you see is yours.\n\n"
        "If you get stuck on the install, reply to this email. A real person "
        "reads it."
        % (base_url, base_url)
    ) + _footer(base_url, user_id)


def _nudge_body(base_url, user_id):
    return (
        "You signed up for Tallgrass a couple of days ago and haven't "
        "captured anything yet, so I wanted to check whether the install was "
        "the thing that stopped you. It usually is.\n\n"
        "It's the awkward part, and I'd rather say so plainly than pretend "
        "otherwise: the extension isn't in the Chrome Web Store yet, so it has "
        "to be loaded by hand. Download a zip, unzip it somewhere permanent, "
        "turn on Developer mode at chrome://extensions, and drag the folder "
        "in. Five minutes if it goes well.\n\n"
        "The steps, with pictures:\n\n%scapture\n\n"
        "If it went badly, or you got somewhere and it didn't work, reply and "
        "tell me where it broke. I'll either fix it or walk you through it — "
        "and knowing where people get stuck is genuinely useful to me.\n\n"
        "Your sample data is still there in the meantime, if you'd rather just "
        "look at what it does first:\n\n%s"
        % (base_url, base_url)
    ) + _footer(base_url, user_id)


MESSAGES = {
    WELCOME: ("Your Tallgrass account is ready", _welcome_body),
    NUDGE: ("Stuck on the Tallgrass install?", _nudge_body),
}


# -------------------------------------------------------------------- sending

def _send(user, kind, base_url):
    """Claim, send, and release the claim if it failed. Returns (sent, reason)."""
    if user.get("email_optout"):
        return False, "opted out"
    if not mailer.is_configured():
        return False, "email is not configured"

    if not db.claim_outreach(user["id"], kind):
        return False, "already sent"

    subject, build = MESSAGES[kind]
    link = "%sunsubscribe/%s" % (base_url, unsubscribe_token(user["id"]))
    ok, error = mailer.send(
        user["email"], subject, build(base_url, user["id"]),
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
    """Nudge up to `limit` stalled accounts. Returns how many were sent."""
    if not enabled() or not mailer.is_configured():
        return 0
    sent = 0
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
    return {
        "enabled": enabled(),
        "configured": mailer.is_configured(),
        "welcome_sent": summary["sent"].get(WELCOME, 0),
        "nudge_sent": summary["sent"].get(NUDGE, 0),
        "optouts": summary["optouts"],
        "waiting": len(dormant()),
    }
