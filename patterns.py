"""What works in a group, worked out from that group's own posts.

Every tool in this category ships the same advice to everybody — post at 7pm,
ask questions, use photos — which is a guess dressed as a finding. This module
only ever compares measured posts inside one group and reports the comparison
it actually made: "photos do 1.8x what plain text does in this group, across 23
posts". Same principle as hooks.py, which offers nothing where nothing has been
measured, rather than an archetype with an apology attached.

The rules that keep a finding honest:

  measured only    a post whose engagement never extracted is not a zero, it
                   is unknown, and it is excluded — the same rule the baseline
                   already follows.
  both sides       a comparison needs MIN_PER_SIDE posts on each side. Three
                   photos beating two text posts is not a pattern.
  a real gap       under MIN_RATIO the difference is noise and saying it out
                   loud would be inventing advice.
  medians          not means. One viral post must not turn its whole category
                   into a recommendation.
  no clocks        there is deliberately no "best time to post" here. Ages come
                   from Facebook's relative labels ("3d"), so an hour-of-day
                   derived from them is manufactured, and a confident wrong
                   answer about timing is exactly the kind of thing this
                   product exists not to do.
  comparable
  numbers          inside one group, raw weighted engagement is the measure.
                   ACROSS groups it cannot be: a group ten times the size makes
                   whatever it happens to post look like the winning format. So
                   a cross-group finding compares each post to its own group's
                   median instead, and only posts whose group has a usable
                   baseline take part.
"""

import outliers

# Per side of a comparison. Below this, one unusual post moves the median.
MIN_PER_SIDE = 5

# How much better one side has to do before it is worth a sentence.
MIN_RATIO = 1.3

# Where a post stops being short. Facebook truncates around here, which is the
# only length boundary the platform itself imposes.
SHORT_CHARS = 280

TYPE_LABELS = {
    "photo": "Photos",
    "video": "Videos",
    "reel": "Reels",
    "album": "Photo albums",
    "link": "Link posts",
    "text": "Text-only posts",
}


def _measured(posts):
    """Real, measured posts — the only rows any finding may be built on."""
    return [p for p in posts
            if (p.get("item_type") or "post") == "post"
            and not p.get("is_demo")
            and outliers.engagement_known(p)]


def _median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _compare(groups, kind):
    """The best-against-the-rest finding for one split, or None.

    `groups` is {label: [engagements]}. Sides below MIN_PER_SIDE are dropped
    before anything is compared, so a thin category cannot win by accident.
    """
    usable = {label: values for label, values in groups.items()
              if len(values) >= MIN_PER_SIDE}
    if len(usable) < 2:
        return None

    medians = {label: _median(values) for label, values in usable.items()}
    best = max(medians, key=lambda label: medians[label])
    rest = [(label, m) for label, m in medians.items() if label != best]
    runner, runner_median = max(rest, key=lambda pair: pair[1])

    if not runner_median or medians[best] <= 0:
        return None
    ratio = medians[best] / runner_median
    if ratio < MIN_RATIO:
        return None

    return {
        "kind": kind,
        "winner": best,
        "loser": runner,
        "ratio": round(ratio, 1),
        "sample": len(usable[best]) + len(usable[runner]),
        "counts": {label: len(values) for label, values in usable.items()},
    }


def _by_format(pairs):
    groups = {}
    for post, value in pairs:
        label = TYPE_LABELS.get((post.get("post_type") or "text").lower())
        if label:
            groups.setdefault(label, []).append(value)
    return _compare(groups, "format")


def _by_shape(pairs):
    groups = {}
    for post, value in pairs:
        body = post.get("body") or ""
        if not body.strip():
            continue                      # a post with no words says nothing here
        label = "Posts that ask a question" if "?" in body else "Posts that make a statement"
        groups.setdefault(label, []).append(value)
    return _compare(groups, "shape")


def _by_length(pairs):
    groups = {}
    for post, value in pairs:
        body = (post.get("body") or "").strip()
        if not body:
            continue
        label = ("Short posts (under %d characters)" % SHORT_CHARS
                 if len(body) <= SHORT_CHARS else "Longer posts")
        groups.setdefault(label, []).append(value)
    return _compare(groups, "length")


SENTENCES = {
    "format": "%(winner)s do %(ratio)s× as well as %(loser_lower)s here.",
    "shape": "%(winner)s do %(ratio)s× as well as %(loser_lower)s here.",
    "length": "%(winner)s do %(ratio)s× as well as %(loser_lower)s here.",
}


def _sentence(finding):
    return SENTENCES[finding["kind"]] % {
        "winner": finding["winner"],
        "ratio": finding["ratio"],
        "loser_lower": finding["loser"][0].lower() + finding["loser"][1:],
    }


def _values(posts, across):
    """(post, comparable number) for every post that may take part.

    Within one group that number is the post's weighted engagement. Across
    groups it is the post's multiple of its own group's median, which is the
    only way a photo in a group of 300 and a photo in a group of 30,000 can sit
    in the same comparison — and it means posts in groups that cannot be scored
    yet are left out rather than quietly flattening the result.
    """
    measured = _measured(posts)
    if not across:
        return [(p, outliers.weighted_engagement(p)) for p in measured]

    ids = {p["id"] for p in measured}
    return [(s, s["outlier_multiple"]) for s in outliers.score_posts(measured)
            if s["id"] in ids and s.get("has_baseline")
            and s.get("outlier_multiple") is not None]


def findings(posts, across=False):
    """Everything true that can be said about these posts, best gap first.

    `across` for a set spanning more than one group — see _values.

    Empty is a perfectly good answer and the common one early on: a group needs
    a couple of dozen measured posts before any split has five on each side.
    """
    pairs = _values(posts, across)
    out = []
    for finder in (_by_format, _by_shape, _by_length):
        found = finder(pairs)
        if found:
            found["sentence"] = _sentence(found)
            out.append(found)
    out.sort(key=lambda f: f["ratio"], reverse=True)
    return {"findings": out, "measured": len(pairs),
            "needed": max(MIN_PER_SIDE * 2 - len(pairs), 0)}
