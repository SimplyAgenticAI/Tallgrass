"""What each AI call actually cost, recorded where it happened.

`ai_usage` counted calls and nothing else — a kind and a timestamp. So the
question "what does a remix cost us" had no answer anywhere in the app, while
every feature ran on the most expensive model available. A free account may
spend 40 owner-funded calls a month and a Pro account 600, and nobody could say
whether 600 of them came to five dollars or fifty against a $19 subscription.

Two rules this module keeps:

  never in the way   recording a cost is bookkeeping. Every path here swallows
                     its own failures: a missing column, a response shape the
                     SDK changed, no request context at all — none of it may
                     cost somebody the generation they just waited for.
  the owner's money  only calls billed to the instance owner's key are
                     recorded, the same test `_ai_gate` already applies.
                     Somebody spending their own key is not our accounting.

Prices are per million tokens and live in one table, because they change and a
number copied into three files is wrong in two of them within a year. Image
models are priced per image instead, which is why they carry a count.
"""

import logging

log = logging.getLogger("tallgrass.aicost")

# Per million tokens, in dollars. Checked against Anthropic's and OpenAI's
# published rates on 2026-09-26 — update here and nowhere else.
PRICES = {
    "claude-opus-5":    {"in": 5.00, "out": 25.00, "cached_in": 0.50},
    "claude-sonnet-5":  {"in": 2.00, "out": 10.00, "cached_in": 0.20},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00,  "cached_in": 0.10},
    "gpt-4o":           {"in": 2.50, "out": 10.00, "cached_in": 1.25},
}

# Dollars per generated image, for the models that charge that way.
IMAGE_PRICES = {
    "gpt-image-1": 0.04,
    "dall-e-3": 0.04,
}

# What an unknown model is assumed to cost, so a model we have not priced yet
# still shows up as money rather than as zero. Deliberately the dearest row:
# an underestimate reads as "this is fine" and that is the wrong way to be
# wrong about a bill.
FALLBACK = {"in": 5.00, "out": 25.00, "cached_in": 0.50}


def _tokens(usage):
    """(input, output, cached) from either SDK's usage object.

    Anthropic reports input_tokens / output_tokens / cache_read_input_tokens;
    OpenAI reports prompt_tokens / completion_tokens. Both are read defensively
    — this is the kind of field that gets renamed.
    """
    def get(*names):
        for name in names:
            value = getattr(usage, name, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    cached = get("cache_read_input_tokens")
    if not cached:
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    return (get("input_tokens", "prompt_tokens"),
            get("output_tokens", "completion_tokens"),
            cached)


def dollars(model, input_tokens=0, output_tokens=0, cached_tokens=0, images=0):
    """What that call cost, in dollars. Never raises."""
    try:
        if images:
            return round(IMAGE_PRICES.get(model, 0.04) * images, 6)
        price = PRICES.get(model or "", FALLBACK)
        # Cached input is billed at the cheaper rate and is already counted in
        # input_tokens by both SDKs, so it is priced as a discount rather than
        # added on top.
        fresh = max(int(input_tokens) - int(cached_tokens), 0)
        return round(
            (fresh * price["in"]
             + int(cached_tokens) * price["cached_in"]
             + int(output_tokens) * price["out"]) / 1_000_000, 6)
    except Exception:                         # noqa: BLE001
        return 0.0


def note(response=None, model=None, usage=None, images=0):
    """Attach the cost of the call that just returned to this request's row.

    Called right after a provider response comes back. Does nothing at all
    unless `_ai_gate` recorded a row for this request, which it only does for
    calls on the owner's key.
    """
    try:
        from flask import g
        row_id = getattr(g, "ai_usage_id", None)
        if not row_id:
            return
        if usage is None and response is not None:
            usage = getattr(response, "usage", None)
        model = model or getattr(response, "model", None) or ""
        if images:
            input_tokens = output_tokens = cached = 0
        elif usage is None:
            return
        else:
            input_tokens, output_tokens, cached = _tokens(usage)

        import db
        db.note_ai_cost(
            row_id, model=str(model)[:60],
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_tokens=cached, images=images,
            cost=dollars(model, input_tokens, output_tokens, cached, images))
    except Exception:                         # noqa: BLE001 - bookkeeping only
        log.debug("could not record AI cost", exc_info=True)
