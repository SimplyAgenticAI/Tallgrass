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
"""

import glob
import logging
import os
import sqlite3
import time

import db

log = logging.getLogger("tallgrass.backup")

BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")

# Enough history to survive a bad day going unnoticed over a weekend, few
# enough that a 1GB disk is not filled by copies of itself.
KEEP = 7


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def run():
    """Take one snapshot and prune old ones. Returns (path, error)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except OSError as exc:
        return None, "Could not create %s: %s" % (BACKUP_DIR, exc)

    # VACUUM INTO refuses to overwrite, and the stamp is only accurate to the
    # second — so pressing "Back up now" in the same second as the automatic
    # one failed with "output file already exists". A suffix rather than a
    # finer clock, because the name is meant to be readable.
    target = os.path.join(BACKUP_DIR, "outlier-%s.db" % _stamp())
    attempt = 1
    while os.path.exists(target) and attempt < 100:
        target = os.path.join(BACKUP_DIR, "outlier-%s-%d.db" % (_stamp(), attempt))
        attempt += 1
    try:
        # A separate connection, so this cannot inherit a transaction.
        conn = sqlite3.connect(db.DB_PATH, timeout=30)
        try:
            # The quoting is ours, not a caller's — target is built above from
            # a timestamp, never from input.
            conn.execute("VACUUM INTO ?", (target,))
        finally:
            conn.close()
    except Exception as exc:                  # noqa: BLE001 - reported, not raised
        return None, "Backup failed: %s" % exc

    # Measured BEFORE pruning. It was measured after, so when prune removed
    # the wrong file the log cheerfully reported 0 bytes for a snapshot that
    # no longer existed.
    size = os.path.getsize(target) if os.path.exists(target) else 0
    prune()
    if not os.path.exists(target):
        return None, "The snapshot was written but then removed by retention."
    log.info("backup written: %s (%d bytes)", target, size)
    return target, None


def _by_age():
    """Snapshot paths, oldest first, ordered by MODIFICATION TIME.

    Not by filename. The stamp is second-resolution, so a second snapshot in
    the same second gets a "-1" suffix — and "-1.db" sorts BEFORE ".db",
    because "-" is 0x2D and "." is 0x2E. Sorting by name therefore treated the
    newest file as the oldest and pruned it immediately: a backup system that
    silently eats its own newest snapshot, which is worse than having none
    because you would believe you were covered.
    """
    paths = glob.glob(os.path.join(BACKUP_DIR, "outlier-*.db"))
    return sorted(paths, key=lambda p: os.path.getmtime(p))


def prune(keep=KEEP):
    """Keep the newest `keep` snapshots, delete the rest."""
    try:
        existing = _by_age()
        for path in existing[:-keep] if keep > 0 else existing:
            os.remove(path)
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
