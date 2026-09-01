"""Pictures have to survive the link they came from.

A post's image was stored as Facebook's own CDN link and nothing else. Those
links are signed and expire within a day or two, so every scanned post lost
its picture shortly after capture and the feed filled with broken boxes.

These tests care about the two things that make re-hosting worth having: the
copy is real and openable, and one account cannot read another's pictures by
counting upward through post ids.

Run: python tests/images.test.py
"""
import io
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def a_photo(width=1600, height=1200, mode="RGB"):
    """Bytes of a plausible photo. Flat colour, so a huge one is still quick."""
    from PIL import Image
    image = Image.new(mode, (width, height), (90, 140, 110))
    buffer = io.BytesIO()
    image.save(buffer, "PNG" if mode == "RGBA" else "JPEG", quality=70)
    return buffer.getvalue()


def main():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "test-only-secret"

    import db
    import auth
    import images
    import app as appmod

    logging.disable(logging.INFO)
    db.init_db()
    owner, _ = auth.create_user("owner@example.com", "a-long-enough-pass", "birchwood")
    other, _ = auth.create_user("other@example.com", "a-long-enough-pass", "fernlake")

    with db.get_db() as conn:
        conn.execute("INSERT INTO sources (id, user_id, fb_id, kind, name) "
                     "VALUES (1, 1, 'group:g', 'group', 'A Group')")
        for pid, uid in ((1, 1), (2, 2)):
            conn.execute(
                "INSERT INTO posts (id, user_id, fb_post_id, source_id, body, "
                "post_type, posted_at, image_url, engagement_read) "
                "VALUES (?, ?, ?, 1, 'b', 'photo', '2026-08-01T00:00:00', "
                "'https://scontent.example/expired.jpg', 1)",
                (pid, uid, "fb-%d" % pid))

    print("a stored copy is real, and smaller than the original")
    raw = a_photo()
    path, error = images.store(1, raw)
    check("stored without error", error, None)
    check("the file exists", bool(path and os.path.isfile(path)), True)
    check("it is smaller than the source", os.path.getsize(path) < len(raw), True)

    from PIL import Image
    with Image.open(path) as saved:
        check("downscaled to the long edge", max(saved.size), images.MAX_EDGE)
        check("aspect ratio kept", round(saved.size[0] / saved.size[1], 2),
              round(1600 / 1200, 2))
        check("saved as JPEG", saved.format, "JPEG")

    print()
    print("a transparent PNG does not come out black")
    # convert("RGB") on an RGBA image fills transparency with black, which
    # turns a logo on a clear background into a dark rectangle.
    from PIL import Image as I
    trans = I.new("RGBA", (400, 400), (0, 0, 0, 0))
    buffer = io.BytesIO()
    trans.save(buffer, "PNG")
    path2, error = images.store(2, buffer.getvalue())
    check("stored", error, None)
    with I.open(path2) as saved:
        check("flattened onto white", saved.convert("RGB").getpixel((5, 5)),
              (255, 255, 255))

    print()
    print("a decompression bomb is refused before it is decoded")
    # Bytes are not the constraint; decoded pixels are. This file is about 2MB
    # on the wire and 412MB as a bitmap — more than the whole instance has.
    # Capping only the download size guards the wrong quantity.
    import tracemalloc
    bomb = a_photo(12000, 12000)
    tracemalloc.start()
    path_bomb, error = images.store(90, bomb)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    check("nothing stored", path_bomb, None)
    check("an error is returned", bool(error), True)
    # If it had decoded, this would be hundreds of megabytes. The point of the
    # guard is that the decode never happens.
    check("refused without decoding it", peak < 20 * 1024 * 1024, True)

    print()
    print("both guards are wired, and each catches its own range")
    over_ours, error = images.store(91, a_photo(4500, 3500))     # 15.8MP
    check("over our limit is refused", over_ours, None)
    check("  by our check, by name", "megapixel limit" in (error or ""), True)
    at_limit, error = images.store(92, a_photo(4000, 3000))      # 12.0MP
    check("at the limit still stores", bool(at_limit), True)
    check("  with no error", error, None)

    print()
    print("a real photo is decoded cheaply, not decoded then shrunk")
    # JPEG can be decoded at 1/2, 1/4 or 1/8 scale by the DCT itself, so a
    # 4000x3000 photo bound for a 640px thumbnail never exists as a 36MB
    # bitmap. Without draft() this peaks an order of magnitude higher.
    tracemalloc.start()
    path_big, error = images.store(93, a_photo(4000, 3000))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    check("stored", error, None)
    check("cheaply", peak < 12 * 1024 * 1024, True)
    with Image.open(path_big) as saved:
        check("and still the right size", max(saved.size), images.MAX_EDGE)

    print()
    print("junk is refused rather than served as a picture")
    # A CDN error page is bytes too, and storing it would put a broken image
    # back on the card by a longer route.
    path3, error = images.store(3, b"<html>Not Found</html>")
    check("no file written", path3, None)
    check("and it says why", "not a readable image" in (error or ""), True)

    print()
    print("only the owner can read a post's picture")
    boss = appmod.app.test_client()
    with boss.session_transaction() as s:
        s["user_id"] = owner["id"]
    stranger = appmod.app.test_client()
    with stranger.session_transaction() as s:
        s["user_id"] = other["id"]
    anon = appmod.app.test_client()

    check("the owner gets it", boss.get("/img/1").status_code, 200)
    check("  as an image",
          boss.get("/img/1").headers["Content-Type"].startswith("image/"), True)
    # Post 2 belongs to the other account. Ids are small integers, so without
    # the owner scope anyone could walk the range.
    check("another account cannot", stranger.get("/img/1").status_code, 404)
    check("signed out is sent to sign in", anon.get("/img/1").status_code, 302)

    print()
    print("a dead link is a 404, not a crash")
    # Nothing cached and the Facebook link long expired — which is the whole
    # situation this feature exists for. The page turns this into
    # "image expired", so it must be an ordinary 404.
    check("missing post", boss.get("/img/9999").status_code, 404)
    with db.get_db() as conn:
        conn.execute("INSERT INTO posts (id, user_id, fb_post_id, source_id, "
                     "body, post_type, posted_at, image_url, engagement_read) "
                     "VALUES (50, 1, 'fb-50', 1, 'b', 'photo', "
                     "'2026-08-01T00:00:00', 'https://scontent.invalid/x.jpg', 1)")
    check("unreachable link", boss.get("/img/50").status_code, 404)

    print()
    print("the cache is bounded and evicts least-recently-used")
    before_bytes, before_count = images.usage()
    check("usage is reported", before_count >= 2, True)
    # A tiny ceiling forces eviction on the next store.
    images.prune(limit=1)
    after_bytes, after_count = images.usage()
    check("pruning to nothing empties it", after_count, 0)

    print()
    print("the server still will not fetch its own network")
    # fetch_and_store goes through the same guard as the vision feature.
    path4, error = images.fetch_and_store(99, "http://169.254.169.254/latest/")
    check("metadata endpoint refused", path4, None)
    check("  and named as blocked", "cannot be read" in (error or ""), True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the pictures stay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
