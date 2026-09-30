"""What the dragonfly knows.

It sits in the meadow on every page, so when somebody taps it, it should have
something worth saying — and the same six sentences on repeat is a mascot, not
help. These are chosen from where the reader is and what their account actually
contains.

Two rules, both borrowed from hooks.py and patterns.py, which exist because the
generic version of this idea is worthless:

  nothing invented   a tip about their data is only offered when the data is
                     there. No "your best post" for somebody who has captured
                     nothing, and no numbers that are not real.
  nothing expensive  this runs on EVERY page load. Everything here is either a
                     fact the page already computed, or one cheap indexed
                     count. Scoring is not done twice for a hint.

Ordered by usefulness to THIS reader, and the client takes them in turn rather
than at random, so the first tap gets the most relevant thing rather than the
luck of the draw.
"""

import outliers

# Evergreen advice, shown once the account is past the stage where a tip about
# getting started would be more use. These are the judgement calls from the
# Playbook, said in one sentence each, because the Playbook is a page nobody is
# told to visit.
CRAFT = [
    "A 4× post you could plausibly have written beats a 28× post you couldn't. "
    "Read down the list for the one that sounds like you.",
    "Ask of any winner: would this still work next month with different "
    "specifics? If it only worked because of the moment, there is nothing in it "
    "to reuse.",
    "The median, not the average — so one viral post in a group can't drag "
    "everything else down to looking ordinary.",
    "Comments and shares are weighted heavier than reactions, because they cost "
    "the reader more than a tap.",
    "A post that did 0.8× is not a failure you should hide from. It is the "
    "clearest thing in the feed: that shape does not work in that room.",
]

# What a particular page is for, said where somebody is standing in it.
BY_PAGE = {
    "feed": "The notch on each card is that group's median. The glow is how far "
            "the post cleared it — so you can see the story without reading a "
            "number.",
    "groups": '"Needs more data" never means a group did badly. It means too '
              "few of its posts could be read to know what normal is there.",
    "write": "Give it an opening line that already worked in that group and it "
             "has something real to build on, rather than inventing a hook.",
    "today": "Nothing here is ever sent for you. Every draft waits for you to "
             "read it, change it, and press the button yourself.",
    "results": "Your own posts are scored against the same medians as everybody "
               "else's, so a 2× here means the same thing it means anywhere.",
    "playbook": "The findings at the top are only from posts in your groups "
                "whose engagement could actually be read. That is why they "
                "appear slowly.",
    "comments": "Answering the oldest waiting comment first is usually worth "
                "more than answering the cleverest one.",
    "library": "Saved posts and remixes are kept for good — they are never aged "
               "out, whatever happens to the rest of a group's history.",
}


def _fact(text, where=None):
    """One tip: the words, and optionally somewhere to go about them.

    A tip that names a group and cannot take you to it is a fact read out at
    you. The client renders `where` as a button on the bubble.
    """
    return {"text": " ".join(str(text).split()), "where": where}


def for_page(active, scores, user, counts=None):
    """Tips for this page and this account, best first.

    `scores` is the list the meadow is already drawn from, so the numbers here
    and the blades agree and nothing is queried twice. `counts` is optional —
    {"posts": n, "waiting": n} — and only used where it is given.
    """
    counts = counts or {}
    posts = counts.get("posts")
    waiting = counts.get("waiting")
    tips = []

    # Where they are stuck comes first: a tip about craft is no use to somebody
    # who has not captured anything yet.
    if not user:
        tips.append(_fact(
            "Everything you see here is scored against the group it came from, "
            "never against a global number."))
    elif posts == 0:
        tips.append(_fact(
            "Nothing of yours is here yet. Open a Facebook group, find the "
            "Tallgrass panel in the corner, press Start, and scroll."))
    elif not scores:
        tips.append(_fact(
            "A group needs about %d posts with readable engagement before "
            "anything can be scored against it. Keep scanning and the numbers "
            "arrive on their own." % outliers.MIN_SAMPLE))
    else:
        best = max(scores)
        if best >= 2:
            tips.append(_fact(
                "Your best captured post so far did %s× the median of its "
                "group. Open it and Write can build on what made it work."
                % round(best, 1)))

    if waiting:
        tips.append(_fact(
            "%d %s waiting on a reply from you. Oldest first is the habit worth "
            "having." % (waiting, "person is" if waiting == 1 else "people are")))

    page_tip = BY_PAGE.get(active or "")
    if page_tip:
        tips.append(_fact(page_tip))

    tips.extend(_fact(t) for t in CRAFT)
    return _tidy(tips)


def _tidy(tips, limit=8):
    """Deduplicated on the words, in order, capped.

    A page tip and a craft line can say the same thing, and nobody taps a
    dragonfly eleven times.
    """
    seen = set()
    unique = []
    for tip in tips:
        if tip["text"] not in seen:
            seen.add(tip["text"])
            unique.append(tip)
    return unique[:limit]


# ------------------------------------------------------------ what Sage knows

def deep(user, active=None, urls=None):
    """Tips built from the whole picture — the same data Sage reasons over.

    Fetched when somebody actually taps, never on a page load: this scores every
    post the account has, which is a page's worth of work and far too much to
    spend assembling a sentence nobody asked for.

    Everything here is read off that context. No claim is made that the numbers
    do not support, and a group is only named when it has a usable baseline —
    naming a group and quoting a median that scoring itself rejected is the one
    mistake this whole product exists not to make.
    """
    urls = urls or {}
    tips = []
    try:
        import sage
        context = sage.build_context()
    except Exception:                         # noqa: BLE001 - fall back quietly
        return []

    if not context or context.get("empty"):
        return []

    sources = [s for s in (context.get("sources") or []) if not s.get("is_sample")]
    scored = [s for s in sources if s.get("has_baseline")]

    # The strongest room, and what "strongest" means in it.
    if scored:
        best = max(scored, key=lambda s: s.get("best_multiple") or 0)
        if best.get("best_multiple"):
            tips.append(_fact(
                '"%s" is where your best result is: a typical post there scores '
                "%s, and the best one you have captured did %s× that."
                % (best["name"], best.get("baseline"), best["best_multiple"]),
                urls.get("groups")))

    # A room that cannot be scored yet, and why — the most common confusion.
    waiting_room = [s for s in sources if not s.get("has_baseline")]
    if waiting_room:
        thin = max(waiting_room, key=lambda s: s.get("posts") or 0)
        tips.append(_fact(
            '"%s" still cannot be scored: %d posts captured and %d%% of them '
            "readable. It needs about %d readable ones before a median means "
            "anything."
            % (thin["name"], thin.get("posts") or 0,
               thin.get("engagement_recorded_pct") or 0, outliers.MIN_SAMPLE),
            urls.get("groups")))

    # A room whose numbers are soft because too little of it could be read.
    unreadable = [s for s in scored if (s.get("engagement_recorded_pct") or 100) < 70]
    if unreadable:
        worst = min(unreadable, key=lambda s: s.get("engagement_recorded_pct") or 0)
        tips.append(_fact(
            'Only %d%% of "%s" could be read, so its median is built on less '
            "than it looks. Scanning it again sharpens every score in it."
            % (worst.get("engagement_recorded_pct") or 0, worst["name"]),
            urls.get("groups")))

    # How many genuine breakouts there are, which is the number worth copying.
    tiers = context.get("tiers") or {}
    breakouts = tiers.get("breakout") or 0
    if breakouts:
        tips.append(_fact(
            "You have %d post%s at 5× or better. Those are the ones worth "
            "taking apart — Write builds on one rather than starting cold."
            % (breakouts, "" if breakouts == 1 else "s"),
            urls.get("write")))

    # What actually works across their groups, if the evidence is there.
    try:
        import patterns
        from app import _fetch_posts
        found = patterns.findings(_fetch_posts(), across=True)
        for finding in (found.get("findings") or [])[:2]:
            tips.append(_fact(
                "%s (from %d posts of yours that could be read)."
                % (finding["sentence"].rstrip("."), found.get("measured") or 0),
                urls.get("playbook")))
    except Exception:                         # noqa: BLE001
        pass

    # Their own posts, if they have told us which are theirs.
    try:
        import mine
        own = mine.results(user["id"]) if user else {"overall": {}}
        overall = own.get("overall") or {}
        if overall.get("scored"):
            tips.append(_fact(
                "Your own posts are running at %s× the median of their groups, "
                "and %d of %d beat it."
                % (overall.get("median"), overall.get("beat"), overall.get("scored")),
                urls.get("results")))
    except Exception:                         # noqa: BLE001
        pass

    # Sample data still mixed in is worth saying once.
    if any(s.get("is_sample") for s in (context.get("sources") or [])):
        tips.append(_fact(
            "Some of what you are looking at is sample data, marked as such. It "
            "hides itself once your own scans land.",
            urls.get("groups")))

    return _tidy(tips)
