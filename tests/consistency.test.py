"""Every page must tell the same story about the same source.

These are the bugs this file exists to prevent, all reported from real use:
  - the groups list and the group's own page disagreeing about whether it
    was scored, because three places computed "readable" three ways;
  - "still climbing", a claim about a trend nothing measures;
  - "comment - comment" on every comment card;
  - comments opening a page with no way back to what they replied to.

Run: python tests/consistency.test.py
"""
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
    for path in ["/", "/groups", "/library", "/opportunities", "/write", "/settings",
                 "/capture", "/account", "/sage", "/playbook", "/?kind=comment",
                 "/?tier=breakout", "/?page=2", "/groups/1?kind=comment"]:
        check("GET %s" % path, c.get(path).status_code, 200)

    # Public pages, fetched with no session at all. "/" is in the list above
    # signed IN, so without this the landing page nobody has an account yet is
    # the one page never rendered by a test.
    anon = app.app.test_client()
    for path in ["/", "/welcome", "/login", "/register", "/pricing"]:
        check("GET %s signed out" % path, anon.get(path).status_code, 200)

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
