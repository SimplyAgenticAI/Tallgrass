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


def _fact(text):
    return " ".join(str(text).split())


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

    # Deduplicated, because a page tip and a craft line can overlap, and capped
    # because nobody taps a dragonfly eleven times.
    seen = set()
    unique = []
    for tip in tips:
        if tip not in seen:
            seen.add(tip)
            unique.append(tip)
    return unique[:8]
