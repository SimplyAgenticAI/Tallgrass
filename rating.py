"""How good a room is, and when to say nothing.

The question is "should I still be in this group", and the data to answer it is
already stored: what a typical post there scores, how much of the group could
actually be read, how often something breaks out, and whether anybody has
posted lately.

The whole difficulty is the second one. A group where extraction failed looks
exactly like a dead group — a median near zero either way — and telling somebody
to leave a room that is actually busy, because Tallgrass could not read it, is
the worst mistake this feature could make. So a verdict is only issued when
enough of the group was measured to support one, and "I cannot tell yet" is a
first-class answer rather than a fallback.

No single score out of a hundred. A band and the numbers behind it, because the
numbers are what let somebody disagree.
"""

import outliers

# What a typical post scores, in weighted engagement (reactions + comments×3 +
# shares×5). The boundaries are a judgement call and deliberately in one place:
# they are shown next to the band everywhere, so a reader can disagree with
# them rather than be ruled by them.
#
# MIN_BASELINE (8) is where scoring itself stops trusting a median, so "quiet"
# starts there rather than at an invented number.
THRIVING = 40
STEADY = 15
QUIET = outliers.MIN_BASELINE          # 8

# Below this share of readable posts, no verdict is offered at all. A group that
# could not be read is not a group that failed.
NEEDS_READABLE_PCT = 55

# Nothing posted in this long, from what we captured, and the room is not a room
# any more. Measured off the newest post, not off the last scan: a group nobody
# has scanned in a month is not thereby dead.
STALE_DAYS = 45

BANDS = ("thriving", "steady", "quiet", "dead", "unclear", "new")

LABELS = {
    "thriving": "Thriving",
    "steady": "Steady",
    "quiet": "Quiet",
    "dead": "Dead",
    "unclear": "Can't tell yet",
    "new": "Not enough yet",
}


def _days_since(stamp, now=None):
    from datetime import datetime, timezone
    if not stamp:
        return None
    hours = outliers._hours_since(stamp, now)
    return None if hours is None else hours / 24.0


def of(source, stats, newest=None, now=None):
    """A verdict for one source: {band, label, why, leave, numbers}.

    `stats` is outliers.source_stats for that source; `newest` is the most
    recent posted_at captured from it. `why` is the evidence, in the order it
    mattered, because a band without its reasons is an opinion.
    """
    verdict = {"band": "new", "label": LABELS["new"], "why": [], "leave": False,
               "numbers": {}}

    if not stats or not stats.get("post_count"):
        verdict["why"].append("Nothing captured from here yet.")
        return verdict

    measured = stats.get("measured_count") or 0
    readable = stats.get("measured_pct") or 0
    baseline = stats.get("baseline")
    posts = stats.get("post_count") or 0
    outlier_rate = round((stats.get("outlier_count") or 0) / posts * 100) if posts else 0
    days = _days_since(newest, now)

    verdict["numbers"] = {
        "posts": posts,
        "readable_pct": readable,
        "baseline": baseline,
        "outlier_pct": outlier_rate,
        "days_quiet": None if days is None else int(days),
        "top_multiple": stats.get("top_multiple"),
    }

    # Sample data is a demonstration. It is never rated and never suggested for
    # leaving — you cannot leave a group that does not exist.
    if source.get("is_demo"):
        verdict["band"] = "new"
        verdict["label"] = LABELS["new"]
        verdict["why"].append("Sample data, not a group you are in.")
        return verdict

    # Not enough measured posts for scoring to mean anything. The groups page
    # already explains this case in detail; here it is simply not a verdict.
    if not stats.get("has_baseline"):
        verdict["band"] = "new"
        verdict["why"].append(
            "%d post%s captured, %d measured. A verdict needs about %d measured."
            % (posts, "" if posts == 1 else "s", measured, outliers.MIN_SAMPLE))
        return verdict

    # Scoreable, but most of it could not be read: the median describes the
    # fraction that could, which is too thin a base for "leave this group".
    if readable < NEEDS_READABLE_PCT:
        verdict["band"] = "unclear"
        verdict["label"] = LABELS["unclear"]
        verdict["why"].append(
            "Only %d%% of what was captured here could be read, so its median "
            "describes a fraction of the room. Scan it again before judging it."
            % readable)
        return verdict

    if days is not None and days >= STALE_DAYS:
        verdict["band"] = "dead"
        verdict["why"].append(
            "Nothing posted here in %d days, from what has been captured." % int(days))
        verdict["why"].append(
            "A typical post scored %s when it was active." % round(baseline, 1))
        verdict["leave"] = True
        verdict["label"] = LABELS["dead"]
        return verdict

    if baseline < QUIET:
        verdict["band"] = "dead"
        verdict["label"] = LABELS["dead"]
        verdict["why"].append(
            "A typical post here scores %s — below %d, which is where scoring "
            "itself stops trusting a median."
            % (round(baseline, 1), outliers.MIN_BASELINE))
        verdict["why"].append(
            "%d%% of it was readable, so that is the room and not a reading "
            "failure." % readable)
        verdict["leave"] = True
        return verdict

    if baseline < STEADY:
        verdict["band"] = "quiet"
        verdict["why"].append(
            "A typical post here scores %s. Real, but thin." % round(baseline, 1))
    elif baseline < THRIVING:
        verdict["band"] = "steady"
        verdict["why"].append(
            "A typical post here scores %s." % round(baseline, 1))
    else:
        verdict["band"] = "thriving"
        verdict["why"].append(
            "A typical post here scores %s." % round(baseline, 1))

    verdict["label"] = LABELS[verdict["band"]]
    if outlier_rate:
        verdict["why"].append(
            "%d%% of its posts break out at 3× that or better." % outlier_rate)
    if days is not None and days <= 7:
        verdict["why"].append("Posted in within the last week.")
    return verdict


def rank(verdicts):
    """Worst first, for a list of what might be worth leaving.

    Only groups with an actual verdict appear. "Can't tell yet" and "not enough
    yet" are not quietly sorted in at the bottom as though they were bad.
    """
    order = {"dead": 0, "quiet": 1, "steady": 2, "thriving": 3}
    rated = [v for v in verdicts if v["band"] in order]
    return sorted(rated, key=lambda v: (order[v["band"]],
                                        v["numbers"].get("baseline") or 0))


def tally(verdicts):
    """How many of each band, for a one-line summary."""
    counts = {}
    for verdict in verdicts:
        counts[verdict["band"]] = counts.get(verdict["band"], 0) + 1
    return counts
