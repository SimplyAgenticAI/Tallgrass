"""Asking Sage for a graphic gets a graphic.

Reported plainly: "If i ask Sage to generate a graphic it does not." The
generator had existed for months behind a button on a post, and the one place
people actually ask for things was not wired to it — so the answer described a
picture in detail and no picture ever arrived.

Two things are tested, and the second is the one that matters commercially.

The detector has to be right in BOTH directions. A missed ask is the bug being
fixed. A false positive is worse: it spends four cents of somebody's allowance
drawing a picture they did not want, every time they ask a question with the
word "graphic" in it. So "what would a good graphic be?" must stay words.

And the draw must never be kicked off by a request nobody is reading — a
cancelled stream, or an answer that errored and has nothing to illustrate.

Run: python tests/sagepic.test.py
"""
import os
import re
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


# An instruction to draw. The phrasings people actually type.
ASKS = [
    "make me a graphic for the bees post",
    "can you generate an image for this?",
    "design a poster for my best post",
    "generate a graphic",
    "I need a thumbnail made",
    "Make a meme out of my top post",
    "build me a visual for the bee post please",
    "create an illustration of that",
]

# Questions about pictures, which are answered in words.
NOT_ASKS = [
    "what would a good graphic be?",
    "which graphic concept should I use?",
    "suggest a visual for this",
    "describe an image that would work",
    "thoughts on a graphic for this?",
    "how is my engagement?",
    "what should I post about this week?",
    "give me three hooks for my next post",
    "rewrite the caption",
    "",
    None,
]


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    import sage
    import app

    print("reading the ask")
    for text in ASKS:
        check("draws: %s" % text, sage.wants_picture(text), True)
    for text in NOT_ASKS:
        check("answers in words: %r" % text, sage.wants_picture(text), False)

    # The note that changes the answer's shape. Without it the model writes the
    # whole concept out and then the picture says all of it again, better.
    check("the answer is asked to be a caption, not a concept",
          "one or two sentences" in sage.PICTURE_NOTE, True)

    # ------------------------------------------------------------- the stream
    c = app.app.test_client()
    tok = re.search(r'name="csrf_token" value="([^"]+)"',
                    c.get("/register").get_data(as_text=True)).group(1)
    c.post("/register", data={"email": "pic@example.com",
                              "password": "hunter2hunter2",
                              "password_confirm": "hunter2hunter2",
                              "csrf_token": tok}, follow_redirects=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"',
                     c.get("/account").get_data(as_text=True)).group(1)

    def events(message, answer="A bee on a sunflower, close up.", fail=False):
        """Run the stream with the model stubbed out, and parse what it sent."""
        sent = {}

        def fake_stream(messages):
            sent["last"] = messages[-1]["content"]
            if fail:
                yield {"type": "error", "error": "Rate limited by Anthropic"}
                return
            yield {"type": "delta", "text": answer}
            yield {"type": "done", "text": answer}

        was = sage.ask_stream
        was_configured = app.remix.graphic_configured
        sage.ask_stream = fake_stream
        app.remix.graphic_configured = lambda: True
        try:
            body = c.post("/api/sage/stream", json={"message": message},
                          headers={"X-CSRF-Token": csrf}).get_data(as_text=True)
        finally:
            sage.ask_stream = was
            app.remix.graphic_configured = was_configured

        out = [json.loads(line[6:]) for line in body.splitlines()
               if line.startswith("data: ")]
        return out, sent.get("last", "")

    print()
    print("the stream says what to draw")
    out, asked = events("make me a graphic for the bees post")
    pics = [e for e in out if e["type"] == "picture"]
    check("one picture event", len(pics), 1)
    if pics:
        check("  it carries the answer as the scene",
              "sunflower" in pics[0]["body"], True)
        check("  and the request as the art direction",
              "bees post" in pics[0]["ask"], True)
        check("  and says whether a key is configured",
              pics[0]["configured"], True)
    check("  it arrives after the words", out[-1]["type"], "picture")
    check("the model was told a picture is coming",
          "one or two sentences" in asked, True)

    # ------------------------------------------------------- the image brief
    #
    # Reported: a graphic asked for "for a group" came out generic and nothing
    # to do with that group's posts. Two causes, both in what the generator was
    # handed. The chat sentence was passed as art direction, and _graphic_prompt
    # puts instructions first under "where they conflict, THEY WIN" — so "make
    # me a graphic for the Vibe Coding group" outranked every rule about showing
    # a real specific scene while containing no art direction at all. And the
    # subject was Sage's two-sentence caption, which describes no scene.
    #
    # So Sage writes the brief on a last SCENE line, and that is what gets
    # illustrated.
    print()
    print("Sage art-directs it")
    SCENE = ("A macro photograph of a single honeybee on a sunflower head, "
             "side-on, early morning light raking across the petals, shallow "
             "depth of field, pollen visible on its legs.")
    answer = ("Bees on a sunflower, shot close. It fits because the posts that "
              "win in that group are all close-up nature moments.\n\nSCENE: " + SCENE)
    out, asked = events("make me a graphic for the Vibe Coding group",
                        answer=answer)
    pics = [e for e in out if e["type"] == "picture"]
    check("the brief is what gets illustrated", len(pics), 1)
    if pics:
        check("  the scene is the subject", pics[0]["body"], SCENE)
        check("  the chat sentence is NOT passed as art direction",
              pics[0]["ask"], "")
        check("  and the brief is not left in the subject twice",
              "SCENE" in pics[0]["body"], False)

    # What the operator sees, and what comes back next turn.
    deltas = "".join(e.get("text", "") for e in out if e["type"] == "delta")
    check("the raw answer did carry the brief", "SCENE:" in deltas, True)
    import db
    with db.get_db() as conn:
        stored = conn.execute(
            "SELECT content FROM sage_messages WHERE role = 'assistant' "
            "ORDER BY id DESC LIMIT 1").fetchone()["content"]
    check("  but the transcript keeps only the prose",
          "SCENE" in stored, False)
    check("  which is still the whole answer",
          stored.endswith("close-up nature moments."), True)

    # The page cuts it too, because the server only sees the whole answer at
    # the end and the chat is painted a word at a time.
    js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "static", "js", "outlier.js"), encoding="utf-8").read()
    check("the page hides the brief while streaming",
          "withoutBrief(streamed)" in js, True)

    # Splitting, directly.
    check("a missing brief leaves the answer alone",
          sage.split_picture_brief("Just prose."), ("Just prose.", ""))
    check("  and an empty answer does not throw",
          sage.split_picture_brief(None), ("", ""))
    check("  the marker is matched case-insensitively",
          sage.split_picture_brief("Words.\nscene: a field")[1], "a field")

    # Sage can only art-direct for a room it can see the pictures of.
    print()
    print("Sage is shown what the winning graphics looked like")
    check("the brief asks for the group's real subjects",
          "not from the idea of the group" in sage.PICTURE_NOTE, True)
    check("  and forbids the abstractions that made these generic",
          "glowing orbs" in sage.PICTURE_NOTE, True)
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "sage.py"), encoding="utf-8").read()
    context = src[src.index("def build_context"):src.index("def _context_block")]
    check("the context carries what a post's picture looked like",
          "image_looked_like" in context, True)
    check("  and the words set into it",
          "image_words" in context, True)

    # Every group carries its own best post, however many groups there are.
    # top_outliers is the best 25 posts in the ACCOUNT, so on an account with a
    # dozen rooms a given room can contribute nothing to it — and a graphic
    # asked for "for that group" then had the group's name, its median, and no
    # example of anything that has ever worked in it.
    tok3 = re.search(r'name="csrf_token" value="([^"]+)"',
                     c.get("/account").get_data(as_text=True)).group(1)
    api = c.post("/api/account/connect",
                 headers={"X-CSRF-Token": tok3}).get_json()["api_key"]
    for which in range(2):
        c.post("/api/capture",
               json={"source": {"fb_id": "g%d" % which, "kind": "group",
                                "name": "Room %d" % which, "url": "u"},
                     "posts": [{"fb_post_id": "r%d-%d" % (which, i),
                                "body": "Room %d post %d about beekeeping" % (which, i),
                                # The second room is the quieter one, so the
                                # account-wide top 25 is all room 0.
                                "likes": (900 if which == 0 else 12) + i,
                                "comments": 4, "shares": 2, "item_type": "post",
                                "author_name": "A", "engagement_read": 1,
                                "posted_at": "2026-10-01T10:00:00"}
                               for i in range(12)]},
               headers={"X-Outlier-Key": api})

    with db.get_db() as conn:
        user = dict(conn.execute(
            "SELECT * FROM users WHERE email = 'pic@example.com'").fetchone())
    was_user = app.auth.current_user
    app.auth.current_user = lambda: user
    try:
        with app.app.test_request_context("/sage"):
            ctx = sage.build_context()
    finally:
        app.auth.current_user = was_user

    rooms = {s["name"]: s for s in ctx["sources"]}
    check("both rooms are described", "Room 0" in rooms and "Room 1" in rooms, True)
    for name in ("Room 0", "Room 1"):
        if name in rooms:
            best = rooms[name].get("best_post") or {}
            check("%s carries its own best post" % name,
                  (best.get("body") or "").startswith(name + " post"), True)
    # The quiet room contributes nothing to the account-wide top list, which is
    # exactly the case this exists for.
    quiet_in_top = any(p["source"] == "Room 1" for p in ctx["top_outliers"])
    check("  and the quiet room is absent from the account-wide top list",
          quiet_in_top, False)

    out, asked = events("how is my engagement?")
    check("a normal question draws nothing",
          [e for e in out if e["type"] == "picture"], [])
    check("  and the model is not sent the picture note",
          "one or two sentences" in asked, False)

    # An answer that failed has nothing to illustrate, and charging for a
    # picture on top of a failed answer is the worst of both.
    out, _ = events("make me a graphic for the bees post", fail=True)
    check("an errored answer draws nothing",
          [e for e in out if e["type"] == "picture"], [])

    # Nothing in the stream path calls the generator. The draw happens on the
    # next request, through /api/graphic, so the allowance check and the cost
    # record stay in the one place that already does them.
    print()
    print("the drawing itself stays in one place")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "app.py"), encoding="utf-8").read()
    stream = src[src.index("def api_sage_stream"):src.index("def api_sage_clear")]
    check("the stream route never generates an image itself",
          "generate_graphic" in stream, False)
    check("  it reports whether a key exists, so the page can say so",
          "graphic_configured" in stream, True)

    js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "static", "js", "outlier.js"), encoding="utf-8").read()
    check("the page handles the picture event",
          'event.type === "picture"' in js, True)
    check("  by drawing through /api/graphic",
          'post("/api/graphic"' in js, True)
    check("  with a download link on the result",
          "tallgrass-graphic.png" in js, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("asked for a graphic, gets a graphic")
    return 0


if __name__ == "__main__":
    sys.exit(main())
