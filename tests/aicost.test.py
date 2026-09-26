"""What the AI actually costs, per feature.

`ai_usage` held a kind and a timestamp, so "what does a remix cost us" had no
answer anywhere while every feature ran on the dearest model available. A Pro
account may spend 600 owner-funded calls a month against a $19 subscription and
nobody could say whether that was five dollars or fifty.

  prices        both SDK shapes are read, cached input is a discount, and an
                unpriced model is assumed dear rather than free
  attached      a cost lands on the row _ai_gate created for this request
  own key       nothing is recorded for somebody spending their own key
  harmless      a provider that returns no usage, a renamed field, no request
                at all — none of it may break a generation
  visible       /admin reports cost per feature, and says how many calls it
                could not price instead of counting them as zero

Run: python tests/aicost.test.py
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


class Usage:
    """An Anthropic-shaped usage object."""
    def __init__(self, i=0, o=0, cached=0):
        self.input_tokens = i
        self.output_tokens = o
        self.cache_read_input_tokens = cached


class OpenAIUsage:
    def __init__(self, i=0, o=0):
        self.prompt_tokens = i
        self.completion_tokens = o


class Response:
    def __init__(self, usage, model=None):
        self.usage = usage
        if model:
            self.model = model


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"
    os.environ["ANTHROPIC_API_KEY"] = "shared-key-for-the-owner"

    import db
    import auth
    import aicost
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    user, _ = auth.create_user("spender@example.com", "a-long-enough-pass", "spender")
    uid = user["id"]

    print("the arithmetic")
    # 1M in + 1M out on Opus 5 is $5 + $25.
    check("opus input and output",
          aicost.dollars("claude-opus-5", 1_000_000, 1_000_000), 30.0)
    check("sonnet is cheaper",
          aicost.dollars("claude-sonnet-5", 1_000_000, 1_000_000), 12.0)
    check("haiku cheaper still",
          aicost.dollars("claude-haiku-4-5", 1_000_000, 1_000_000), 6.0)
    # Cached input is already inside input_tokens, so it is priced as a
    # discount on part of it rather than added on top.
    full = aicost.dollars("claude-opus-5", 1_000_000, 0)
    discounted = aicost.dollars("claude-opus-5", 1_000_000, 0, cached_tokens=1_000_000)
    check("cached input costs a tenth", (full, discounted), (5.0, 0.5))
    check("an unknown model is assumed dear, not free",
          aicost.dollars("some-new-model", 1_000_000, 0) > 0, True)
    check("images are priced per picture, not per token",
          aicost.dollars("gpt-image-1", images=2), 0.08)
    check("nothing at all costs nothing", aicost.dollars("claude-opus-5"), 0.0)

    print()
    print("both SDK shapes are understood")
    check("anthropic", aicost._tokens(Usage(100, 50, 20)), (100, 50, 20))
    check("openai", aicost._tokens(OpenAIUsage(100, 50)), (100, 50, 0))
    check("a shape with nothing useful", aicost._tokens(object()), (0, 0, 0))

    print()
    print("the cost lands on the row this request created")
    client = appmod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    with appmod.app.test_request_context("/api/remix/1"):
        from flask import session, g
        session["user_id"] = uid
        blocked = appmod._ai_gate("remix")
        check("the gate allows it", blocked, None)
        check("  and recorded a row", bool(getattr(g, "ai_usage_id", None)), True)
        aicost.note(Response(Usage(3000, 900, 0)), "claude-opus-5")

    rows = db.ai_cost_by_kind(30)
    check("one feature is listed", [r["kind"] for r in rows], ["remix"])
    check("  with its call", rows[0]["calls"], 1)
    check("  its tokens", (rows[0]["input_tokens"], rows[0]["output_tokens"]),
          (3000, 900))
    check("  and a real cost",
          rows[0]["cost"], aicost.dollars("claude-opus-5", 3000, 900))
    check("nothing is unpriced", rows[0]["unpriced"], 0)
    check("the per-account table carries cost too",
          db.ai_usage_summary()[0]["cost"] > 0, True)

    print()
    print("somebody on their own key is not our accounting")
    import sage
    with appmod.app.test_request_context("/api/remix/1"):
        from flask import session, g
        session["user_id"] = uid
        sage.set_setting("ai_key_anthropic", "their-own-key")
        appmod._ai_gate("remix")
        check("no row is created", getattr(g, "ai_usage_id", None), None)
        aicost.note(Response(Usage(9_000_000, 9_000_000)), "claude-opus-5")
    check("and the totals did not move",
          db.ai_cost_by_kind(30)[0]["calls"], 1)
    with appmod.app.test_request_context("/"):
        from flask import session
        session["user_id"] = uid
        sage.set_setting("ai_key_anthropic", "")

    print()
    print("bookkeeping never breaks a generation")
    # Each of these used to be a plausible way to turn a working feature into a
    # 500 the moment a provider changed a field name.
    aicost.note(None, "claude-opus-5")                  # nothing to read
    aicost.note(Response(None), "claude-opus-5")        # a response with no usage
    aicost.note(Response(object()), "claude-opus-5")    # a shape we do not know
    aicost.note(Response(Usage(1, 1)), None)            # no model given
    check("none of it raised", True, True)
    check("and none of it invented a row", db.ai_cost_by_kind(30)[0]["calls"], 1)

    print()
    print("an unpriced call is shown, not counted as free")
    with appmod.app.test_request_context("/api/graphic"):
        from flask import session
        session["user_id"] = uid
        appmod._ai_gate("graphic")               # recorded, never noted
    rows = {r["kind"]: r for r in db.ai_cost_by_kind(30)}
    check("the graphic call is listed", rows["graphic"]["calls"], 1)
    check("  as unpriced", rows["graphic"]["unpriced"], 1)
    check("  and contributes no invented cost", rows["graphic"]["cost"], 0)

    print()
    print("the admin page shows the money")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (uid,))
    html = client.get("/admin").get_data(as_text=True)
    check("there is a cost column", "Tokens in / out" in html, True)
    check("  with a total", "on the shared key, last 30 days" in html, True)
    check("  and the unpriced call is called out", "unpriced" in html, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("every generation now says what it cost")
    return 0


if __name__ == "__main__":
    sys.exit(main())
