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
