"""What works in a group — and everything it refuses to say.

The risk in this feature is not a crash, it is a confident sentence nobody
derived from anything. So most of this is about silence:

  thin sample   under five posts on a side, no finding
  small gap     under 1.3x, no finding
  unmeasured    posts whose engagement never extracted take no part — they are
                unknown, not zero
  samples       demo rows never produce advice
  medians       one viral post cannot carry a category
  cross-group   across groups, posts are compared to their own group's median,
                so the biggest group cannot decide the answer
  no clocks     there is no timing claim anywhere in the output

Run: python tests/patterns.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import patterns  # noqa: E402

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def post(n, likes, kind="photo", body="A post with words in it", demo=0,
         read=1, source=1):
    return {"id": n, "source_id": source, "item_type": "post", "post_type": kind,
            "likes": likes, "comments": 0, "shares": 0, "body": body,
            "is_demo": demo, "engagement_read": read,
            "posted_at": "2026-09-20 12:00:00"}


def kinds(result):
    return {f["kind"] for f in result["findings"]}


def main():
    print("a clear difference is reported")
    posts = ([post(i, 100, "photo") for i in range(6)] +
             [post(100 + i, 20, "text") for i in range(6)])
    result = patterns.findings(posts)
    check("format is found", "format" in kinds(result), True)
    found = [f for f in result["findings"] if f["kind"] == "format"][0]
    check("photos win", found["winner"], "Photos")
    check("  over text", found["loser"], "Text-only posts")
    check("  by the median ratio", found["ratio"], 5.0)
    check("the sample is both sides", found["sample"], 12)
    check("it reads as a sentence",
          found["sentence"], "Photos do 5.0× as well as text-only posts here.")
    check("and counts every post it looked at", result["measured"], 12)

    print()
    print("what it will not say")
    thin = ([post(i, 100, "photo") for i in range(4)] +
            [post(100 + i, 20, "text") for i in range(9)])
    check("four photos are not a pattern", "format" in kinds(patterns.findings(thin)), False)

    close = ([post(i, 22, "photo") for i in range(6)] +
             [post(100 + i, 20, "text") for i in range(6)])
    check("a 1.1x gap is noise", "format" in kinds(patterns.findings(close)), False)

    one_viral = ([post(0, 9000, "photo")] + [post(i, 5, "photo") for i in range(1, 6)] +
                 [post(100 + i, 20, "text") for i in range(6)])
    # The median ignores it, so the honest answer here is that TEXT wins — the
    # thing that must not happen is one 9000-reaction post making photos the
    # recommendation.
    viral_fmt = [f for f in patterns.findings(one_viral)["findings"]
                 if f["kind"] == "format"]
    check("one viral post cannot carry a category",
          viral_fmt and viral_fmt[0]["winner"], "Text-only posts")

    unread = ([post(i, 100, "photo") for i in range(6)] +
              [post(100 + i, 0, "text", read=0) for i in range(6)])
    check("unmeasured posts take no part",
          "format" in kinds(patterns.findings(unread)), False)
    check("  and are not counted as measured", patterns.findings(unread)["measured"], 6)

    demo = ([post(i, 100, "photo", demo=1) for i in range(6)] +
            [post(100 + i, 20, "text", demo=1) for i in range(6)])
    check("sample data produces no advice", patterns.findings(demo)["findings"], [])
    check("  and measures nothing", patterns.findings(demo)["measured"], 0)

    print()
    print("questions, statements and length")
    asked = ([post(i, 100, body="Anyone know a good roofer?") for i in range(6)] +
             [post(100 + i, 20, body="Here is a thing that happened.") for i in range(6)])
    shape = [f for f in patterns.findings(asked)["findings"] if f["kind"] == "shape"]
    check("a question split is found", bool(shape), True)
    check("  and names the winner", shape[0]["winner"], "Posts that ask a question")

    long_body = "word " * 100
    lengths = ([post(i, 100, body="Short and to the point.") for i in range(6)] +
               [post(100 + i, 20, body=long_body) for i in range(6)])
    length = [f for f in patterns.findings(lengths)["findings"] if f["kind"] == "length"]
    check("a length split is found", bool(length), True)
    check("  short wins here", length[0]["winner"].startswith("Short posts"), True)

    print()
    print("no finding mentions a time of day")
    every = patterns.findings(posts)["findings"] + patterns.findings(asked)["findings"]
    words = " ".join(f["sentence"] for f in every).lower()
    check("nothing about hours, evenings or days",
          any(w in words for w in ("pm", "am", "evening", "morning", "monday", "o'clock")),
          False)

    print()
    print("across groups, the biggest group does not decide")
    # Group 1 is large and posts photos that do ordinarily there; group 2 is
    # small and its text posts are the ones beating their own group.
    big = ([post(i, 1000, "photo", source=1) for i in range(9)] +
           [post(50 + i, 1000, "text", source=1) for i in range(1)])
    small = ([post(200 + i, 10, "photo", source=2) for i in range(9)] +
             [post(300 + i, 90, "text", source=2) for i in range(6)])
    across = patterns.findings(big + small, across=True)
    fmt = [f for f in across["findings"] if f["kind"] == "format"]
    check("a format finding is still possible", bool(fmt), True)
    if fmt:
        check("  and it is the relatively better format that wins",
              fmt[0]["winner"], "Text-only posts")
    raw = patterns.findings(big + small)
    raw_fmt = [f for f in raw["findings"] if f["kind"] == "format"]
    check("raw engagement would have said the opposite",
          raw_fmt and raw_fmt[0]["winner"], "Photos")

    print()
    print("the pages that show it")
    import logging, shutil, tempfile
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    import db, auth
    import app as appmod
    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("pat@example.com", "a-long-enough-pass", "patty")
    uid = user["id"]
    with db.get_db() as conn:
        sid = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) VALUES (?, 'g1', 'group', 'Bakers')",
            (uid,)).lastrowid
        for i in range(6):
            conn.execute(
                "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, post_type, "
                "posted_at, is_demo, item_type, engagement_read) VALUES "
                "(?, ?, ?, 'A photo post here', 100, 'photo', datetime('now','-2 days'), 0, 'post', 1)",
                (uid, "ph-%d" % i, sid))
        for i in range(6):
            conn.execute(
                "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, post_type, "
                "posted_at, is_demo, item_type, engagement_read) VALUES "
                "(?, ?, ?, 'A text post here', 20, 'text', datetime('now','-2 days'), 0, 'post', 1)",
                (uid, "tx-%d" % i, sid))
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    group_page = client.get("/groups/%d" % sid).get_data(as_text=True)
    check("the group page says what works there",
          "What works in this group" in group_page, True)
    check("  with the ratio", "5.0×" in group_page, True)
    play = client.get("/playbook").get_data(as_text=True)
    check("the playbook leads with their own numbers",
          "What works in your groups" in play, True)
    check("  and explains the cross-group comparison",
          "own group's" in " ".join(play.split()), True)
    # The playbook is behind the login, so there is no signed-out case to
    # worry about — the guard in the template is belt and braces.
    anon = appmod.app.test_client()
    check("signed out, the playbook asks for a login",
          anon.get("/playbook").status_code, 302)
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("findings only where there is something to find")
    return 0


if __name__ == "__main__":
    sys.exit(main())
