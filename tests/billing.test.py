"""Entitlement, and the ways it could be given away.

billing.py is live in production and had no test. The risk here is not that
Stripe stops working — Stripe will tell you. It is that the app grants paid
access, or admin, to somebody who did not buy it: a webhook trusted without a
signature, a field written that was never meant to be writable, a cancelled
subscription that keeps working.

Nothing here talks to Stripe. Every path tested is one that decides
entitlement locally, which is exactly the set that fails silently.

Run: python tests/billing.test.py
"""
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

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
    for key in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                "STRIPE_PRICE_MONTH", "STRIPE_PRICE_YEAR",
                "BLACK_FRIDAY_OFFER", "BLACK_FRIDAY_ENDS"):
        os.environ.pop(key, None)

    import db
    import billing

    db.init_db()
    with db.get_db() as conn:
        conn.execute("INSERT INTO users (id, email, password_hash, is_admin) "
                     "VALUES (1, 'free@example.com', 'x', 0)")
        conn.execute("INSERT INTO users (id, email, password_hash, is_admin) "
                     "VALUES (2, 'boss@example.com', 'x', 1)")
        conn.execute("INSERT INTO sources (id, user_id, fb_id, kind, name) "
                     "VALUES (1, 1, 'group:g', 'group', 'A Group')")

    def user(uid):
        with db.get_db() as conn:
            return dict(conn.execute(
                "SELECT * FROM users WHERE id = ?", (uid,)).fetchone())

    print("a webhook is not trusted without a signing secret")
    # Without verification this endpoint is an unauthenticated
    # "make me a subscriber" button.
    event, error = billing.verify_webhook(b'{"type":"checkout.session.completed"}',
                                          "t=1,v1=whatever")
    check("no event is returned", event, None)
    check("and it says why", "STRIPE_WEBHOOK_SECRET" in error, True)

    print()
    print("entitlement writes are restricted to entitlement fields")
    # apply_subscription builds its UPDATE from keyword arguments. If the
    # allow-list ever stops filtering, a webhook payload becomes a way to write
    # any column on the users table — is_admin being the one that matters.
    billing.apply_subscription(
        1,
        plan="pro",
        subscription_status="active",
        is_admin=1,                       # not an entitlement field
        email="attacker@example.com",     # nor this
        password_hash="replaced",         # nor this
    )
    after = user(1)
    check("the plan was set", after["plan"], "pro")
    check("the status was set", after["subscription_status"], "active")
    check("is_admin was NOT granted", bool(after["is_admin"]), False)
    check("the email was NOT changed", after["email"], "free@example.com")
    check("the password hash was NOT changed", after["password_hash"], "x")

    print()
    print("an update with nothing writable in it writes nothing")
    before = user(1)
    billing.apply_subscription(1, is_admin=1, email="x@y.z")
    check("the row is untouched", user(1), before)

    print()
    print("paid access follows the subscription status")
    check("active is pro", billing.is_pro(user(1)), True)
    for status, expected in (("trialing", True), ("past_due", True),
                             ("canceled", False), ("unpaid", False),
                             ("incomplete_expired", False), (None, False)):
        billing.apply_subscription(1, subscription_status=status)
        label = status or "no status"
        check("%s -> %s" % (label, "pro" if expected else "not pro"),
              billing.is_pro(user(1)), expected)

    print()
    print("losing the plan loses access even if the status looks fine")
    billing.apply_subscription(1, plan="free", subscription_status="active")
    check("plan free is not pro", billing.is_pro(user(1)), False)

    print()
    print("the instance owner is never metered")
    boss = user(2)
    check("an admin reads as pro without paying", billing.is_pro(boss), True)
    check("and is admin", billing.is_admin(boss), True)
    check("a free user is not admin", billing.is_admin(user(1)), False)
    check("nobody is not admin", billing.is_admin(None), False)
    check("nobody is not pro", billing.is_pro(None), False)

    print()
    print("the free tier stops at its post limit")
    limit = billing.FREE_LIMITS["posts"]

    def seed(n, is_demo=0, start=0):
        with db.get_db() as conn:
            for i in range(n):
                conn.execute(
                    "INSERT INTO posts (user_id, fb_post_id, source_id, body, "
                    "post_type, posted_at, likes, comments, shares, "
                    "engagement_read, captured_at, is_demo, item_type) "
                    "VALUES (1, ?, 1, 'b', 'text', '2026-08-01T00:00:00', "
                    "10, 0, 0, 1, '2026-08-01T00:00:00', ?, 'post')",
                    ("fb-%d-%d" % (is_demo, start + i), is_demo))

    seed(limit - 1)
    allowed, reason = billing.capture_allowed(user(1))
    check("one under the limit is allowed", allowed, True)
    check("with no reason given", reason, None)

    seed(1, start=limit)
    allowed, reason = billing.capture_allowed(user(1))
    check("at the limit it stops", allowed, False)
    check("and names the limit", str(limit) in reason.replace(",", ""), True)

    print()
    print("sample data does not count against the limit")
    check("the real count is the limit", billing.usage(1)["posts"], limit)
    seed(50, is_demo=1, start=9000)
    check("demo posts are excluded", billing.usage(1)["posts"], limit)

    print()
    print("upgrading lifts the stop immediately")
    billing.apply_subscription(1, plan="pro", subscription_status="active")
    allowed, _ = billing.capture_allowed(user(1))
    check("a pro account captures past the free limit", allowed, True)
    check("and so does the owner", billing.capture_allowed(user(2))[0], True)

    print()
    print("checkout refuses what it cannot bill")
    url, error = billing.create_checkout_session(user(1), "fortnight", "/ok", "/no")
    check("an unknown interval is rejected", url, None)
    check("  by name", "interval" in error.lower(), True)
    url, error = billing.create_checkout_session(user(1), "month", "/ok", "/no")
    check("no Stripe key means no checkout", url, None)
    check("  and it says billing is not configured",
          "isn't configured" in error, True)
    check("is_configured agrees", billing.is_configured(), False)

    print()
    print("the billing portal needs an actual customer")
    url, error = billing.create_portal_session(user(1), "/back")
    check("unconfigured is refused first", url, None)
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_not_a_real_key"
    url, error = billing.create_portal_session(user(1), "/back")
    check("a user with no Stripe customer is refused", url, None)
    check("  and told why", "No subscription", error[:15], )
    os.environ.pop("STRIPE_SECRET_KEY", None)

    print()
    print("customers map back to accounts")
    billing.apply_subscription(1, stripe_customer_id="cus_abc123")
    check("a known customer resolves", billing.user_id_for_customer("cus_abc123"), 1)
    check("an unknown one does not", billing.user_id_for_customer("cus_nope"), None)
    check("and neither does nothing", billing.user_id_for_customer(None), None)

    print()
    print("prices come from the environment when it is set")
    check("a built-in price is used by default",
          billing.price_id("month"), billing.DEFAULT_PRICES["month"])
    os.environ["STRIPE_PRICE_MONTH"] = "price_from_env"
    check("the environment wins", billing.price_id("month"), "price_from_env")
    check("  without affecting the other interval",
          billing.price_id("year"), billing.DEFAULT_PRICES["year"])
    os.environ.pop("STRIPE_PRICE_MONTH", None)
    check("an unknown interval has no price", billing.price_id("fortnight"), None)

    print()
    print("the Black Friday promo ends itself, and a flag overrides the date")
    during = datetime(2026, 11, 27, 18, tzinfo=timezone.utc)
    after = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
    check("built-in end is Cyber Monday, Pacific midnight",
          billing.offer_ends_at(), billing._DEFAULT_OFFER_END)
    check("it is on during Black Friday", billing.offer_active(during), True)
    check("it is off at the end instant", billing.offer_active(after), False)
    os.environ["BLACK_FRIDAY_OFFER"] = "0"
    check("BLACK_FRIDAY_OFFER=0 hides it during the sale",
          billing.offer_active(during), False)
    os.environ["BLACK_FRIDAY_OFFER"] = "1"
    check("BLACK_FRIDAY_OFFER=1 keeps it up after the sale",
          billing.offer_active(after), True)
    os.environ.pop("BLACK_FRIDAY_OFFER", None)
    os.environ["BLACK_FRIDAY_ENDS"] = "2026-11-24"
    check("a date runs through the end of that UTC day",
          billing.offer_ends_at(),
          datetime(2026, 11, 25, tzinfo=timezone.utc))
    os.environ["BLACK_FRIDAY_ENDS"] = "2026-12-05T15:00:00Z"
    check("a timestamp is an exclusive end",
          billing.offer_ends_at(),
          datetime(2026, 12, 5, 15, tzinfo=timezone.utc))
    os.environ["BLACK_FRIDAY_ENDS"] = "not-a-date"
    check("a bad date falls back to the built-in end",
          billing.offer_ends_at(), billing._DEFAULT_OFFER_END)
    os.environ.pop("BLACK_FRIDAY_ENDS", None)

    print()
    print("only an offer signup's first checkout gets the free month")
    os.environ["BLACK_FRIDAY_OFFER"] = "1"
    check("the live code is accepted", billing.normalize_offer("BlackFriday"),
          "blackfriday")
    check("anything else is ignored", billing.normalize_offer("holiday"), None)
    check("the stamp is written", billing.claim_offer(1, "blackfriday"), True)
    check("it is on the account", user(1)["signup_offer"], "blackfriday")
    check("a second stamp does not overwrite", billing.claim_offer(1, "blackfriday"), False)
    check("offer account, no subscription: 30 days",
          billing.trial_days_for(user(1)), 30)
    billing.apply_subscription(1, stripe_subscription_id="sub_existing")
    check("an existing subscription is not given another trial",
          billing.trial_days_for(user(1)), 0)
    billing.apply_subscription(1, stripe_subscription_id=None)
    check("clearing the subscription restores the one trial",
          billing.trial_days_for(user(1)), 30)
    check("a normal account gets no trial",
          billing.trial_days_for(user(2)), 0)
    os.environ["BLACK_FRIDAY_OFFER"] = "0"
    check("the promo being off rejects a new stamp",
          billing.claim_offer(2, "blackfriday"), False)
    check("and the code normalizes to nothing",
          billing.normalize_offer("blackfriday"), None)
    # The account that already signed up keeps the trial after the banner goes.
    check("an account already stamped still has 30 days",
          billing.trial_days_for(user(1)), 30)
    os.environ["BLACK_FRIDAY_OFFER"] = "1"

    print()
    print("checkout attaches the trial only on the offer path")
    import stripe as stripe_mod
    captured = {}

    def fake_create(**kwargs):
        captured["kwargs"] = kwargs
        return type("Session", (), {"url": "https://checkout.stripe.test/c/sess"})()

    original_create = stripe_mod.checkout.Session.create
    stripe_mod.checkout.Session.create = fake_create
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_not_a_real_key"
    try:
        offer_user = user(1)
        url, error = billing.create_checkout_session(
            offer_user, "month", "https://example.test/ok", "https://example.test/no")
        sent = captured["kwargs"]
        check("the offer session is created", url, "https://checkout.stripe.test/c/sess")
        check("  with no error", error, None)
        check("  on the existing monthly price",
              sent["line_items"], [{"price": billing.price_id("month"), "quantity": 1}])
        check("  with a 30 day trial",
              sent["subscription_data"]["trial_period_days"], 30)
        check("  and the webhook can see that it was a trial",
              sent["metadata"]["trial_days"], "30")
        check("  a missing card at the end cancels rather than invoicing",
              sent["subscription_data"]["trial_settings"]["end_behavior"]["missing_payment_method"],
              "cancel")
        plain = dict(user(2))
        plain["signup_offer"] = None
        captured.clear()
        url, error = billing.create_checkout_session(
            plain, "month", "https://example.test/ok", "https://example.test/no")
        check("a normal signup still gets a session", bool(url), True)
        check("  with no trial attached",
              "subscription_data" in captured["kwargs"], False)
        check("  and no trial marker",
              "trial_days" in captured["kwargs"]["metadata"], False)
    finally:
        stripe_mod.checkout.Session.create = original_create
        os.environ.pop("STRIPE_SECRET_KEY", None)

    check("checkout metadata marks a trial",
          billing.checkout_is_trial({"metadata": {"trial_days": "30"}}), True)
    check("and a normal checkout is not one",
          billing.checkout_is_trial({"metadata": {"interval": "month"}}), False)
    check("a trial end is used when the period end is absent",
          billing.subscription_period_end(
              {"status": "trialing", "trial_end": 123, "current_period_end": None}),
          123)
    check("a real period end wins",
          billing.subscription_period_end(
              {"status": "active", "current_period_end": 456, "trial_end": 123}),
          456)

    print()
    print("the landing page offers it, and the signup path keeps it")
    os.environ["BLACK_FRIDAY_OFFER"] = "1"
    os.environ["APP_SECRET"] = "test-only-secret"
    os.environ.pop("ADMIN_EMAILS", None)
    import app as appmod

    anon = appmod.app.test_client()
    home = anon.get("/").get_data(as_text=True)
    check("the promo is on the landing page", "on the house." in home, True)
    check("  it names the real monthly price", "$19 a month" in home, True)
    check("  and the CTA is the offer signup",
          'href="/register?offer=blackfriday"' in home, True)
    os.environ["BLACK_FRIDAY_OFFER"] = "0"
    hidden = anon.get("/welcome").get_data(as_text=True)
    check("BLACK_FRIDAY_OFFER=0 removes it", "on the house." in hidden, False)
    check("  and the offer link with it", "offer=blackfriday" in hidden, False)
    os.environ["BLACK_FRIDAY_OFFER"] = "1"

    def token_from(client, path):
        html = client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    reg = appmod.app.test_client()
    form = reg.get("/register?offer=blackfriday").get_data(as_text=True)
    check("register explains the free month",
          "Pro is free for 30 days" in form, True)
    check("  and carries the offer through the form",
          'name="offer" value="blackfriday"' in form, True)
    made = reg.post("/register?offer=blackfriday", data={
        "email": "bf@example.com",
        "username": "blackfriday",
        "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery",
        "offer": "blackfriday",
        "csrf_token": token_from(reg, "/register?offer=blackfriday"),
    }, follow_redirects=False)
    check("offer signup redirects to pricing", made.status_code, 302)
    check("  at /pricing", made.headers["Location"].endswith("/pricing"), True)
    priced = reg.get("/pricing").get_data(as_text=True)
    check("pricing starts the free month", "Start my free month" in priced, True)
    check("  and tells the checkout it is a trial",
          'data-trial-days="30"' in priced, True)

    plain_reg = appmod.app.test_client()
    ordinary = plain_reg.post("/register", data={
        "email": "ordinary@example.com",
        "username": "ordinary",
        "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery",
        "csrf_token": token_from(plain_reg, "/register"),
    }, follow_redirects=False)
    check("a normal signup still lands in the app", ordinary.status_code, 302)
    check("  at the feed", ordinary.headers["Location"].endswith("/"), True)
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT signup_offer FROM users WHERE email = ?",
            ("ordinary@example.com",)).fetchone()
    check("  with no offer stamped", row["signup_offer"], None)

    os.environ.pop("BLACK_FRIDAY_OFFER", None)
    os.environ.pop("APP_SECRET", None)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("entitlement is only granted to those who bought it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
