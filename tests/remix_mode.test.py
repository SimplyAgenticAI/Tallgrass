"""Remix stays on the subject — the bees test.

A post about bees travelling came back as a post about satellites in the sky,
and a graphic to match. Nothing had gone wrong at the model: with a brand
profile filled in, the prompt said the operator's own subject was the one that
mattered and the original was "only where the mechanic came from", and the
closing line asked for a mechanic "that would still work if every noun changed".

So both jobs now exist, and the one the button looks like it does is the
default. These assert the prompt TEXT, which is where the behaviour actually
lives — no model is called.

  default      no mode named anywhere means another post like this one
  like_this    the subject is locked, and a brand profile cannot unlock it
  my_business  the old behaviour still available, still explicit
  graphic      "like the original" keeps the original's SUBJECT, not just its
               palette — it used to be told to change it
  no lettering the image prompt still forbids text unless it is asked for

Run: python tests/remix_mode.test.py
"""
import io
import json
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []

BEES = {
    "id": 1,
    "source_name": "Beekeepers of the Midwest",
    "body": "Don't be alarmed when you see this — it's just bees travelling. "
            "They cluster on a branch while the scouts look for a new home.",
    "likes": 400, "comments": 90, "shares": 30,
    "post_type": "photo",
    "outlier_multiple": 6.1,
    "image_url": "https://example.com/bees.jpg",
    "image_desc": "A dense clump of honeybees hanging from a tree branch",
}


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
    import remix
    import sage
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("bee@example.com", "a-long-enough-pass", "beekeeper")
    uid = user["id"]

    def prompt(mode=None, post=None):
        """The remix prompt, built inside a request as the real thing is."""
        with appmod.app.test_request_context("/"):
            from flask import session
            session["user_id"] = uid
            kwargs = {} if mode is None else {"mode": mode}
            text, error = remix._remix_prompt(post or BEES, **kwargs)
        assert not error, error
        return text

    # The profile that caused it: an operator who writes about something else
    # entirely. Saved for real, because reading it is what the prompt does.
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        sage.set_setting("brand_offer", "AI automation for small businesses")
        sage.set_setting("brand_audience", "overworked agency owners")
        # The remix panel only renders with a provider key saved, and the
        # saved-variant markup only exists once there is a remix to show.
        sage.set_setting("ai_key_anthropic", "test-key-not-used")

    print("the default is another post like this one")
    default = prompt()
    check("the mode needs no argument", remix.DEFAULT_MODE, remix.LIKE_THIS)
    check("the subject is locked", "KEEP THE SUBJECT OF THE ORIGINAL" in default, True)
    check("the group is named as where it goes back",
          "Beekeepers of the Midwest" in default, True)
    check("and 'every noun changed' is gone",
          "every noun changed" in default, False)
    check("the brand profile is demoted to voice",
          "must NOT change what the post is about" in default, True)
    check("  while still being shown", "AI automation" in default, True)
    check("nothing invites a transposition",
          "only where the mechanic came from" in default, False)

    print()
    print("the angles keep the subject too")
    check("same_hook says so",
          "keep what the post is about" in remix.ANGLES_LIKE_THIS["same_hook"], True)
    check("the old wording is not used in this mode",
          "change the story, the examples and the specifics" in default.lower(), False)
    check("the angle names are the same in both modes",
          sorted(remix.ANGLES_LIKE_THIS), sorted(remix.ANGLES))

    print()
    print("the old behaviour is still there, now by choice")
    business = prompt(remix.MY_BUSINESS)
    check("it transposes onto their world",
          "only where the mechanic came from" in business, True)
    check("and asks for the transferable mechanic",
          "every noun changed" in business, True)
    check("the subject lock is absent",
          "KEEP THE SUBJECT OF THE ORIGINAL" in business, False)

    print()
    print("a bad or missing mode falls back to the safe one")
    for value in (None, "", "nonsense", "LIKE_THIS", 7):
        check("  %r -> like_this" % (value,), remix.clean_mode(value), remix.LIKE_THIS)
    check("the request sends the mode through",
          "KEEP THE SUBJECT OF THE ORIGINAL" in prompt("not-a-mode"), True)

    print()
    print("the graphic follows the original's subject")
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        brief = remix.original_graphic_brief(BEES)
        echoed = remix._graphic_prompt(
            "Don't be alarmed", body=BEES["body"], like_original=brief)
        plain = remix._graphic_prompt("Don't be alarmed", body=BEES["body"])
    check("there is a brief to echo", bool(brief), True)
    check("it is told to match the subject matter",
          "its subject matter" in echoed, True)
    check("  and said plainly",
          "If the original showed bees, this one shows bees." in echoed, True)
    check("it is no longer told to change the subject",
          "a different subject within the same idea" in echoed, False)
    check("it is still a sibling, not a copy", "not a copy" in echoed, True)
    check("the independent graphic echoes nothing",
          "MAKE ANOTHER ONE LIKE" in plain, False)
    check("lettering is still banned by default",
          "ABSOLUTELY NO text" in echoed and "ABSOLUTELY NO text" in plain, True)
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        asked = remix._graphic_prompt("A hook", body="Words",
                                      instructions="put the headline in the image")
    check("  unless the operator asks for it",
          "ABSOLUTELY NO text" in asked, False)

    # The post and a saved remix, needed by everything below.
    with db.get_db() as conn:
        sid = conn.execute(
            "INSERT INTO sources (user_id, fb_id, kind, name) "
            "VALUES (?, 'g1', 'group', 'Beekeepers')", (uid,)).lastrowid
        pid = conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, post_type, "
            "image_url, posted_at, is_demo, item_type, engagement_read) VALUES "
            "(?, 'bee-1', ?, ?, 400, 'photo', 'https://example.com/b.jpg', "
            "datetime('now','-1 days'), 0, 'post', 1)",
            (uid, sid, BEES["body"])).lastrowid
        conn.execute(
            "INSERT INTO remixes (post_id, user_id, angle, output, model) "
            "VALUES (?, ?, 'same_hook', ?, 'test')",
            (pid, uid, json.dumps({
                "why_it_worked": "It reassured people about an alarming sight.",
                "variants": [{"angle": "same_hook",
                              "body": "Don't panic if you see this cluster.",
                              "hook": "Don't panic if you see this cluster."}],
            })))
    print()
    print("reading the original picture does not depend on Facebook's link")
    # The whole point: image_url is signed and expires in a day or two, so any
    # post older than that could never be echoed. images.py has been keeping a
    # downscaled copy of every picture it has shown all along.
    import images
    seen = {}

    def never_fetch(url):
        seen["asked_facebook"] = True
        raise Exception("410 Gone - that is what an expired link does")

    real_fetch = remix._fetch_image
    remix._fetch_image = never_fetch
    try:
        # A real JPEG, written by the same library images.py uses to store
        # them, rather than hand-rolled bytes it would reject.
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (120, 90, 30)).save(buf, "JPEG")
        tiny = buf.getvalue()
        stored, store_error = images.store(pid, tiny)
        check("a picture the app has shown is on disk", bool(stored), True)

        described = {"called_with": None}

        def fake_vision(raw, media_type, key):
            described["called_with"] = (len(raw), media_type)
            return "a close photograph of a swarm on a branch"

        # Only the network is faked; everything that decides WHERE the bytes
        # come from is the real code.
        with appmod.app.test_request_context("/"):
            from flask import session
            session["user_id"] = uid
            with db.get_db() as conn:
                row = dict(conn.execute(
                    "SELECT * FROM posts WHERE id = ?", (pid,)).fetchone())
            text, err = remix.describe_original_graphic(row)
        check("it did not ask Facebook", seen.get("asked_facebook"), None)
        # No AI key that works here, so the call itself fails — what matters is
        # that it got as far as HAVING the bytes rather than refusing early.
        check("and the failure is not about an expired link",
              "links expire" in (err or ""), False)
    finally:
        remix._fetch_image = real_fetch

    print()
    print("when the picture really is gone, it still makes something")
    with db.get_db() as conn:
        gone_id = conn.execute(
            "INSERT INTO posts (user_id, fb_post_id, source_id, body, likes, post_type, "
            "image_url, posted_at, is_demo, item_type, engagement_read) VALUES "
            "(?, 'bee-gone', ?, 'Bees again, no picture left', 90, 'photo', "
            "'https://scontent.example.com/expired.jpg', datetime('now','-40 days'), "
            "0, 'post', 1)", (uid, sid)).lastrowid
    client_gone = appmod.app.test_client()
    with client_gone.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = "known-token"
    made = {"like_original": "unset"}

    def fake_graphic(hook, instructions="", body="", like_original=None, caption_text=""):
        made["like_original"] = like_original
        return "data:image/png;base64,AAAA", None

    real_graphic = remix.generate_graphic
    real_describe = remix.describe_original_graphic
    remix.generate_graphic = fake_graphic
    remix.describe_original_graphic = lambda post: (None, "Facebook's links expire.")
    try:
        r = client_gone.post("/api/graphic", json={
            "hook": "Don't be alarmed", "body": "Bees again, no picture left",
            "like_post_id": gone_id,
        }, headers={"X-CSRF-Token": "known-token"})
        data = r.get_json()
        check("it does not refuse", r.status_code, 200)
        check("a picture comes back", bool(data.get("image")), True)
        check("it says what it could not do",
              "illustrates the words instead" in (data.get("note") or ""), True)
        check("  and did not pretend to echo anything", made["like_original"], None)
    finally:
        remix.generate_graphic = real_graphic
        remix.describe_original_graphic = real_describe

    print()
    print("the page offers the choice, with the subject-keeping one first")
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/post/%d" % pid).get_data(as_text=True)
    check("both modes are offered", html.count('name="remix-mode"'), 2)
    check("the subject-keeping one is preselected",
          'value="like_this"\n               checked' in html
          or 'value="like_this" checked' in html
          or ('like_this' in html.split("checked")[0].split('name="remix-mode"')[-1]), True)
    check("the graphic that follows the original is offered",
          "Graphic like the original" in html, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("a remix of the post, not of the subject")
    return 0


if __name__ == "__main__":
    sys.exit(main())
