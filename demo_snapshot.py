"""Real captured posts, frozen into the sample set every new account gets.

The sample data was written by hand, and its engagement numbers were invented
— at one point tuned by hand until the distribution produced a breakout,
because the original set did not contain one. That works as an illustration
and fails as evidence: the Write page offers openings labelled "the number is
what that post actually did", and on invented data that sentence is not true.

So the operator scans real sources, exports them here, and the file is
committed. From then on every new account is seeded from real posts with real
engagement, and every number the demo shows is one that actually happened.

Three things this format does deliberately:

  ages nothing   Times are stored as an OFFSET from export, not as dates. A
                 snapshot of absolute timestamps reads as "posted 8 months
                 ago" by spring and the demo looks abandoned. Reconstructed
                 against the moment of signup, it is always current.

  keeps the      Every post of a chosen source is exported, not the best ones.
  distribution   The multiple a post scores is measured against its source's
                 MEDIAN, so a snapshot of only the winners has no baseline
                 left to beat and would score them all as unremarkable.

  costs one      Pictures are carried in the file and written ONCE to a shared
  copy           directory, not into each account's image cache. Ninety images
                 per user across a few hundred users is the whole disk.

WHAT YOU SCAN MATTERS, and the tooling cannot decide it for you. Posts from a
public Page were published to the world by a business. Posts from a private
group were written by named individuals to a closed audience, and seeding them
into every stranger's account hands that audience to people it was never meant
for. Prefer public Pages.
"""

import base64
import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone

import db

log = logging.getLogger("tallgrass.demo")

# Written by the Save button on the admin page, onto the persistent disk.
#
# This is the one that gets used in practice. The original design made the
# operator download a file, commit it and deploy — three steps and a git push
# to change which posts new users see, which is three steps too many for
# something you want to try, look at, and adjust. The disk survives deploys, so
# there is no reason it had to go through the repository at all.
LIVE_PATH = os.path.join(db.DATA_DIR, "demo_snapshot.json")

# Beside the code: a snapshot committed to the repository, which every deploy
# carries. Still supported and still exportable, because it is the only version
# that survives losing the disk — but it is now the fallback, not the path.
SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "demo_snapshot.json")

# Shared by every account, written once. The seeder points demo posts at these
# by hash rather than copying them per user.
IMAGE_DIR = os.path.join(db.DATA_DIR, "demo-images")

# What a demo post stores in image_url. Not a URL — a marker the image route
# recognises, so a demo picture is served from the shared directory instead of
# being fetched and cached again for every account that sees it.
MARKER = "demo:"

FORMAT_VERSION = 1

# How many posts to take from each chosen source.
#
# Not a curation limit — a disk one, and the arithmetic is worth writing down
# because it is easy to pick a number that quietly costs a hundred megabytes.
# Every seeded post is a ROW IN EACH NEW ACCOUNT, at roughly 1.5KB with its
# body. Four sources at 100 posts is 600KB per signup, which is 150MB by the
# time there are 250 accounts — on a 1GB disk already holding a 400MB image
# cache and seven backups.
#
# 40 from each of three or four sources is comfortably past MIN_SAMPLE, gives
# a median with real spread behind it, and costs a quarter of that.
#
# What it must NOT become is a selection on engagement. Posts are taken by
# RECENCY, so the distribution is whatever that source actually looks like.
# Taking the best 40 would leave no baseline for them to beat and score every
# one of them as unremarkable.
DEFAULT_POSTS_PER_SOURCE = 40
MAX_POSTS_PER_SOURCE = 200

# Roughly the per-post cost of a seeded row, for the estimate on the admin
# page. Measured against real captures rather than guessed: bodies dominate.
BYTES_PER_POST = 1500

MAX_IMAGE_BYTES = 200 * 1024


def _hours_since(stamp):
    """How long ago a post was published, in hours. None if unparseable."""
    if not stamp:
        return None
    text = str(stamp).strip().replace(" ", "T")[:19]
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - moment
    return max(0.0, round(delta.total_seconds() / 3600.0, 2))


# --------------------------------------------------------------------- export

def build(source_ids, user_id, note="", limit=DEFAULT_POSTS_PER_SOURCE):
    """Freeze these sources into a snapshot dict. Operator-only.

    Reads the operator's OWN captures — the caller is responsible for the
    sources belonging to them, and app.py scopes the query it passes here.

    `limit` is per source and applied by RECENCY, never by engagement. Taking
    the best N would be selecting on the very thing the score measures against
    the median, leaving no baseline for them to beat.
    """
    import images

    limit = max(1, min(int(limit or DEFAULT_POSTS_PER_SOURCE),
                       MAX_POSTS_PER_SOURCE))

    snapshot = {
        "format": FORMAT_VERSION,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": note or "",
        "skipped": [],
        "sources": [],
    }

    with db.get_db() as conn:
        for source_id in source_ids:
            source = conn.execute(
                "SELECT * FROM sources WHERE id = ? AND user_id = ?",
                (source_id, user_id)).fetchone()
            if not source:
                continue

            rows = conn.execute(
                """
                SELECT p.*, a.name AS author_name
                FROM posts p LEFT JOIN authors a ON a.id = p.author_id
                WHERE p.source_id = ? AND p.user_id = ?
                  AND COALESCE(p.item_type, 'post') = 'post'
                ORDER BY p.posted_at DESC
                LIMIT ?
                """,
                (source_id, user_id, limit)).fetchall()

            posts = []
            undated = 0
            from_capture = 0
            unparsed = []
            for row in rows:
                hours = _hours_since(row["posted_at"])

                if hours is None:
                    # posted_at is nullable — the extension stores null when it
                    # cannot read a timestamp off the page, which happens on
                    # some profile layouts. Falling back to when WE saw the
                    # post is not the same fact, but it is a real one and it is
                    # an upper bound on the post's age.
                    #
                    # This whole source used to be refused over it: a profile
                    # whose timestamps did not extract exported nothing and
                    # reported "no readable post dates", which is true and
                    # useless when the posts themselves are perfectly good.
                    hours = _hours_since(row["captured_at"])
                    if hours is not None:
                        from_capture += 1

                if hours is None:
                    undated += 1
                    if len(unparsed) < 3:
                        # The raw values, so the reason can be diagnosed rather
                        # than guessed at from a count.
                        unparsed.append("posted_at=%r captured_at=%r"
                                        % (row["posted_at"], row["captured_at"]))
                    continue

                post = {
                    "fb_post_id": row["fb_post_id"],
                    "body": row["body"] or "",
                    "post_type": row["post_type"] or "text",
                    "hours_ago": hours,
                    "likes": row["likes"] or 0,
                    "comments": row["comments"] or 0,
                    "shares": row["shares"] or 0,
                    "video_plays": row["video_plays"] or 0,
                    "author": row["author_name"] or "",
                    "permalink": row["permalink"] or "",
                    "image_count": row["image_count"] or 0,
                    "has_video": bool(row["has_video"]),
                    "engagement_read": bool(row["engagement_read"]),
                    "image_text": row["image_text"] or "",
                    "image_desc": row["image_desc"] or "",
                    "body_from_image": bool(row["body_from_image"]),
                }

                # The picture as it is already cached — downscaled to 640px and
                # re-encoded, so this is the small copy rather than Facebook's
                # original. A post whose image was never fetched has none to
                # carry, which is not worth failing over.
                cached = images.cached(row["id"])
                if cached:
                    try:
                        raw = io.open(cached, "rb").read()
                        if len(raw) <= MAX_IMAGE_BYTES:
                            post["image"] = base64.b64encode(raw).decode("ascii")
                    except OSError:
                        pass

                posts.append(post)

            # A source that contributes nothing is not quietly dropped.
            #
            # It was, and the first export produced three posts across five
            # chosen sources — four of them empty — which would have seeded
            # every new account with less than MIN_SAMPLE and a feed that
            # ranked nothing. Silence made that look like success. The reason
            # travels with the result now, so the admin page can say which
            # source needs scanning and why.
            if len(posts) < outliers_min_sample():
                snapshot["skipped"].append({
                    "name": source["name"] or "",
                    "kind": source["kind"] or "group",
                    "usable": len(posts),
                    "undated": undated,
                    "reason": ("nothing captured yet" if not rows else
                               "no usable dates on any post" if undated and not posts
                               else "only %d scoreable posts, needs %d"
                                    % (len(posts), outliers_min_sample())),
                    # Empty unless something genuinely would not parse. A count
                    # says a thing failed; these say what it was.
                    "samples": unparsed,
                })
                continue

            snapshot["sources"].append({
                "fb_id": source["fb_id"],
                "kind": source["kind"] or "group",
                "name": source["name"] or "",
                "url": source["url"] or "",
                "member_count": source["member_count"] or 0,
                # How many of these are aged from when we saw them rather than
                # when they were posted. Surfaced rather than buried: it is the
                # difference between "posted 3 days ago" meaning the post's own
                # age and meaning the age of your scan.
                "from_capture": from_capture,
                "posts": posts,
            })

    return snapshot


def outliers_min_sample():
    """The floor a source has to clear to be worth seeding at all.

    Imported lazily: outliers imports db, and this module is imported by
    db-adjacent code at start-up.
    """
    import outliers
    return outliers.MIN_SAMPLE


def save(snapshot, path=None):
    target = path or SNAPSHOT_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # Written beside and moved into place. A half-written snapshot that the
    # next signup tries to read is a broken account, not a broken file.
    temporary = target + ".part"
    with io.open(temporary, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)
    os.replace(temporary, target)
    return target


def publish(source_ids, user_id, note="", limit=DEFAULT_POSTS_PER_SOURCE):
    """Make these sources the sample set, now. Returns (summary, problems).

    The whole round trip in one call: read the operator's captures, write the
    pictures once into the shared directory, and put the snapshot on the disk
    where signup reads it. No download, no commit, no deploy — the disk
    survives those, and needing a git push to change which posts a new user
    sees is three steps too many for something you want to adjust and look at.

    Pictures are decoded and written HERE rather than at signup, so the first
    person to sign up after a change does not pay for it.
    """
    snapshot = build(source_ids, user_id, note=note, limit=limit)

    for source in snapshot["sources"]:
        for post in source["posts"]:
            if post.get("image"):
                # Written now, and the base64 dropped: the file on disk is the
                # copy that matters, and carrying both doubles the snapshot for
                # nothing. What is kept is the marker pointing at it.
                marker = _store_image(post["image"])
                post.pop("image", None)
                if marker:
                    post["image_ref"] = marker

    if not snapshot["sources"]:
        return None, snapshot["skipped"]

    save(snapshot, LIVE_PATH)
    return summary(snapshot), snapshot["skipped"]


def clear():
    """Go back to the written sample set."""
    try:
        os.remove(LIVE_PATH)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------- import

def load(path=None):
    """The committed snapshot, or None if this install has none.

    None is a supported state, not an error: without a snapshot the built-in
    written set is used, which is what every install had before this existed.
    """
    # The saved one wins. The committed one is the fallback that survives
    # losing the disk, and the written set is the fallback behind that.
    candidates = [path] if path else [LIVE_PATH, SNAPSHOT_PATH]
    snapshot = None
    for target in candidates:
        try:
            with io.open(target, encoding="utf-8") as fh:
                snapshot = json.load(fh)
            break
        except (OSError, ValueError):
            continue
    if snapshot is None:
        return None

    if not isinstance(snapshot, dict) or not snapshot.get("sources"):
        return None
    if snapshot.get("format") != FORMAT_VERSION:
        log.warning("demo snapshot is format %s, expected %s — ignoring",
                    snapshot.get("format"), FORMAT_VERSION)
        return None
    return snapshot


def summary(snapshot=None):
    """What the admin page says about the committed snapshot, or None."""
    snapshot = snapshot or load()
    if not snapshot:
        return None
    sources = snapshot.get("sources", [])
    posts = [p for s in sources for p in s.get("posts", [])]
    return {
        "captured_at": snapshot.get("captured_at", ""),
        "note": snapshot.get("note", ""),
        "sources": len(sources),
        "posts": len(posts),
        # A published snapshot carries markers; a committed one still carries
        # the bytes. Either counts as having a picture.
        "images": sum(1 for p in posts if p.get("image") or p.get("image_ref")),
        "from_capture": sum(s.get("from_capture", 0) for s in sources),
        "names": sorted({s.get("name", "") for s in sources if s.get("name")}),
    }


def image_path(digest):
    """Where a snapshot picture lives once written. Traversal-safe."""
    if not digest or not all(c in "0123456789abcdef" for c in digest):
        return None
    return os.path.join(IMAGE_DIR, "%s.jpg" % digest)


def _store_image(encoded):
    """Write one picture to the shared directory. Returns its marker, or None.

    Named by the hash of its own bytes, so the same picture seeded for the
    thousandth account is still one file on disk.
    """
    try:
        raw = base64.b64decode(encoded)
    except Exception:                         # noqa: BLE001
        return None
    digest = hashlib.sha256(raw).hexdigest()[:24]
    path = image_path(digest)
    if not path:
        return None
    try:
        if not os.path.isfile(path):
            os.makedirs(IMAGE_DIR, exist_ok=True)
            temporary = path + ".part"
            with io.open(temporary, "wb") as fh:
                fh.write(raw)
            os.replace(temporary, path)
    except OSError:
        return None
    return MARKER + digest


def marker_digest(image_url):
    """The digest inside a demo image marker, or None if it isn't one."""
    if not image_url or not str(image_url).startswith(MARKER):
        return None
    return str(image_url)[len(MARKER):]
