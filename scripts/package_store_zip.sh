#!/bin/sh
# Chrome Web Store upload zip for the extension in this repo.
#
# manifest.json sits at the archive root. Markdown and this script are left
# out. The result is unstamped: do not upload the zip that /extension/download
# serves. That one is stamped with the origin that served it, which is right
# for a hand-loaded copy and wrong for the store.
set -e
cd "$(dirname "$0")/.."
python3 - << 'PY'
import json
import os
import zipfile

root = os.getcwd()
ext = os.path.join(root, "extension")
with open(os.path.join(ext, "manifest.json"), encoding="utf-8") as handle:
    version = json.load(handle)["version"]
out = os.path.join(root, "tallgrass-extension-v%s.zip" % version)
skip = {".md", ".sh"}
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
    for dirpath, dirnames, filenames in os.walk(ext):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name == ".DS_Store" or os.path.splitext(name)[1] in skip:
                continue
            path = os.path.join(dirpath, name)
            archive.write(path, os.path.relpath(path, ext).replace(os.sep, "/"))
with zipfile.ZipFile(out) as archive:
    names = archive.namelist()
if "manifest.json" not in names:
    raise SystemExit("manifest.json is not at the archive root: %s" % names[:8])
extra = [n for n in names if n.endswith(".md") or n.endswith(".sh")]
if extra:
    raise SystemExit("docs leaked into the zip: %s" % extra)
print("wrote %s (%d files), manifest.json at the archive root" % (
    os.path.basename(out), len(names)))
PY
