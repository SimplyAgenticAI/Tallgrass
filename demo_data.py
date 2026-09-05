"""Sample data so a fresh install has something to render.

Every row is written with is_demo=1 and can be wiped from the Capture page.
This exists to make the difference between "working but empty" and "broken"
visible — it is not a substitute for real captures.

Engagement follows a power-law-ish shape on purpose: most posts sit near the
median with a couple of genuine breakouts, which is what the outlier scoring
is designed to separate.

The multipliers below are multiples OF THE MEDIAN, so the shape is readable
from the column itself: the median post is 1.0 and the set has to contain
something that clears 5x or the scoring has nothing to find.

That last part was not true for a long time. The values were spread evenly
enough that the median landed at 3.55 and the best post scored 4.3x against
it — so the sample set demonstrated a breakout-finder finding no breakouts,
and the feed's headline stat read "0 breakout posts, nothing cleared 5x
median". It went unnoticed while this was an empty-install convenience. It
stopped being harmless the moment a new account was given this set as its
first impression of the product, which is what tests/onboarding.test.py now
pins.
"""

import random
from datetime import datetime, timedelta, timezone

import db

SEED = 20260807  # fixed so the demo set is identical on every machine

DEMO_SOURCES = [
    {
        "fb_id": "demo-group-ecom",
        "kind": "group",
        "name": "[DEMO] Ecommerce Founders UK",
        "member_count": 24800,
    },
    {
        "fb_id": "demo-group-agency",
        "kind": "group",
        "name": "[DEMO] Agency Owners Lounge",
        "member_count": 9100,
    },
    {
        "fb_id": "demo-group-local",
        "kind": "group",
        "name": "[DEMO] Local Service Business Growth",
        "member_count": 41200,
    },
]

DEMO_AUTHORS = [
    "Sam Okonkwo", "Rachel Fenwick", "Dev Patel", "Marta Nowak",
    "Tom Aldridge", "Jess Kimura", "Femi Adeyemi", "Nina Brandt",
]

# Bodies are written to look like real group posts — some plainly typed, some
# structured — because the remix engine keys off register as much as content.
DEMO_POSTS = [
    ("Spent 4 months building a feature nobody asked for. Killed it last week. "
     "Revenue went up 8%. Turns out the thing was confusing people at checkout.\n\n"
     "Ask before you build. I clearly didn't.", "text", 7.1),
    ("Anyone else getting absolutely destroyed by shipping costs this quarter? "
     "Our margins are down 6 points and it's entirely postage.", "text", 0.5),
    ("Quick one — what's everyone using for inventory sync these days? "
     "Currently on spreadsheets and it's held together with hope.", "text", 0.4),
    ("I fired our biggest client on Tuesday.\n\nThey were 40% of revenue and about "
     "110% of our stress. Two people on my team were ready to quit over them.\n\n"
     "Scariest thing I've done. Zero regrets so far. Ask me in six months.", "text", 12.4),
    ("Reminder that a 2% conversion rate means 98 out of 100 people looked at your "
     "thing and left. Most of your growth is hiding in that 98.", "text", 1.2),
    ("Case study: took a client from 3k to 22k monthly revenue in 7 months. "
     "Full breakdown of what actually moved the needle in the comments.", "photo", 1.4),
    ("Does anyone have a decent VA agency they'd recommend? Been burned twice now.", "text", 0.3),
    ("Hot take: most 'brand strategy' work sold to small businesses is expensive "
     "procrastination. Ship the thing. Fix it in public.", "text", 2.3),
    ("Our best performing ad this month was filmed on a phone in a car park. "
     "The £4k studio production did a third of the numbers.", "video", 3.1),
    ("Genuinely curious how many people here are profitable vs just busy.", "text", 0.85),
    ("Three years in, first month over six figures. Not posting numbers to brag — "
     "posting because in year one I read posts like this and assumed they were fake. "
     "They weren't. It just takes much longer than anyone admits.", "text", 5.4),
    ("What's your actual close rate on discovery calls? Mine's 22% and I can't tell "
     "if that's good or terrible.", "text", 0.75),
    ("Stop offering unlimited revisions. That's it, that's the post.", "text", 1.6),
    ("Built our whole onboarding in Notion and clients keep saying it's the most "
     "organised agency they've worked with. It took a weekend.", "text", 0.9),
    ("Looking for a copywriter who understands B2B SaaS. Budget is real. DM me.", "text", 0.25),
    ("The uncomfortable truth about referrals: they dry up the moment you stop "
     "delivering something remarkable. They're a lagging indicator, not a strategy.", "text", 1.1),
    ("Anyone tried the new ad format? Results seem inconsistent across accounts.", "text", 0.45),
    ("Raised prices 40% in January. Lost 2 clients out of 14. Revenue up 26%. "
     "I should have done it two years earlier.", "text", 3.6),
    ("Small win: automated our reporting and got 6 hours a week back. "
     "Happy to share the setup if useful.", "text", 0.8),
    ("Every single time I've hired fast I've regretted it. Every single time. "
     "And I keep doing it.", "text", 1.3),
    ("What does everyone charge for a one-off audit? Trying to benchmark.", "text", 0.55),
    ("Client asked for a discount because 'it's just a few hours of work'. "
     "Sent them a breakdown of the 11 years it took to make it a few hours.", "text", 2.6),
    ("Local SEO is still absurdly underpriced relative to what it returns. "
     "Most of my competitors have completely abandoned it for social.", "text", 0.95),
    ("Posting this because I wish someone had told me: your first 20 clients "
     "will come from people who already know you. Not ads. Not content. "
     "Go talk to people you've already met.", "text", 2.0),
    ("Anyone going to the trade show next month? Would be good to meet up.", "text", 0.35),
    ("Cut our ad spend by 60% and revenue stayed flat. Six months of budget "
     "was buying us nothing and I only found out by accident.", "text", 4.2),
    ("Free template: the proposal doc that's closed about £400k for us. "
     "No opt-in, link's in the comments.", "link", 1.8),
    ("How are people handling late payers? Currently chasing 3 invoices "
     "over 60 days and losing patience.", "text", 0.6),
    ("Unpopular: you don't need a niche in year one. You need to talk to enough "
     "people to find out what you're actually good at. The niche finds you.", "text", 1.7),
    ("Rebuilt our site in a weekend after 8 months of a designer 'nearly being done'. "
     "It converts better than the mockups did.", "text", 1.0),
]


def seed_demo_data(user_id=None):
    """Insert the demo set for one account. Returns posts written.

    A committed snapshot of real captures wins if this install has one. The
    written set below is the fallback, and stays for the case it was built
    for: an install with no snapshot, which is every fresh clone.
    """
    import demo_snapshot
    snapshot = demo_snapshot.load()
    if snapshot:
        return _seed_from_snapshot(snapshot, user_id)
    return _seed_written(user_id)


def _seed_from_snapshot(snapshot, user_id):
    """Real posts, real engagement, ages reconstructed against right now.

    The offset is what keeps this usable. Absolute timestamps would make a
    snapshot taken today read as eight months stale by spring, and a feed of
    old posts is the exact impression this is meant to avoid.
    """
    import demo_snapshot as snap

    now = datetime.now(timezone.utc)
    written = 0

    with db.get_db() as conn:
        for source in snapshot.get("sources", []):
            source_id = db.upsert_source(
                conn,
                fb_id=source["fb_id"],
                kind=source.get("kind") or "group",
                name=source.get("name") or "",
                url=source.get("url") or "",
                member_count=source.get("member_count") or 0,
                user_id=user_id,
            )

            for post in source.get("posts", []):
                author_id = None
                if post.get("author"):
                    author_id = db.upsert_author(conn, name=post["author"])

                posted = now - timedelta(hours=float(post.get("hours_ago") or 0))

                row = dict(post)
                row["posted_at"] = posted.strftime("%Y-%m-%dT%H:%M:%S")
                row["is_demo"] = 1
                # Written once to a shared directory and referenced by hash.
                # Copying ninety pictures into every account's image cache is
                # the whole disk by a few hundred users.
                row["image_url"] = (snap._store_image(post["image"])
                                    if post.get("image") else None)
                row.pop("image", None)
                row.pop("hours_ago", None)

                if db.upsert_post(conn, source_id, author_id, row,
                                  user_id=user_id):
                    written += 1

    return written


def _seed_written(user_id=None):
    """The hand-written set. Used when no snapshot has been committed."""
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    written = 0

    with db.get_db() as conn:
        for source_index, source in enumerate(DEMO_SOURCES):
            source_id = db.upsert_source(
                conn,
                fb_id=source["fb_id"],
                kind=source["kind"],
                name=source["name"],
                url=f"https://facebook.com/groups/{source['fb_id']}",
                member_count=source["member_count"],
                user_id=user_id,
            )

            # Give each group a different baseline so the scoring has to
            # normalise per-source rather than comparing raw counts.
            base_scale = [42, 18, 96][source_index]

            for post_index, (body, post_type, multiplier) in enumerate(DEMO_POSTS):
                author = DEMO_AUTHORS[(post_index + source_index) % len(DEMO_AUTHORS)]
                author_id = db.upsert_author(conn, name=author)

                jitter = rng.uniform(0.75, 1.3)
                likes = int(base_scale * multiplier * jitter)
                comments = int(likes * rng.uniform(0.06, 0.22))
                shares = int(likes * rng.uniform(0.01, 0.09))

                posted = now - timedelta(
                    days=rng.randint(1, 75), hours=rng.randint(0, 23)
                )

                created = db.upsert_post(
                    conn,
                    source_id,
                    author_id,
                    {
                        "fb_post_id": f"{source['fb_id']}-p{post_index}",
                        "body": body,
                        "permalink": f"https://facebook.com/groups/{source['fb_id']}/posts/{post_index}",
                        "post_type": post_type,
                        "posted_at": posted.strftime("%Y-%m-%dT%H:%M:%S"),
                        "likes": likes,
                        "comments": comments,
                        "shares": shares,
                        "video_plays": int(likes * 12) if post_type == "video" else 0,
                        "is_demo": 1,
                    },
                    user_id=user_id,
                )
                if created:
                    written += 1

    return written
