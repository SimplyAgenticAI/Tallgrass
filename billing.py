"""Subscriptions via Stripe Checkout.

This module never sees a card number. Checkout is a Stripe-hosted page: the
user is redirected there, enters payment details on Stripe's domain, and comes
back with nothing sensitive in hand. Entitlement is then set from a
signature-verified webhook rather than from the redirect, because a redirect
URL is attacker-controllable and a webhook is not.
"""

import os
from datetime import datetime, timedelta, timezone

import db

# Pricing.
#
# The tool replaces manual group research and hands back finished copy, so it
# sits well above a utility and well below the $100+ social-listening suites
# it competes against. $19 is low enough to be an easy yes without a
# procurement conversation, high enough to fund support and hosting.
#
# The annual price is ten months for twelve — a discount that is legible at a
# glance and needs no explaining.
PLANS = {
    "month": {
        "label": "Monthly",
        "amount": 1900,          # cents
        "display": "$19",
        "period": "per month",
        "note": "Cancel any time.",
    },
    "year": {
        "label": "Yearly",
        "amount": 19000,
        "display": "$190",
        "period": "per year",
        "note": "Two months free. Works out at $15.83/mo.",
        "badge": "Save 17%",
    },
}

FREE_LIMITS = {"sources": None, "posts": 1000}   # None = unlimited

# Black Friday 2026: one free month of Pro for accounts that sign up through
# the promo. The prices above are not touched. The free month is a trial on
# the Checkout session, and only on that path, so an existing subscriber and
# a normal signup are billed exactly as they are today.
#
# The banner hides itself. Leave both variables unset and it stays up through
# the end of Cyber Monday 2026 in US Pacific (midnight PST, 1 December 08:00
# UTC), then disappears. Set BLACK_FRIDAY_OFFER=0 to take it down immediately,
# or BLACK_FRIDAY_OFFER=1 to keep it up past the date. BLACK_FRIDAY_ENDS
# replaces the date: a YYYY-MM-DD runs through the end of that UTC day, and a
# full timestamp is the instant it turns off.
OFFER_CODE = "blackfriday"
OFFER_TRIAL_DAYS = 30
_DEFAULT_OFFER_END = datetime(2026, 12, 1, 8, 0, tzinfo=timezone.utc)
_OFFER_ON = ("1", "on", "true", "yes")
_OFFER_OFF = ("0", "off", "false", "no")


def offer_ends_at():
    """When the promo stops accepting new signups. Exclusive."""
    raw = os.environ.get("BLACK_FRIDAY_ENDS", "").strip()
    if raw:
        parsed = _parse_offer_end(raw)
        if parsed:
            return parsed
    return _DEFAULT_OFFER_END


def _parse_offer_end(raw):
    try:
        if len(raw) == 10:
            day = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return day + timedelta(days=1)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def offer_active(now=None):
    """Whether the landing page should offer the free month.

    Read on every request, so a dashboard change to the env var takes effect
    on the next page without a code change. Accounts that already signed up
    through the offer keep their trial either way: this only gates the banner
    and new stamps.
    """
    flag = os.environ.get("BLACK_FRIDAY_OFFER", "").strip().lower()
    if flag in _OFFER_OFF:
        return False
    if flag in _OFFER_ON:
        return True
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < offer_ends_at()


def normalize_offer(value):
    """The offer code to stamp, or None when the promo is off or unknown."""
    code = (value or "").strip().lower()
    if code == OFFER_CODE and offer_active():
        return OFFER_CODE
    return None


def claim_offer(user_id, code):
    """Remember that this new account came in through the promo.

    Returns True when the stamp is written. A second call does not overwrite
    it, and a code that is not the live offer writes nothing.
    """
    code = normalize_offer(code)
    if not code:
        return False
    with db.get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET signup_offer = ? "
            "WHERE id = ? AND signup_offer IS NULL",
            (code, user_id),
        )
        return cur.rowcount == 1


def trial_days_for(user):
    """Free days to put on this account's first Checkout, or 0.

    The promise was made at signup, so it still applies after the banner has
    hidden itself. It does not apply twice: once a subscription exists, the
    next checkout bills the normal price from day one.
    """
    if not user or (user.get("signup_offer") or "") != OFFER_CODE:
        return 0
    if user.get("stripe_subscription_id"):
        return 0
    return OFFER_TRIAL_DAYS


def checkout_is_trial(session):
    """True when this Checkout was created with the free month attached."""
    try:
        return int((session.get("metadata") or {}).get("trial_days") or 0) > 0
    except (TypeError, ValueError):
        return False


def subscription_period_end(subscription):
    """Unix timestamp the account page should show, or None.

    During a trial, current_period_end is the trial end on the API versions
    this app already reads. trial_end covers a payload that only carries that.
    """
    period_end = subscription.get("current_period_end")
    if not period_end and subscription.get("status") == "trialing":
        period_end = subscription.get("trial_end")
    return period_end or None

# One difference between the tiers, and it is volume.
#
# The old lists claimed Sage, remix, ideas and export were Pro-only. Nothing
# in the code has ever enforced that — capture_allowed is the single gate in
# the app and it counts posts. So the pricing page was telling free users they
# could not have things they already had, which is the one direction a pricing
# page must never be wrong in: it argues against the product to the people
# still deciding whether it works.
#
# Holding features back also hides the thing worth paying for. Somebody who
# has never seen a remix has no reason to want more capture; somebody who has
# used it on their own winning post has an obvious one.
# Only what the money actually buys.
#
# The first line used to read "Everything in Free, with nothing held back",
# which states the obvious — nobody pays to receive less — and spends the most
# valuable line on the card sounding defensive. Pro differs from Free in one
# way, so the list says what that one way gets you rather than restating that
# it is a superset.
# How long other people's posts are kept. ONE constant, because the number
# appears on the pricing page, in the account page, and in the sweep that
# enforces it — and a policy written down in three places is wrong in two of
# them within a year.
#
# Six months. What a group rewarded last week is what its median should
# describe; a post from a year ago in somebody else's group is storage, not
# evidence. The things a person would actually miss are exempt (see
# retention.py): their own posts, anything saved, anything remixed, and
# everything in the reply pipeline are kept for good.
RETENTION_MONTHS = 6

PRO_FEATURES = [
    "Scan as much as you like: no total cap",
    "Re-scan as often as you like, so scores stay current",
    "Your own posts, saved posts and remixes kept for good",
    "%d months of everybody else's posts, so the scores describe now" % RETENTION_MONTHS,
]

# The two reply lines here - comments and chats found for you, replies drafted
# in your voice - described features removed in V32.6, and this is the page
# somebody reads before paying.
FREE_FEATURES = [
    "Every feature: Sage, remix, ideas, export",
    "Full outlier scoring and the meadow",
    "What your winners have in common, from your own data",
    "Unlimited groups, pages and profiles",
    "1,000 captured posts",
]


def is_configured():
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def _client():
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


# The live prices for this account, so a fresh deploy bills correctly with
# nothing to configure. A price id is not a secret — it identifies what is
# being sold, and is useless without the secret key that authorises a charge.
#
# The environment still wins when set, which is what makes test mode possible:
# test prices are different objects entirely, and a test key with a live price
# id fails outright.
DEFAULT_PRICES = {
    "month": "price_1U2zlNKAWBo2NxJskmsfzvgs",   # $19 / month
    "year":  "price_1U2zm4KAWBo2NxJssRLfeyyR",   # $190 / year
}


def price_id(interval):
    """The Stripe price to bill, environment first."""
    override = os.environ.get(
        "STRIPE_PRICE_MONTH" if interval == "month" else "STRIPE_PRICE_YEAR"
    )
    return override or DEFAULT_PRICES.get(interval)


def create_checkout_session(user, interval, success_url, cancel_url):
    """Returns (checkout_url, error)."""
    if interval not in PLANS:
        return None, "Unknown billing interval."
    if not is_configured():
        return None, "Billing isn't configured on this instance yet."

    price = price_id(interval)
    if not price:
        return None, (
            "No Stripe price configured for that interval. Set "
            f"STRIPE_PRICE_{'MONTH' if interval == 'month' else 'YEAR'}."
        )

    # Same price ids as every other checkout. The free month is a trial on
    # this session only, so the product catalog and every existing
    # subscription stay exactly as they are.
    metadata = {"user_id": str(user["id"]), "interval": interval}
    subscription_data = None
    trial_days = trial_days_for(user)
    if trial_days:
        metadata["trial_days"] = str(trial_days)
        subscription_data = {
            "trial_period_days": trial_days,
            "trial_settings": {
                "end_behavior": {"missing_payment_method": "cancel"},
            },
            "metadata": {
                "user_id": str(user["id"]),
                "offer": OFFER_CODE,
            },
        }

    try:
        stripe = _client()
        params = dict(
            mode="subscription",
            line_items=[{"price": price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            customer=user.get("stripe_customer_id") or None,
            customer_email=None if user.get("stripe_customer_id") else user["email"],
            # Ties the completed checkout back to an account without trusting
            # anything the browser sends back on the return trip.
            client_reference_id=str(user["id"]),
            metadata=metadata,
            allow_promotion_codes=True,
        )
        if subscription_data:
            params["subscription_data"] = subscription_data
        session = stripe.checkout.Session.create(**params)
        return session.url, None
    except Exception as exc:                      # noqa: BLE001 - surfaced to the user
        return None, f"Stripe rejected the request: {exc}"


def create_portal_session(user, return_url):
    """Stripe's own billing portal — card updates, invoices, cancellation."""
    if not is_configured():
        return None, "Billing isn't configured on this instance yet."
    if not user.get("stripe_customer_id"):
        return None, "No subscription on this account yet."

    try:
        stripe = _client()
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"], return_url=return_url
        )
        return session.url, None
    except Exception as exc:                      # noqa: BLE001
        return None, f"Stripe rejected the request: {exc}"


def verify_webhook(payload, signature):
    """Returns (event, error). Signature verification is mandatory.

    Without it this endpoint is an unauthenticated "make me a subscriber"
    button, since anyone can POST a plausible-looking JSON body to it.
    """
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return None, "STRIPE_WEBHOOK_SECRET is not set — refusing to trust this call."

    try:
        stripe = _client()
        return stripe.Webhook.construct_event(payload, signature, secret), None
    except Exception as exc:                      # noqa: BLE001
        return None, f"Signature check failed: {exc}"


def apply_subscription(user_id, **fields):
    """Write entitlement. Only ever called from a verified webhook."""
    allowed = {
        "plan", "billing_interval", "stripe_customer_id",
        "stripe_subscription_id", "subscription_status", "current_period_end",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    columns = ", ".join(f"{k} = ?" for k in updates)
    with db.get_db() as conn:
        conn.execute(
            f"UPDATE users SET {columns} WHERE id = ?",
            (*updates.values(), user_id),
        )


def user_id_for_customer(customer_id):
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,)
        ).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------- limits


def usage(user_id):
    with db.get_db() as conn:
        sources = conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        posts = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE user_id = ? AND is_demo = 0",
            (user_id,),
        ).fetchone()["n"]
    return {"sources": sources, "posts": posts}


def is_admin(user):
    """Owner of the instance. Never metered, never nagged to upgrade."""
    return bool(user and user.get("is_admin"))


def is_pro(user):
    """Paid access. past_due still counts — losing a card shouldn't lock
    someone out of their own research mid-billing-cycle."""
    if is_admin(user):
        return True
    return bool(
        user
        and user.get("plan") == "pro"
        and user.get("subscription_status") in ("active", "trialing", "past_due")
    )


# Generations funded by the INSTANCE OWNER's key, per rolling 30 days.
#
# Nothing metered generation at all: any signed-up account could produce
# unlimited images, remixes and answers, and where the owner's key was the
# fallback, unlimited meant unlimited on the owner's card with no way to
# notice until the bill.
#
# Deliberately generous. This is a runaway guard, not a second pricing tier —
# a free user who hits it is using the product hard, which is the outcome the
# free tier is for.
AI_LIMITS = {"free": 40, "pro": 600}


def ai_allowed(user, key_source):
    """Returns (allowed, reason). Only meters calls the owner pays for.

    `key_source` comes from sage.get_config(): "saved" when the user supplied
    their own key, "environment" when the instance owner's is being used.
    Somebody spending their own money is nobody else's problem, so they are
    never metered — metering them would be charging rent on their own petrol.
    """
    if key_source != "environment":
        return True, None
    if is_admin(user):
        return True, None

    import db
    used = db.ai_calls_this_month(user["id"])
    cap = AI_LIMITS["pro"] if is_pro(user) else AI_LIMITS["free"]
    if used < cap:
        return True, None

    if is_pro(user):
        return False, (
            "You've used %d generations this month, which is the ceiling on "
            "the shared key. Add your own API key in Settings and there is no "
            "limit at all." % cap
        )
    return False, (
        "Free covers %d generations a month on the shared key and you've "
        "reached it. Upgrade, or add your own API key in Settings. With your "
        "own key there is no limit." % cap
    )


# Runaway guards, NOT a product limit.
#
# Nothing rate-limited ingest at all: a looping extension, a retry storm or a
# bad build could write until the disk filled, and the first symptom would have
# been every account's captures failing at once. A real scan of a group sends
# tens to a few hundred posts, so these are an order of magnitude above normal
# use — anybody who notices them has something wrong, not something big.
INGEST_PER_REQUEST = 1000
INGEST_PER_HOUR = 10000


def ingest_burst(user_id, incoming, counted=None):
    """Whether this batch is within the hourly ceiling.

    Returns (room, used) — `room` is how many of `incoming` may be stored, and
    is never negative. The caller stores that many and reports the rest as not
    stored, which is the same shape as the existing per-post failure reporting:
    a batch is never silently dropped whole.
    """
    import db
    used = db.posts_ingested_since(user_id, hours=1) if counted is None else counted
    room = max(INGEST_PER_HOUR - used, 0)
    return min(int(incoming), room), used


def capture_room(user):
    """How many more posts this account may store, or None when uncapped.

    capture_allowed answers "may they capture at all", which is checked once
    before a batch — so an account sitting on 999 of 1,000 posts could send a
    batch of 800 and keep every one of them. Measured: 1,799 posts on a
    1,000-post plan. The cap has to be applied to the BATCH, not just to the
    moment before it, or the number on the pricing page is decoration and the
    one thing the paid tier sells is given away.
    """
    if is_admin(user) or is_pro(user):
        return None
    return max(FREE_LIMITS["posts"] - usage(user["id"])["posts"], 0)


def capture_allowed(user):
    """Returns (allowed, reason). Enforced at ingest, where it actually bites."""
    if is_admin(user) or is_pro(user):
        return True, None

    counts = usage(user["id"])

    # Post count is the hard stop and must be tested first. Checked after the
    # source limit it would never fire: once one group exists every later call
    # returns "existing_only" and short-circuits past this.
    if counts["posts"] >= FREE_LIMITS["posts"]:
        return False, (
            f"Free covers {FREE_LIMITS['posts']:,} posts and you've reached it. "
            "Upgrade and keep scanning. There's no total cap on Pro."
        )

    return True, None
