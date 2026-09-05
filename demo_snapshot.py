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

# Beside the code, not on the data disk: this is content that ships with a
# deploy, the same as a template. A file on the persistent disk would exist on
# whichever instance happened to write it and nowhere else.
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

# A snapshot is committed to the repository, so it has to stay a sane size. At
# roughly 30KB a picture this is a few megabytes, which is fine; ten times that
# is not something to put in git.
MAX_POSTS_PER_SOURCE = 120
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

def build(source_ids, user_id, note=""):
    """Freeze these sources into a snapshot dict. Operator-only.

    Reads the operator's OWN captures — the caller is responsible for the
    sources belonging to them, and app.py scopes the query it passes here.
    """
    import images

    snapshot = {
        "format": FORMAT_VERSION,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": note or "",
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
                (source_id, user_id, MAX_POSTS_PER_SOURCE)).fetchall()

            posts = []
            for row in rows:
                hours = _hours_since(row["posted_at"])
                if hours is None:
                    # Without a time there is no age to reconstruct, and a post
                    # dated to the moment of signup is a lie of a different
                    # kind. Skipped rather than guessed.
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

            snapshot["sources"].append({
                "fb_id": source["fb_id"],
                "kind": source["kind"] or "group",
                "name": source["name"] or "",
                "url": source["url"] or "",
                "member_count": source["member_count"] or 0,
                "posts": posts,
            })

    return snapshot


def save(snapshot, path=None):
    with io.open(path or SNAPSHOT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)
    return path or SNAPSHOT_PATH


# --------------------------------------------------------------------- import

def load(path=None):
    """The committed snapshot, or None if this install has none.

    None is a supported state, not an error: without a snapshot the built-in
    written set is used, which is what every install had before this existed.
    """
    target = path or SNAPSHOT_PATH
    try:
        with io.open(target, encoding="utf-8") as fh:
            snapshot = json.load(fh)
    except (OSError, ValueError):
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
        "images": sum(1 for p in posts if p.get("image")),
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
