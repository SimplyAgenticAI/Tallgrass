"""Opening lines that actually worked, taken from the operator's own posts.

Every tool in this category ships the same nine hooks to every customer —
"Nobody talks about this, but...", "The advice everyone gives is wrong" — a
list somebody wrote once, offered as though it were evidence. It is a guess,
and it is the same guess for everybody.

This app has the thing those lists stand in for: real posts that really did
outperform, in the reader's own groups, with a measured multiple attached. So
a hook here is not an archetype. It is the first line of a post that beat its
group's median by 12.4x, shown with the 12.4x.

Where a group has no scored posts there is nothing to learn from, and the
archetypes below are offered instead — labelled as generic, because a
suggestion nobody's data supports must not look like one it does.
"""

import re

# Below this a hook is a fragment rather than an opening, and above it the
# "opening line" is really the whole post.
MIN_HOOK_CHARS = 18
MAX_HOOK_CHARS = 120

# Only posts that actually cleared their group's median are worth copying. At
# 1.0x a post is by definition typical, and its opening line is evidence of
# nothing.
MIN_MULTIPLE = 1.5


# Shapes worth naming, checked in order — the first match wins, so the more
# specific patterns come first. Deliberately conservative: an opening that
# matches nothing is labelled "opening" rather than forced into a category it
# does not fit.
_SHAPES = (
    ("question", re.compile(r"\?\s*$")),
    ("how-to", re.compile(r"^\s*how\b", re.I)),
    ("list", re.compile(r"^\s*\d+\s+\w+", re.I)),
    ("warning", re.compile(r"^\s*(before|don'?t|stop|never|avoid|warning)\b", re.I)),
    # "Three years ago" is written out far more often than "3 years ago", and
    # matching only digits missed the commonest way people open a story.
    ("story", re.compile(
        r"^\s*((\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an)\s+"
        r"(years?|months?|weeks?|days?)\s+ago"
        r"|last\s+(year|month|week|night)"
        r"|when\s+i\b|i\s+(used\s+to|once|remember))", re.I)),
    ("contrarian", re.compile(
        r"\b(nobody|everyone|everybody|most\s+people|myth|actually\s+wrong|"
        r"wrong\s+about|unpopular)\b", re.I)),
    ("number", re.compile(r"^\s*[$£€]?\d")),
)

SHAPE_LABELS = {
    "question": "Question",
    "how-to": "How-to",
    "list": "List",
    "warning": "Warning",
    "story": "Story",
    "contrarian": "Contrarian",
    "number": "Number",
    "opening": "Opening",
}


# Offered only when a group has nothing to learn from, and always labelled as
# generic. These are the industry's standard archetypes and they are included
# so the page still works on day one — not because anything here says they
# work for this reader.
GENERIC_HOOKS = (
    {"shape": "curiosity", "text": "Nobody talks about this, but…"},
    {"shape": "contrarian", "text": "The advice everyone repeats is backwards."},
    {"shape": "story", "text": "A year ago I was doing this completely wrong."},
    {"shape": "question", "text": "Why does nobody mention this part?"},
    {"shape": "warning", "text": "Before you try this, read the next line."},
    {"shape": "list", "text": "Three things that changed how I work."},
)


def _shape_of(text):
    for name, pattern in _SHAPES:
        if pattern.search(text):
            return name
    return "opening"


def opening_line(body):
    """The first real line of a post, or None if there isn't one.

    Takes the first sentence when the post opens with prose, and the first
    line when it opens with a short standalone hook — which is how most posts
    that do well are actually written.
    """
    text = " ".join((body or "").split())
    if not text:
        return None

    # A short first line IS the hook, and splitting it on punctuation would
    # cut it in half. Only when the post actually breaks there, though —
    # otherwise a one-paragraph post has no "first line" distinct from its
    # first sentence, and taking the whole paragraph returns the post rather
    # than its opening.
    raw = (body or "").strip()
    first_line = raw.split("\n")[0].strip()
    if "\n" in raw and MIN_HOOK_CHARS <= len(first_line) <= MAX_HOOK_CHARS:
        candidate = first_line
    else:
        # Otherwise take the first sentence, keeping its punctuation.
        match = re.match(r"^(.{%d,%d}?[.!?])(\s|$)" % (MIN_HOOK_CHARS, MAX_HOOK_CHARS),
                         text)
        candidate = match.group(1) if match else text[:MAX_HOOK_CHARS].strip()

    candidate = " ".join(candidate.split())
    if len(candidate) < MIN_HOOK_CHARS:
        return None

    # A "hook" with no spaces is a token, not an opening line.
    if " " not in candidate:
        return None

    return candidate


def from_posts(scored, limit=8):
    """Hooks worth copying, best first.

    `scored` is the output of outliers.score_posts. Only posts carrying a real
    baseline are considered: without one there is no multiple, and a hook with
    no number behind it is exactly the guess this module exists to replace.
    """
    seen = set()
    found = []

    for post in scored:
        if not post.get("has_baseline"):
            continue
        multiple = post.get("outlier_multiple")
        if multiple is None or multiple < MIN_MULTIPLE:
            continue
        # Words lifted out of a graphic are not an opening line the author
        # typed, so they are not a hook anybody can reuse.
        if post.get("body_from_image"):
            continue

        text = opening_line(post.get("body"))
        if not text:
            continue

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)

        found.append({
            "text": text,
            "shape": _shape_of(text),
            "multiple": multiple,
            "post_id": post.get("id"),
            "source_name": post.get("source_name"),
            "generic": False,
        })

    found.sort(key=lambda h: h["multiple"], reverse=True)
    return found[:limit]


def for_source(scored, limit=8):
    """What the picker should show: real hooks, or clearly-marked generics.

    Never mixed. A list that is half evidence and half archetype invites the
    reader to treat the archetypes as evidence too, which is the exact
    confusion the labelling exists to prevent.
    """
    real = from_posts(scored, limit=limit)
    if real:
        return {"hooks": real, "generic": False}

    return {
        "hooks": [dict(h, multiple=None, post_id=None, generic=True)
                  for h in GENERIC_HOOKS],
        "generic": True,
    }
