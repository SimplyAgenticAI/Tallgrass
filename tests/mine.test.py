"""Your own posts, found and scored against the group.

  suggested  the name comes from comments the extension marked as yours,
             full names only
  matched    posts by that name are found, case and spacing ignored
  honest     no multiple without a baseline; demo posts are nobody's
  scoped     another account's identical name and posts never leak in
  page       Settings renders the list, and saving a name sticks

Run: python tests/mine.test.py
"""
import logging
import os
import shutil
import sys
import tempfile

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
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import auth
    import mine
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()

    def make_user(email, name):
        user, _ = auth.create_user(email, "a-long-enough-pass", name)
        return user

    def add_group(user_id, group, posts, demo=0):
        """posts: list of (author, likes)."""
        with db.get_db() as conn:
            sid = conn.execute(
                "INSERT INTO sources (user_id, fb_id, kind, name) VALUES (?, ?, 'group', ?)",
                (user_id, "g:%s:%s" % (user_id, group), group)).lastrowid
            ids = []
            for i, (author, likes) in enumerate(posts):
                aid = conn.execute("SELECT id FROM authors WHERE name = ?", (author,)).fetchone()
                aid = aid[0] if aid else conn.execute(
                    "INSERT INTO authors (name) VALUES (?)", (author,)).lastrowid
                ids.append(conn.execute(
                    "INSERT INTO posts (user_id, fb_post_id, source_id, author_id, body, likes, "
                    "posted_at, is_demo, item_type, engagement_read) VALUES "
                    "(?, ?, ?, ?, ?, ?, datetime('now', '-1 days'), ?, 'post', 1)",
                    (user_id, "%s-%s-%d" % (user_id, group, i), sid, aid,
                     "A post by %s" % author, likes, demo)).lastrowid)
        return sid, ids

    def add_my_comment(user_id, author):
        with db.get_db() as conn:
            pid = conn.execute(
                "INSERT INTO comment_posts (user_id, post_key) VALUES (?, ?)",
                (user_id, "k-%s-%s" % (user_id, author))).lastrowid
            conn.execute(
                "INSERT INTO post_comments (user_id, post_id, comment_key, author, body, is_mine) "
                "VALUES (?, ?, ?, ?, 'thanks!', 1)", (user_id, pid, "c-%s" % author, author))

    jane = make_user("jane@example.com", "janeuser")
    others = [("Other Person %d" % i, 10) for i in range(9)]
    _, ids = add_group(jane["id"], "Bakers", others + [("Jane Smith", 60)])
    add_group(jane["id"], "Tiny", [("Jane Smith", 30), ("Bob Ray", 5)])
    add_group(jane["id"], "Samples", [("Jane Smith", 99)] * 3, demo=1)

    print("the name is suggested from your own comments")
    check("nothing to suggest before any comments", mine.suggested_names(jane["id"]), [])
    add_my_comment(jane["id"], "Jane")          # a first name alone proves nothing
    add_my_comment(jane["id"], "Jane Smith")
    check("the full name is suggested, the bare first name is not",
          mine.suggested_names(jane["id"]), ["Jane Smith"])
    names, confirmed = mine.names_for(jane["id"])
    check("used until confirmed", (names, confirmed), (["Jane Smith"], False))

    print()
    print("your posts are found and scored honestly")
    s = mine.summary(jane["id"])
    check("two real posts, sample ones never count", len(s["posts"]), 2)
    check("across two groups", s["groups"], 2)
    check("the breakout comes first with its multiple",
          (s["posts"][0]["id"], s["posts"][0]["outlier_multiple"]), (ids[-1], 6.0))
    check("the thin group's post has no multiple", s["posts"][1]["outlier_multiple"], None)
    check("only scored posts are counted as beating the group", (s["beat"], s["scored"]), (1, 1))

    print()
    print("saving the name")
    saved = mine.set_names(jane["id"], "  jane   SMITH , Jane Smith,\nJ. Smith ")
    check("spacing tidied and duplicates dropped", saved, ["jane SMITH", "J. Smith"])
    check("case does not matter for matching", len(mine.my_posts(jane["id"])), 2)
    names, confirmed = mine.names_for(jane["id"])
    check("now confirmed", confirmed, True)

    print()
    print("another account never leaks in")
    other = make_user("other@example.com", "otheruser")
    add_group(other["id"], "Elsewhere", others + [("Jane Smith", 500)])
    check("jane still has two", len(mine.my_posts(jane["id"])), 2)
    check("other has none without a name", mine.my_posts(other["id"]), [])

    print()
    print("the settings page")
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = jane["id"]
    page = client.get("/settings")
    html = page.get_data(as_text=True)
    check("renders", page.status_code, 200)
    check("shows the found count", "Found <b>2</b> posts" in html, True)
    check("shows the multiple", "6.0×" in html, True)
    check("and says when there is not enough data", "Needs more data" in html, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("your posts, found and scored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
