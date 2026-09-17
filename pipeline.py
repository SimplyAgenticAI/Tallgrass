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


def set_meta(kind, user_id, row_id, stage=None, note=None, snooze_days=None, wake=False):
    """Update any of stage, note and snooze on one comment or chat. Returns rows changed."""
    table = TABLES.get(kind)
    if not table:
        raise ValueError("unknown kind")
    sets, values = [], []
    if stage is not None:
        sets.append("stage = ?")
        values.append(stage if stage in STAGES else None)
    if note is not None:
        sets.append("note = ?")
        values.append(db.clean_text(str(note), 500).strip() or None)
    if snooze_days is not None:
        days = int(snooze_days)
        sets.append("snooze_until = ?")
        values.append((datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
                      if days > 0 else None)
    if wake:
        sets.append("snooze_until = NULL")
    if not sets:
        return 0
    with db.get_db() as conn:
        return conn.execute("UPDATE %s SET %s WHERE id = ? AND user_id = ?" % (table, ", ".join(sets)),
                            values + [int(row_id), user_id]).rowcount


def is_snoozed(row):
    until = row.get("snooze_until") if isinstance(row, dict) else row["snooze_until"]
    return bool(until) and until > now_utc()


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
