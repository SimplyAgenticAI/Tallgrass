"""The reply queue. Removed, and this is what is left of it.

There was a queue here of everyone waiting on an answer: unanswered comments on
your own posts, and Messenger chats where they spoke last. It is gone, in two
steps and for two reasons.

The chats went first. A merged inbox competed with Facebook's own and lost on
every axis that matters — Facebook delivers in real time where this scrapes,
and it has mobile apps, labels and saved replies. The duplication was worse
than the weakness: when this said three people were waiting and Facebook said
five, the trust that went was the trust the SCORING had earned.

Then the comments went too, and the pages with them. Facebook already carries
replying, so a second place to do it was a second place to check. What this app
does that nothing else does is tell you what a post did against the median of
its own group, and that is what it is now.

The three functions stay, returning nothing, because they are still called:

  waiting_count  - the number on the extension's icon badge. Returning 0 clears
                   that badge on every build already installed, without waiting
                   for a store release. Several /api/ endpoints report it back
                   to the extension after a capture.
  queue          - kept for shape. Nothing reads it in the app any more.
  for_panel      - the reply queue in the on-Facebook panel.

The comment and chat STORES are untouched and still accept what the extension
sends, on purpose: a build already installed goes on sending until a new one
reaches it, and refusing those posts would break capture rather than retire a
feature. They come out after the extension stops sending.

OPPORTUNITY_RE and DECLINE_RE moved to comments.py, which is where a comment's
text belongs; they are re-exported here because tests import them from this
module.
"""

import comments

OPPORTUNITY_RE = comments.OPPORTUNITY_RE
DECLINE_RE = comments.DECLINE_RE

EMPTY = {"entries": [], "comments": 0, "messages": 0, "opportunities": 0,
         "samples": False}


def queue(_user_id):
    """Nothing is queued. See the module note."""
    return dict(EMPTY)


def for_panel(_user_id, limit=15):
    """Nothing for the panel's reply queue. See the module note."""
    return []


def waiting_count(_user_id):
    """Nobody is waiting, because nothing in this app asks anybody to reply.

    Zero rather than a count of stored rows. The number is drawn on the
    extension's icon as a red badge, and a badge pointing at a list that no
    longer exists is worse than no badge: it asks somebody to go and find work
    the app will not show them.
    """
    return 0
