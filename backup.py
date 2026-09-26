"""Copies of the database, because there were none.

Everything captured lives in one SQLite file on one Render disk. There was no
snapshot, no dump and no export of it anywhere — a corrupted file or a deleted
disk took every account's work with it, and it was the only failure on the
list that could not be undone.

VACUUM INTO rather than copying the file: it takes a consistent snapshot of a
live database, which `cp` does not. A copy taken mid-write is a copy of a
half-written database, and the moment you need it is the moment you find out.

READ THIS BEFORE TRUSTING IT
----------------------------
A backup on the same disk protects against the database being corrupted,
truncated or wrongly deleted. It does NOT protect against losing the disk,
because it is on the disk. Offsite is a decision only the operator can make —
it needs credentials for somewhere else — so `latest()` exists to hand the
newest snapshot to the admin page for download, which is the offsite copy a
person can actually make today.

Snapshots are gzipped (`outlier-<stamp>.db.gz`). To put one back: download it,
`gunzip` it, and replace the database file — or call `restore_to` for the same
thing in one step. Nothing in the app overwrites the live database; a restore is
deliberately a decision somebody makes with their hands.
"""

import glob
import gzip
import logging
import os
import shutil
import sqlite3
import time

import db

log = logging.getLogger("tallgrass.backup")

BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")

# Enough history to survive a bad day going unnoticed over a weekend, few
# enough that a 1GB disk is not filled by copies of itself.
KEEP = 7

# Snapshots are gzipped, which is the difference between this feature being
# affordable and being the thing that fills the disk.
#
# A SQLite file is mostly text and empty page padding; gzip takes it to roughly
# a fifth to a tenth. Seven uncompressed copies of a 60MB database is 420MB on a
# 1GB disk that also holds the database itself and up to 400MB of cached post
# images — and NOTHING anywhere checked free space, so the first symptom of
# running out would have been writes failing: captures lost, silently, for
# everyone. Compressed, the same history is nearer 50MB.
SUFFIX = ".db.gz"

# A second ceiling, in bytes, because "seven" says nothing about size: seven
# snapshots of a database that has grown tenfold is the same problem again.
# Whichever limit bites first wins.
BUDGET_BYTES = 200 * 1024 * 1024

# Never write a snapshot that could be the thing that fills the disk. VACUUM
# INTO needs room for a whole copy before it is compressed, so the requirement
# is the database's own size with headroom on top.
MIN_FREE_MULTIPLE = 2.5
MIN_FREE_FLOOR = 50 * 1024 * 1024


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _db_bytes():
    try:
        return os.path.getsize(db.DB_PATH)
    except OSError:
        return 0


def _free_bytes(path=None):
    """Free space on the disk holding the data directory, or None if unknown."""
    try:
        return shutil.disk_usage(path or db.DATA_DIR).free
    except Exception:                         # noqa: BLE001 - never a hard failure
        return None


def _needed_free():
    return max(int(_db_bytes() * MIN_FREE_MULTIPLE), MIN_FREE_FLOOR)


def dir_bytes(path):
    """Total size of the files directly inside `path`. 0 if unreadable."""
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_file():
                        total += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def storage():
    """What is on the disk, for the admin page.

    The image cache has been reported for a while; the database and its
    snapshots never were, and they are the two that grow without anybody
    choosing to. Free space was not shown at all, which is the number that
    decides whether the next capture succeeds.
    """
    try:
        import images
        image_bytes, image_count = images.usage()
    except Exception:                         # noqa: BLE001
        image_bytes, image_count = 0, 0

    free = _free_bytes()
    backups = dir_bytes(BACKUP_DIR)
    database = _db_bytes()
    return {
        "db_bytes": database,
        "backup_bytes": backups,
        "backup_budget": BUDGET_BYTES,
        "image_bytes": image_bytes,
        "image_count": image_count,
        "free_bytes": free,
        "used_bytes": database + backups + image_bytes,
        # What run() will refuse below, so the page can say so before it bites
        # rather than after.
        "needed_free": _needed_free(),
        "low": free is not None and free < _needed_free(),
    }


def run():
    """Take one snapshot and prune old ones. Returns (path, error)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except OSError as exc:
        return None, "Could not create %s: %s" % (BACKUP_DIR, exc)

    # Pruned first, so yesterday's copies are not competing for the space this
    # one needs.
    prune()

    free = _free_bytes()
    needed = _needed_free()
    if free is not None and free < needed:
        return None, (
            "Not enough disk space for a snapshot: %d MB free, %d MB needed. "
            "Old snapshots have already been pruned, so the database itself is "
            "what is filling the disk." % (free // 1048576, needed // 1048576))

    # VACUUM INTO refuses to overwrite, and the stamp is only accurate to the
    # second — so pressing "Back up now" in the same second as the automatic
    # one failed with "output file already exists". A suffix rather than a
    # finer clock, because the name is meant to be readable.
    target = os.path.join(BACKUP_DIR, "outlier-%s%s" % (_stamp(), SUFFIX))
    attempt = 1
    while os.path.exists(target) and attempt < 100:
        target = os.path.join(BACKUP_DIR,
                              "outlier-%s-%d%s" % (_stamp(), attempt, SUFFIX))
        attempt += 1

    # VACUUM INTO writes a real database file; it cannot write into a gzip
    # stream. So the snapshot is taken uncompressed next to its final name and
    # compressed straight afterwards, and the uncompressed one is removed
    # whatever happens — a half-finished pair on a disk this small is the
    # problem this whole change is about.
    raw = target[:-3]                          # ".db.gz" -> ".db"
    try:
        # A separate connection, so this cannot inherit a transaction.
        conn = sqlite3.connect(db.DB_PATH, timeout=30)
        try:
            # The quoting is ours, not a caller's — target is built above from
            # a timestamp, never from input.
            conn.execute("VACUUM INTO ?", (raw,))
        finally:
            conn.close()
    except Exception as exc:                  # noqa: BLE001 - reported, not raised
        _remove(raw)
        return None, "Backup failed: %s" % exc

    try:
        with open(raw, "rb") as plain, gzip.open(target, "wb", compresslevel=6) as gz:
            shutil.copyfileobj(plain, gz, length=1024 * 1024)
    except Exception as exc:                  # noqa: BLE001
        _remove(raw)
        _remove(target)
        return None, "Could not compress the snapshot: %s" % exc
    finally:
        _remove(raw)

    # Measured BEFORE pruning. It was measured after, so when prune removed
    # the wrong file the log cheerfully reported 0 bytes for a snapshot that
    # no longer existed.
    size = os.path.getsize(target) if os.path.exists(target) else 0
    prune()
    if not os.path.exists(target):
        return None, "The snapshot was written but then removed by retention."
    log.info("backup written: %s (%d bytes compressed, database is %d bytes)",
             target, size, _db_bytes())
    return target, None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _by_age():
    """Snapshot paths, oldest first, ordered by MODIFICATION TIME.

    Not by filename. The stamp is second-resolution, so a second snapshot in
    the same second gets a "-1" suffix — and "-1.db" sorts BEFORE ".db",
    because "-" is 0x2D and "." is 0x2E. Sorting by name therefore treated the
    newest file as the oldest and pruned it immediately: a backup system that
    silently eats its own newest snapshot, which is worse than having none
    because you would believe you were covered.
    """
    # Both names: snapshots taken before compression are still on the disk of
    # every install that has been running, and they still have to be listed,
    # downloaded and eventually pruned.
    paths = (glob.glob(os.path.join(BACKUP_DIR, "outlier-*" + SUFFIX))
             + glob.glob(os.path.join(BACKUP_DIR, "outlier-*.db")))
    return sorted(set(paths), key=lambda p: os.path.getmtime(p))


def prune(keep=KEEP, budget=BUDGET_BYTES):
    """Keep the newest snapshots, within both limits.

    Count first, then bytes. "Seven" says nothing about size, and a database
    that has grown tenfold makes seven copies the same disk problem again — so
    whichever limit bites first decides.
    """
    try:
        existing = _by_age()
        doomed = list(existing[:-keep] if keep > 0 else existing)
        surviving = existing[len(doomed):]

        if budget:
            sizes = []
            for path in surviving:
                try:
                    sizes.append((path, os.path.getsize(path)))
                except OSError:
                    continue
            total = sum(size for _path, size in sizes)
            # Oldest first, and never the newest one: a retention rule that can
            # delete the only current snapshot is worse than no rule, because
            # you would believe you were covered.
            for path, size in sizes[:-1]:
                if total <= budget:
                    break
                doomed.append(path)
                total -= size

        for path in doomed:
            _remove(path)
        if doomed:
            log.info("pruned %d old snapshot(s)", len(doomed))
    except OSError as exc:
        log.warning("could not prune backups: %s", exc)


def listing():
    """Newest first, for the admin page. Never raises."""
    try:
        paths = list(reversed(_by_age()))      # newest first, by mtime
    except OSError:
        return []
    out = []
    for path in paths:
        try:
            out.append({
                "name": os.path.basename(path),
                "bytes": os.path.getsize(path),
                "modified": time.strftime("%Y-%m-%d %H:%M UTC",
                                          time.gmtime(os.path.getmtime(path))),
            })
        except OSError:
            continue
    return out


def latest():
    """Path of the newest snapshot, or None."""
    paths = _by_age()
    return paths[-1] if paths else None


def restore_to(path, dest):
    """Write a snapshot out as a plain database file. Returns (path, error).

    Snapshots are gzipped, so "download it and put it back" needs one step in
    between. This is that step, and it is also what proves a snapshot is a
    real database rather than a file of the right size — which is the only
    property of a backup that matters.
    """
    try:
        if path.endswith(SUFFIX):
            with gzip.open(path, "rb") as gz, open(dest, "wb") as out:
                shutil.copyfileobj(gz, out, length=1024 * 1024)
        else:
            shutil.copyfile(path, dest)
    except Exception as exc:                  # noqa: BLE001
        return None, "Could not expand that snapshot: %s" % exc
    return dest, None


def path_for(name):
    """Resolve a snapshot by name, or None.

    Rejects anything that is not a plain file inside BACKUP_DIR. The name
    arrives from a query string, and 'the admin page asked for it' is not a
    reason to let a request read whatever it likes off the disk.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    candidate = os.path.abspath(os.path.join(BACKUP_DIR, name))
    if os.path.dirname(candidate) != os.path.abspath(BACKUP_DIR):
        return None
    return candidate if os.path.isfile(candidate) else None
