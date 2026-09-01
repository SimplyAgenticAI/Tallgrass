"""Keeping the pictures.

A post's image was stored as Facebook's own CDN link and nothing else. Those
links are signed and carry an expiry — a day or two — so every scanned post
lost its picture shortly after it was captured, and the feed filled up with
broken boxes. The post survived; what it looked like did not, and what a post
looked like is half of why it worked.

So the image is copied here the first time anybody looks at it, and served
from this app afterwards. Fetched on demand rather than during capture: a
batch of fifty posts would otherwise wait on fifty downloads before the
extension heard anything back, and the feed is normally opened the same day a
scan runs, while the links are still alive.

Downscaled on the way in. A Facebook photo is 100–300KB and this disk is 1GB
shared with the database and its backups; at 640px it is nearer 30KB, which is
the difference between keeping a few thousand pictures and keeping tens of
thousands. It is a thumbnail on a card and a picture on a post page — neither
needs the original.

The cache is bounded and evicts the least recently LOOKED AT, not the oldest.
A post from March that somebody still opens is worth more than one from
yesterday that nobody has.
"""

import hashlib
import io
import logging
import os

import db

log = logging.getLogger("tallgrass.images")

CACHE_DIR = os.path.join(db.DATA_DIR, "images")

# Long edge, in pixels. Big enough for the detail page on a retina screen,
# small enough that the disk holds tens of thousands.
MAX_EDGE = 640
JPEG_QUALITY = 82

# What the cache may occupy. The disk is 1GB and also holds the database and
# seven backups of it, so this leaves room for both to grow.
MAX_CACHE_BYTES = 400 * 1024 * 1024

# Refuse anything implausible before decoding it.
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def _name(post_id):
    # Hashed so the filename says nothing about the account it belongs to.
    return hashlib.sha256(("post-%s" % post_id).encode()).hexdigest()[:24] + ".jpg"


def path_for(post_id):
    return os.path.join(CACHE_DIR, _name(post_id))


def cached(post_id):
    """The stored path if we have this picture, else None."""
    path = path_for(post_id)
    return path if os.path.isfile(path) else None


def store(post_id, raw):
    """Downscale and save. Returns (path, error).

    Anything Pillow cannot open is rejected here rather than served: an HTML
    error page from a CDN is bytes too, and serving it as an image would put a
    broken picture back on the card by a longer route.
    """
    try:
        from PIL import Image
    except ImportError:
        return None, "Pillow is not installed."

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:                  # noqa: BLE001
        return None, "That was not a readable image (%s)." % exc

    try:
        # EXIF orientation, honoured before resizing — otherwise a phone photo
        # is stored on its side.
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)

        if image.mode not in ("RGB", "L"):
            # Transparency flattened onto white rather than lost to black,
            # which is what a bare convert("RGB") does to a PNG logo.
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha = image.convert("RGBA").split()[-1]
            background.paste(image.convert("RGB"), mask=alpha)
            image = background

        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

        os.makedirs(CACHE_DIR, exist_ok=True)
        path = path_for(post_id)
        # Written beside and moved into place, so a failed write never leaves
        # a half-image that later looks like a cache hit.
        temporary = path + ".part"
        image.save(temporary, "JPEG", quality=JPEG_QUALITY, optimize=True,
                   progressive=True)
        os.replace(temporary, path)
    except Exception as exc:                  # noqa: BLE001
        return None, "Could not store that image (%s)." % exc

    prune()
    return (path if os.path.isfile(path) else None), None


def fetch_and_store(post_id, url):
    """Copy a post's picture here. Returns (path, error).

    The fetch is the same guarded one the vision feature uses, so a stored
    image_url pointing at the server's own network is refused here too.
    """
    import remix
    try:
        raw, media_type = remix._fetch_image(url)
    except remix._BlockedURL as exc:
        return None, "That image link cannot be read: %s." % exc
    except Exception as exc:                  # noqa: BLE001
        return None, "Could not fetch it (%s)." % exc

    if len(raw) > MAX_SOURCE_BYTES:
        return None, "That image is too large."
    if not media_type.startswith("image/"):
        return None, "That link did not return an image."
    return store(post_id, raw)


def usage():
    """(bytes, count) currently held."""
    total = 0
    count = 0
    try:
        for entry in os.scandir(CACHE_DIR):
            if entry.is_file() and entry.name.endswith(".jpg"):
                total += entry.stat().st_size
                count += 1
    except OSError:
        pass
    return total, count


def prune(limit=MAX_CACHE_BYTES):
    """Evict least-recently-USED until the cache fits.

    By access time, not creation time. A picture from months ago that somebody
    still opens is worth keeping over one from yesterday that nobody has
    looked at since it arrived.
    """
    try:
        entries = [e for e in os.scandir(CACHE_DIR)
                   if e.is_file() and e.name.endswith(".jpg")]
    except OSError:
        return

    total = sum(e.stat().st_size for e in entries)
    if total <= limit:
        return

    # Oldest access first.
    entries.sort(key=lambda e: e.stat().st_atime)
    removed = 0
    for entry in entries:
        if total <= limit:
            break
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            total -= size
            removed += 1
        except OSError:
            continue
    if removed:
        log.info("image cache: evicted %d least-recently-used", removed)
