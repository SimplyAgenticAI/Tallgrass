"""Every page must tell the same story about the same source.

These are the bugs this file exists to prevent, all reported from real use:
  - the groups list and the group's own page disagreeing about whether it
    was scored, because three places computed "readable" three ways;
  - "still climbing", a claim about a trend nothing measures;
  - "comment - comment" on every comment card;
  - comments opening a page with no way back to what they replied to.

Run: python tests/consistency.test.py
"""
import json
import os
import re
import sys
import tempfile
import shutil
from datetime import datetime, timedelta, timezone

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
    os.environ["ADMIN_EMAILS"] = "t@example.com"
    import app

    c = app.app.test_client()
    tok = re.search(r'name="csrf_token" value="([^"]+)"',
                    c.get("/register").get_data(as_text=True)).group(1)
    c.post("/register", data={"email": "t@example.com",
                              "password": "hunter2hunter2",
                              "password_confirm": "hunter2hunter2",
                              "csrf_token": tok}, follow_redirects=True)
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"',
                     c.get("/account").get_data(as_text=True)).group(1)
    key = c.post("/api/account/connect",
                 headers={"X-CSRF-Token": tok2}).get_json()["api_key"]

    def iso(hours):
        return (datetime.now(timezone.utc) -
                timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")

    def send(fb_id, name, posts):
        return c.post("/api/capture",
                      json={"source": {"fb_id": fb_id, "kind": "group",
                                       "name": name, "url": "u"},
                            "posts": posts},
                      headers={"X-Outlier-Key": key})

    # Lots captured, almost none readable — the shape that produced the
    # contradiction between the list and the page.
    send("group:broken", "Broken Group",
         [{"fb_post_id": "b%d" % i, "body": "Post %d" % i,
           "likes": (120 if i < 3 else 0), "comments": 0, "shares": 0,
           "item_type": "post", "author_name": "A", "posted_at": iso(200),
           "engagement_read": (1 if i < 3 else 0)} for i in range(40)])

    send("group:good", "Good Group",
         [{"fb_post_id": "g%d" % i, "body": "Healthy %d" % i,
           "likes": 90 + i * 11, "comments": 6, "shares": 3,
           "item_type": "post", "author_name": "B", "engagement_read": 1,
           "posted_at": iso(5 if i == 0 else 300)} for i in range(12)] +
         [{"fb_post_id": "cm%d" % i, "body": "A reply number %d" % i,
           "likes": 8 + i * 4, "comments": 0, "shares": 0,
           "item_type": "comment", "author_name": "C", "engagement_read": 1,
           "posted_at": iso(280), "parent_fb_id": "g0"} for i in range(5)])

    groups = c.get("/groups").get_data(as_text=True)

    # Which id "Good Group" landed on, rather than assuming it is 2.
    #
    # It was 2 for as long as a new account started empty. Signup now seeds the
    # sample set first, so the three sample groups take the low ids and the two
    # captured here follow — and every hardcoded /groups/2 below was quietly
    # asserting about a sample group instead. Looked up by name, this test
    # stops caring how many sources exist before its own.
    good_id = re.search(
        r'data-source-id="(\d+)"[^>]*>(?:(?!data-source-id).)*?Good Group',
        groups, re.S)
    assert good_id, "Good Group is not on the groups page"
    good = good_id.group(1)

    listed = re.findall(
        r'data-countup="(\d+)">\d+</span><span class="s-unit">%</span>', groups)

    print("consistency between the list and each group's own page")
    for sid in sorted(set(re.findall(r'data-source-id="(\d+)"', groups))):
        page = c.get("/groups/" + sid).get_data(as_text=True)
        pct = re.search(r'>(\d+)% readable<', page)
        check("group %s reports a readable %% on its own page" % sid, bool(pct))
        if pct:
            check("group %s: that %% also appears in the list" % sid,
                  pct.group(1) in listed)
        check("group %s: no stale 'at least 8 posts' copy" % sid,
              "at least 8 posts" not in page, True)

    print("claims the app is not entitled to make")
    feed = c.get("/").get_data(as_text=True)
    check("no 'still climbing' anywhere", "still climbing" not in feed)
    check("age is stated as a fact instead",
          bool(re.search(r"posted [\w ]+ ago", feed)))
    check("comments are not labelled twice",
          feed.count('class="type-chip">comment<'), 0)

    print("comments are not presented as a ranking")
    # Facebook previews one or two replies per post, chosen by "Most
    # relevant", so any ranked comments view would be ranking Facebook's
    # picks. Capture was removed; older rows must not resurface as a feed.
    feed_html = c.get("/").get_data(as_text=True)
    check("no Comments tab on the feed", "kind=comment" not in feed_html)
    check("no 'Comments captured' headline stat",
          "Comments captured" not in feed_html)
    check("?kind=comment does not open a ranked comment feed",
          "Top comments" not in c.get("/?kind=comment").get_data(as_text=True))
    check("no Comments tab on a group page",
          "kind=comment" not in c.get("/groups/" + good).get_data(as_text=True))

    # Rows captured by older versions still render on their post's page, and
    # must say what they are.
    detail_pages = [c.get("/post/" + p).get_data(as_text=True)
                    for p in re.findall(r'data-post-id="(\d+)"',
                                        c.get("/groups/" + good).get_data(as_text=True))]
    with_replies = [d for d in detail_pages if "preview comment" in d]
    check("legacy replies still show on their post", len(with_replies) > 0)
    if with_replies:
        check("and are labelled as Facebook's selection, not a ranking",
              "not the top ones" in with_replies[0])

    print("every page still renders")
    for path in ["/", "/groups", "/library", "/write", "/settings",
                 "/capture", "/account", "/sage", "/playbook", "/?kind=comment",
                 "/?tier=breakout", "/?page=2", "/groups/1?kind=comment"]:
        check("GET %s" % path, c.get(path).status_code, 200)

    # Public pages, fetched with no session at all. "/" is in the list above
    # signed IN, so without this the landing page nobody has an account yet is
    # the one page never rendered by a test.
    anon = app.app.test_client()
    for path in ["/", "/welcome", "/login", "/register", "/pricing"]:
        check("GET %s signed out" % path, anon.get(path).status_code, 200)

    print()
    print("the public pages can be found, and the app cannot")
    robots = anon.get("/robots.txt")
    robots_text = robots.get_data(as_text=True)
    check("robots.txt", robots.status_code, 200)
    check("  names the sitemap",
          "Sitemap: https://tallgrassapp.com/sitemap.xml" in robots_text, True)
    check("  keeps crawlers out of the API", "Disallow: /api/" in robots_text, True)
    check("  and out of the signed-in app", "Disallow: /groups" in robots_text, True)
    sitemap = anon.get("/sitemap.xml").get_data(as_text=True)
    check("sitemap.xml", anon.get("/sitemap.xml").status_code, 200)
    for loc in ("https://tallgrassapp.com/",
                "https://tallgrassapp.com/welcome",
                "https://tallgrassapp.com/pricing",
                "https://tallgrassapp.com/privacy",
                "https://tallgrassapp.com/terms"):
        check("  lists %s" % loc, loc in sitemap, True)
    check("  and not the app", "https://tallgrassapp.com/groups" in sitemap, False)
    check("  nor an account page", "https://tallgrassapp.com/login" in sitemap, False)
    llms = anon.get("/llms.txt")
    llms_text = llms.get_data(as_text=True)
    check("llms.txt", llms.status_code, 200)
    check("  says what the landing says", "median" in llms_text.lower(), True)
    check("  and does not invent a reply queue",
          "messenger" not in llms_text.lower(), True)

    def has_public_meta(html):
        return all(bit in html for bit in (
            "<title>", 'name="description"', 'rel="canonical"',
            'property="og:title"', 'name="twitter:card"'))

    home = anon.get("/").get_data(as_text=True)
    welcome = anon.get("/welcome").get_data(as_text=True)
    check("the landing page has a title, description, canonical and cards",
          has_public_meta(home), True)
    check("  canonical is the public home, not this host",
          'href="https://tallgrassapp.com/"' in home, True)
    check("  /welcome canonicalises to the same page",
          'href="https://tallgrassapp.com/"' in welcome, True)
    check("  and no longer sells a reply queue",
          "waiting on a reply" not in home, True)
    for path in ("/pricing", "/privacy", "/terms"):
        html = anon.get(path).get_data(as_text=True)
        check("%s has a title, description, canonical and cards" % path,
              has_public_meta(html), True)
        check("  %s canonical stays on that page" % path,
              ('href="https://tallgrassapp.com%s"' % path) in html, True)
    pricing = anon.get("/pricing").get_data(as_text=True)
    check("pricing does not sell reply drafting",
          "Messenger" not in pricing and "reply drafting" not in pricing, True)
    feed = c.get("/").get_data(as_text=True)
    check("the signed-in feed is not tagged as a marketing page",
          'property="og:title"' not in feed and 'rel="canonical"' not in feed, True)

    print()
    print("the homepage sells the store, and more than one kind of group")
    check("Add to Chrome is on the hero and the close", home.count("Add to Chrome") >= 2, True)
    check("each one goes through /go/store", home.count('href="/go/store"') >= 2, True)
    check("signup is still offered", "Get started free" in home, True)
    check("the sample is called Tallgrass feed", "Tallgrass feed" in home, True)
    check("the old sample label is gone", "Outlier feed" not in home, True)
    check("one real estate example remains", "Title &amp; Escrow Pros" in home, True)
    check("a local business group is there too", "Main Street Owners" in home, True)
    check("and a creator group", "Creator Coaching Circle" in home, True)
    check("twitter card is a large image", "summary_large_image" in home, True)
    check("og:image points at the brand image",
          'property="og:image"' in home and "og.png" in home, True)
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', home, re.S)
    check("the homepage carries SoftwareApplication JSON-LD", blob is not None, True)
    if blob:
        data = json.loads(blob.group(1))
        prices = sorted(offer["price"] for offer in data["offers"])
        check("offers are Free, Pro monthly and Pro yearly", prices, ["0", "19", "190"])
    check("no FAQ schema without an FAQ section", "FAQPage" not in home, True)

    saved_keys = {}
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if key in os.environ:
            saved_keys[key] = os.environ.pop(key)
    try:
        bare = anon.get("/").get_data(as_text=True)
        reg = anon.get("/register").get_data(as_text=True)
        check("without a server key, the homepage says you bring your own",
              "You bring your own AI key" in bare, True)
        check("register says the same", "You bring your own AI key" in reg, True)
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-only"
        hosted = anon.get("/").get_data(as_text=True)
        reg_on = anon.get("/register").get_data(as_text=True)
        check("with a server key, the homepage does not demand one",
              "You bring your own AI key" not in hosted, True)
        check("  and says drafting is included", "AI drafting is included" in hosted, True)
        check("register follows", "You bring your own AI key" not in reg_on, True)
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for key, value in saved_keys.items():
            os.environ[key] = value

    print()
    print("signed-out marketing pages do not wear the app nav")
    for path in ("/pricing", "/privacy", "/terms"):
        html = anon.get(path).get_data(as_text=True)
        check("signed-out %s uses the marketing bar" % path, 'class="lp-bar"' in html, True)
        check("  %s has no app nav" % path, 'class="topnav"' not in html, True)
        check("  %s has no version pill" % path, "version-pill" not in html, True)
    missing = anon.get("/no-such-page-anywhere")
    missing_html = missing.get_data(as_text=True)
    check("an unknown URL is a 404", missing.status_code, 404)
    check("  that says page not found", "Page not found" in missing_html, True)
    check("  and does not pretend it was a missing post",
          "isn't in the database" not in missing_html, True)
    check("  with noindex", 'name="robots" content="noindex"' in missing_html, True)
    check("  and the header", missing.headers.get("X-Robots-Tag"), "noindex")
    check("  marketing bar for a stranger", 'class="lp-bar"' in missing_html, True)
    check("  a way home", ">Home</a>" in missing_html, True)
    check("  and a way to sign in", ">Sign in</a>" in missing_html, True)
    signed_missing = c.get("/no-such-page-anywhere")
    signed_html = signed_missing.get_data(as_text=True)
    check("a signed-in 404 keeps the app nav", 'class="topnav"' in signed_html, True)
    check("  and links back to the feed", "Back to the feed" in signed_html, True)
    check("signed-in pricing keeps the app nav",
          'class="topnav"' in c.get("/pricing").get_data(as_text=True), True)

    priv = anon.get("/privacy").get_data(as_text=True)
    check("live privacy still names Messenger", 'id="messenger"' in priv, True)
    check("live privacy date is unchanged", "16 September 2026" in priv, True)
    check("the 31.0 date is not live", "13 November 2026" not in priv, True)
    was_flag = app.PRIVACY_EXTENSION_31
    app.PRIVACY_EXTENSION_31 = True
    try:
        drafted = anon.get("/privacy").get_data(as_text=True)
    finally:
        app.PRIVACY_EXTENSION_31 = was_flag
    check("the draft drops the Messenger section", 'id="messenger"' not in drafted, True)
    check("the draft drops comment saving", "Save comments" not in drafted, True)
    check("the draft date is the new one", "13 November 2026" in drafted, True)
    check("the draft still says what a scan collects",
          "while a scan is running" in drafted, True)

    ico = anon.get("/favicon.ico")
    apple = anon.get("/apple-touch-icon.png")
    check("favicon.ico is served", ico.status_code, 200)
    check("  as an image", (ico.mimetype or "").startswith("image/"), True)
    check("apple-touch-icon is served", apple.status_code, 200)
    check("  as a png", apple.mimetype, "image/png")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    listing = open(os.path.join(root, "docs", "STORE_LISTING_31.md"), encoding="utf-8").read()
    check("the 31.0 listing ranks against the median", "median" in listing.lower(), True)
    check("  and says the key is yours", "your own" in listing.lower(), True)
    check("  and does not sell comment saving", "Save comments" not in listing, True)
    check("the store zip script is there",
          os.path.isfile(os.path.join(root, "scripts", "package_store_zip.sh")), True)

    plain = app.app.test_client()
    ptok = re.search(r'name="csrf_token" value="([^"]+)"',
                     plain.get("/register").get_data(as_text=True)).group(1)
    plain.post("/register", data={"email": "reader@example.com",
                                  "password": "hunter2hunter2",
                                  "password_confirm": "hunter2hunter2",
                                  "csrf_token": ptok}, follow_redirects=True)
    priced = plain.get("/pricing").get_data(as_text=True)
    check("a free account is not told its group cap is None",
          "/None" not in priced, True)
    check("  and is told the post cap", "of 1,000 posts used" in priced, True)

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    blueprint = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()
    procfile = open(os.path.join(root, "Procfile"), encoding="utf-8").read()
    cmd = "gunicorn app:app --workers 1 --threads 4 --timeout 120"
    check("the blueprint start command is the live one-writer command",
          cmd in blueprint, True)
    check("  health check stays /api/ping",
          "healthCheckPath: /api/ping" in blueprint, True)
    check("  the disk stays 1 GB", "sizeGB: 1" in blueprint, True)
    check("the Procfile matches it", cmd in procfile, True)
    check("  neither file asks for a second worker",
          "--workers 2" not in blueprint and "--workers 2" not in procfile, True)

    # ------------------------------------------------ what /api/ping promises
    #
    # The extension polls this every minute and compares extension_version to
    # its own. Anything the dashboard names here, it is telling a browser it
    # can install — so a hosted dashboard must name the version the Chrome Web
    # Store has approved, never the one sitting in this repo.
    #
    # It reported the repo's manifest to everybody once. The store was on 22.9
    # and the repo had run on to 23.6 through fourteen dashboard-only releases,
    # so every store user's popup showed an update that did not exist, with
    # instructions to sideload it by hand - the exact thing the store listing
    # was published to delete. The versions diverge by design now, and this is
    # what stops them being confused for each other again.
    print()
    print("the ping only advertises versions somebody can actually install")

    was_local = app._is_local_dashboard
    try:
        app._is_local_dashboard = lambda: False
        hosted = anon.get("/api/ping").get_json()
        check("hosted reports the STORE version",
              hosted["extension_version"], app.EXTENSION_STORE_VERSION)
        check("  so a user on the store build is never nagged",
              hosted["extension_version"] == app.EXTENSION_STORE_VERSION, True)

        # Locally the extension is the project folder loaded unpacked, so a
        # newer copy on disk really is installable — reloading the card adopts
        # it. Reporting the store version here would break the dev loop.
        app._is_local_dashboard = lambda: True
        local = anon.get("/api/ping").get_json()
        check("local reports the REPO version",
              local["extension_version"], app._extension_version())
    finally:
        app._is_local_dashboard = was_local

    # The download button serves the repo's zip, so its label has to describe
    # the bytes it hands over — not the store's number.
    check("the zip's own version is still the repo's",
          app._extension_version(), app._manifest_version("0"))

    # ------------------------------------------- the two numbers, in agreement
    #
    # Every check above compares the ping to EXTENSION_STORE_VERSION, so they
    # all passed happily while that constant was three weeks stale: 28.4 went
    # live in the store and the constant still said 22.9. Nothing broke loudly.
    # What it did instead was quiet and expensive — _extension_ahead_of_store
    # concluded a submission was mid-review, so every hosted visitor's install
    # page opened the hand-install section and told them the store copy was
    # behind, which is the Developer-mode route the listing exists to delete.
    #
    # So this asserts the pair is CURRENT, not merely self-consistent.
    #
    # It is meant to fail in exactly one situation: the manifest has been
    # bumped and that package is still in review. That is a real state, and the
    # fix is to put the in-review manifest version in `in_review` below — one
    # deliberate line, which is also the reminder to clear it and bump the
    # constant the day the submission goes live.
    in_review = "31.0"          # in the repo; the store listing is 30.1
    repo_ext = app._extension_version()
    if in_review:
        check("the manifest is the version said to be in review", repo_ext, in_review)
        check("  and the store constant is behind it, as expected",
              app._version_tuple(app.EXTENSION_STORE_VERSION) < app._version_tuple(repo_ext),
              True)
    else:
        check("the store constant matches the extension in this repo "
              "(if a submission is in review, set in_review above)",
              app.EXTENSION_STORE_VERSION, repo_ext)
        # In a request, and against a hosted host name, because that is the
        # only case where the sideload section is ever opened.
        with app.app.test_request_context("/capture", base_url="https://tallgrassapp.com"):
            check("  so the hosted install page does not push a sideload",
                  app._extension_ahead_of_store(), False)

    # Tuples, not floats. 23.10 as a float is smaller than 23.6, and this
    # comparison decides whether the page offers an early copy at all — so
    # the first two-digit patch would have silently switched the offer off.
    check("23.10 is newer than 23.6",
          app._version_tuple("23.10") > app._version_tuple("23.6"), True)
    check("a version equal to the store's is not ahead",
          app._version_tuple("22.9") > app._version_tuple("22.9"), False)
    check("nonsense reads as old rather than raising",
          app._version_tuple("x.y") > app._version_tuple("22.9"), False)

    # ------------------------------------------- the early-access offer
    #
    # Offered only while the repo really is ahead of the approved package —
    # that window is a review wait, and it is the only time a hand install
    # gets somebody something they cannot already have. Shown outside it, it
    # is just the six-step page growing back.
    print()
    print("the manual install is offered only when it gets you something")

    was_store = app.EXTENSION_STORE_VERSION
    try:
        app._is_local_dashboard = lambda: False

        app.EXTENSION_STORE_VERSION = "0.1"        # store far behind
        page = c.get("/capture").get_data(as_text=True)
        check("behind: the early copy is offered",
              "early" in page and "manual-route" in page, True)
        check("  and the doubling hazard is named first",
              "Disable the store copy first" in page, True)

        app.EXTENSION_STORE_VERSION = app._extension_version()   # caught up
        page = c.get("/capture").get_data(as_text=True)
        check("caught up: nothing early is advertised",
              "Get v" in page, False)
        check("  and the hand route is a folded line again",
              "Install it by hand instead" in page, True)

        # A local dashboard has no store copy in the picture at all, so it
        # must never claim one is behind.
        app._is_local_dashboard = lambda: True
        app.EXTENSION_STORE_VERSION = "0.1"
        check("local is never 'ahead of the store'",
              app._extension_ahead_of_store(), False)
    finally:
        app.EXTENSION_STORE_VERSION = was_store
        app._is_local_dashboard = was_local

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all consistency checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
