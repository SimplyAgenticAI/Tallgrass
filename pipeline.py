"""Where each relationship stands.

Waiting, replied and gone quiet say whose turn it is. They say nothing about
whether Dana asked for a quote, or whether you are waiting on Chris to book.
This adds the three things that do, on any comment or chat:

  stage   New lead → Talking → Quoted → Booked → Won, or Lost.
  note    A line in the owner's own words: "wants the 5-page site, budget ~$2k".
  snooze  Out of Today and the waiting count until a day you choose, for the
          "follow up Thursday" that otherwise lives in your head. A chat's
          snooze ends early if they write again.

Drafts read the stage and the note, so a quoted lead gets a nudge toward
booking rather than a first hello. Everything here is the owner's own input;
nothing is inferred.
"""

from datetime import datetime, timedelta, timezone

import db

STAGES = ["new", "talking", "quoted", "booked", "won", "lost"]
STAGE_LABELS = {
    "new": "New lead", "talking": "Talking", "quoted": "Quoted",
    "booked": "Booked", "won": "Won", "lost": "Lost",
}
# What each stage asks of the next reply. Handed to drafts.
STAGE_GUIDANCE = {
    "new": "A new lead: answer what they asked and invite one easy next step.",
    "talking": "Already talking: move toward a clear offer or a concrete next step.",
    "quoted": "They have a quote: help them decide — answer doubts, make booking easy, no pressure.",
    "booked": "They booked: confirm details, be helpful, make them glad they chose you.",
    "won": "A customer: nurture the relationship; a review or referral only if it comes up naturally.",
    "lost": "They said no: stay warm and helpful, leave the door open, never push.",
}
SNOOZE_DAYS = (1, 3, 7)
TABLES = {"comment": "post_comments", "message": "message_threads"}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# set_meta wrote a stage, note or snooze. Its only caller was the
# /pipeline route, whose controls were rendered only on the Comments
# and Messages pages. All three are gone.


# is_snoozed had no caller even before that: the templates compared
# snooze_until to now_utc themselves.


def summary(user_id):
    """How many people are at each stage, across comments and chats. Samples excluded."""
    counts = {s: 0 for s in STAGES}
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT c.stage FROM post_comments c JOIN comment_posts p ON p.id = c.post_id "
            "WHERE c.user_id = ? AND c.stage IS NOT NULL AND p.is_demo = 0 "
            "UNION ALL SELECT stage FROM message_threads "
            "WHERE user_id = ? AND stage IS NOT NULL AND is_demo = 0",
            (user_id, user_id)).fetchall()
    for r in rows:
        if r[0] in counts:
            counts[r[0]] += 1
    return counts


def draft_context(stage, note):
    """The lines a draft is given about where this relationship stands, or ''."""
    parts = []
    if stage in STAGE_LABELS:
        parts.append("Stage: %s. %s" % (STAGE_LABELS[stage], STAGE_GUIDANCE[stage]))
    if note:
        parts.append("The owner's own note on this person: %s" % note)
    return "\n".join(parts)
