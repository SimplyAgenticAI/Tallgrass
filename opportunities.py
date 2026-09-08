"""Ranking posts you went looking for, which is the opposite of ranking posts
that found you.

Everything else in this product scores a post against the median of its own
group: what is normal here, and did this clear it. That question is exactly
wrong for a post somebody searched for, and applying it would rank the results
upside down.

    "Anyone know someone who builds websites? Ours is embarrassing."
    1 like, 2 comments

That is the best result a search for "website" can return, and it is a
textbook non-outlier. Meanwhile the forty-comment post about websites is the
WORSE one to answer, because forty people already did.

So the three inputs here are not engagement at all:

  fresh       A day-old ask is live. A week-old ask was answered by somebody
              else on the day it was posted. Recency dominates everything and
              is the only input that can zero the score on its own.
  wanting     Does the text read as somebody who wants a thing, or somebody
              talking about the thing? "Can anyone recommend" is a different
              sentence from "I love our new site", and both contain the word.
  uncrowded   How many replies are already there. INVERTED against every
              other score in this codebase, and it is not a bug.

Nothing here is scored against a median and nothing here touches one. See the
comment on the opportunities table in db.py for why that separation is load
bearing rather than tidy.

This is deliberately arithmetic and not a model. It costs nothing per post,
runs offline, and can be read and argued with. A language model reading intent
properly is the obvious upgrade and the right one — but it has a price per
post, and it should be added once these results are known to be worth paying
for, not before.
"""

import re
from datetime import datetime, timezone

# How long a result stays interesting. Past this it scores zero: not hidden,
# not deleted, just ranked where a fortnight-old request for a quote belongs.
MAX_AGE_HOURS = 24 * 14

# The shapes of asking. Ordered strongest first — the earliest match wins, so
# an explicit request outranks a vague grumble in the same post.
#
# These are patterns of REQUEST, deliberately, and carry no industry words at
# all. The industry is whatever the person searched for; baking "website" in
# here would make the feature work for one trade and quietly fail for every
# other, which is the difference between a keyword tool and a web-design tool.
WANTING = [
    (1.00, "asking outright", re.compile(
        r"\b(?:can\s+any(?:one|body)\s+recommend|any(?:one|body)\s+know\s+"
        r"(?:a\s+good|of\s+a|any(?:one|body))|looking\s+(?:for|to\s+hire)|"
        r"in\s+(?:the\s+)?market\s+for|need\s+(?:a|an|some(?:one|body))|"
        r"who\s+(?:do\s+you|can)\s+(?:use|recommend)|"
        r"recommendations?\s+for|hiring\s+(?:a|an)|"
        r"does\s+any(?:one|body)\s+(?:do|know))\b", re.I)),
    (0.80, "ready to pay", re.compile(
        r"\b(?:budget|quote|how\s+much\s+(?:would|do|does|should)|"
        r"paid\s+(?:gig|work)|will\s+pay|happy\s+to\s+pay|"
        r"what\s+(?:do|should)\s+(?:i|we)\s+expect\s+to\s+pay|"
        r"pricing|rates?\b)", re.I)),
    (0.55, "a problem to solve", re.compile(
        r"\b(?:struggling\s+with|help\s+with|advice\s+on|"
        r"(?:is|it)\s+(?:so\s+)?(?:out\s?dated|embarrassing|broken|awful)|"
        r"(?:does\s?n[o']?t|doesn't|won'?t|cannot|can'?t)\s+work|"
        r"any\s+(?:advice|tips|suggestions)|not\s+sure\s+(?:how|where|what))",
        re.I)),
    (0.30, "a question", re.compile(r"\?", re.I)),
]


def _hours_since(stamp):
    """Age in hours, or None when the timestamp will not parse.

    None is not zero. A post with no readable date is of unknown age, and
    unknown is not the same as new — treating it as new would float every
    undated result to the top of the list.
    """
    if not stamp:
        return None
    text = str(stamp).strip().replace("Z", "+00:00")
    for parse in (datetime.fromisoformat,
                  lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
                  lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")):
        try:
            when = parse(text)
        except (ValueError, TypeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600.0)
    return None


def freshness(posted_at):
    """1.0 for something posted now, decaying to 0 at MAX_AGE_HOURS.

    Front-loaded rather than linear. The gap between two hours old and one day
    old is the whole game; the gap between nine days and ten is nothing, and a
    linear decay spends most of its range describing the part nobody acts on.
    """
    hours = _hours_since(posted_at)
    if hours is None:
        # Unknown age. Not zero — an undated post may be perfectly good — but
        # never competitive with something known to be from this morning.
        return 0.35
    if hours >= MAX_AGE_HOURS:
        return 0.0
    if hours <= 6:
        return 1.0
    if hours <= 24:
        return 0.85
    if hours <= 72:
        return 0.55
    if hours <= 24 * 7:
        return 0.30
    return 0.12


def wanting(body):
    """How much the text reads as somebody who wants something.

    Returns (weight, label). The label is shown on the card, because a number
    with no reason attached is not something anybody can disagree with — and
    the first thing a person will want to do with a bad result is understand
    why it was ranked at all.
    """
    text = (body or "").strip()
    if not text:
        return 0.0, ""
    for weight, label, pattern in WANTING:
        if pattern.search(text):
            return weight, label
    return 0.15, "mentions it"


def uncrowded(comments):
    """Fewer replies is better. Inverted on purpose — see the module docstring.

    A post with no answers yet is one you can be first on. Past about thirty
    replies the thread is a scrum and being the thirty-first voice in it is
    worth close to nothing.
    """
    try:
        count = max(0, int(comments or 0))
    except (TypeError, ValueError):
        count = 0
    if count == 0:
        return 1.0
    if count <= 3:
        return 0.85
    if count <= 10:
        return 0.6
    if count <= 30:
        return 0.35
    return 0.15


# How much of the score each modifier is allowed to move. Wanting is not in
# here because it is not a modifier — it is the thing being modified.
FRESH_FLOOR = 0.35        # a stale post keeps this much of its intent
ROOM_FLOOR = 0.55         # a crowded thread keeps this much


def score(post):
    """Rank one result, 0..100, with the reason it got that.

    Returns (score, intent_label). Stored at capture rather than computed on
    read: age moves every minute, and a list that silently re-orders itself
    between page loads cannot be worked through.

    Intent MULTIPLIES rather than adds, and that is the correction that makes
    this usable. Adding the three together gave

        "I love our new website, the team did great."   60.0, worth a look
        "Websites are dead, everything is social now."  53.2, worth a look

    because freshness and an empty comment thread paid out in full while
    intent scored almost nothing — so anything posted this morning cleared the
    bar whether or not a single person in it wanted anything. Half the list
    would have been chatter, and the tab is worthless the moment somebody
    scrolls a screenful of that.

    Multiplied, no-intent stays no-intent however fresh and however quiet.
    Freshness and elbow room can only scale a real request up or down.
    """
    fresh = freshness(post.get("posted_at"))
    want, label = wanting(post.get("body"))
    room = uncrowded(post.get("comments"))

    # Age gates the whole thing rather than just contributing to it. Something
    # past the window is not a weak opportunity, it is a closed one, and no
    # amount of intent should be able to lift it back into the list.
    if fresh <= 0.0:
        return 0.0, label

    total = (want
             * (FRESH_FLOOR + (1 - FRESH_FLOOR) * fresh)
             * (ROOM_FLOOR + (1 - ROOM_FLOOR) * room))
    return round(total * 100, 1), label


# Below this many results there is nothing to conclude from a run of old ones.
TOP_SORT_MIN_SAMPLE = 5
TOP_SORT_SHARE = 0.6


def looks_like_top_results(rows):
    """Does this batch look sorted by popularity rather than by date?

    Facebook's search defaults to Top, which ranks by engagement — precisely
    backwards here, because the request nobody has answered yet is the one
    worth answering. Scan with Top selected and you capture the crowded
    popular threads, score them mediocre, and nothing says why.

    Detected from the data rather than from the URL, deliberately. Facebook's
    Recent toggle is an undocumented base64 filters blob; building it into a
    link would work until it quietly stopped, and a silently wrong sort is the
    failure this ranking least tolerates. A run of old results is a real
    signal and cannot break behind our back.

    Soft on purpose. A quiet topic genuinely has old results, so this is worth
    saying and not worth acting on — the page suggests, it does not refuse.
    """
    dated = [r for r in rows if r.get("posted_at")]
    if len(dated) < TOP_SORT_MIN_SAMPLE:
        return False
    stale = sum(1 for r in dated if freshness(r.get("posted_at")) <= 0.30)
    return stale / float(len(dated)) >= TOP_SORT_SHARE


def tier(value):
    """The band a score falls in, for the colour on the card."""
    if value >= 70:
        return "hot"
    if value >= 45:
        return "worth a look"
    return "background"
