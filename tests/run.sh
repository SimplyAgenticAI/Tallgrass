#!/bin/sh
# Every test, one command. Run before pushing.
set -e
cd "$(dirname "$0")/.."

echo "--- syntax ---"
for f in extension/*.js static/js/*.js; do node --check "$f"; done
python -c "import ast,glob;[ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('*.py')];print('python ok')"
python -c "
import jinja2, pathlib
env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))
for p in pathlib.Path('templates').glob('*.html'):
    env.parse(p.read_text(encoding='utf-8'), filename=p.name)
print('templates ok')"
python -c "
import json, io
# Bytes, not text: a UTF-8 BOM here once made json.load fail on every start,
# and it is invisible in an editor.
raw = io.open('extension/manifest.json','rb').read()
assert not raw.startswith(b'\xef\xbb\xbf'), 'manifest.json has a UTF-8 BOM'
m = json.loads(raw.decode('utf-8'))
# The Chrome Web Store's own limits, checked here rather than discovered at
# upload. It rejects the package outright and the only clue is a number.
assert len(m['description']) <= 132, 'manifest description is %d chars, max 132' % len(m['description'])
assert len(m['name']) <= 75, 'manifest name is %d chars, max 75' % len(m['name'])
print('manifest ok — v%s, description %d chars' % (m['version'], len(m['description'])))"

echo "--- no duplicate definitions ---"
# A duplicated block once meant edits landed in code the browser never ran.
node -e '
var src = require("fs").readFileSync("extension/content.js", "utf8").split("\n");
var seen = {}, dupes = [];
src.forEach(function (l, i) {
  var m = l.match(/^\s*(?:function (\w+)|var ([A-Z_]+) =)/);
  if (!m) return;
  var n = m[1] || m[2];
  if (seen[n]) dupes.push(n + " (lines " + seen[n] + ", " + (i + 1) + ")");
  else seen[n] = i + 1;
});
if (dupes.length) { console.error("DUPLICATE DEFINITIONS: " + dupes.join(", ")); process.exit(1); }
console.log("content.js clean");
'

echo "--- scan captures posts ---"
node tests/scan.test.js
echo "--- extraction ---"
node tests/extract.test.js
echo "--- captions ---"
node tests/caption.test.js
echo "--- timestamps ---"
node tests/timestamp.test.js
echo "--- capture delivery ---"
node tests/delivery.test.js
echo "--- service worker ---"
node tests/worker.test.js
echo "--- self-update ---"
node tests/updater.test.js
echo "--- frontend survives a bare page ---"
node tests/frontend.test.js
echo "--- what a new account sees ---"
python tests/onboarding.test.py
echo "--- onboarding email ---"
python tests/outreach.test.py
echo "--- real posts as sample data ---"
python tests/snapshot.test.py
echo "--- streamed json ---"
python tests/jsonstream.test.py
echo "--- hooks from real posts ---"
python tests/hooks.test.py
echo "--- ranking without the text ---"
python tests/paging.test.py
echo "--- pictures are kept ---"
python tests/images.test.py
echo "--- money and backups ---"
python tests/safety.test.py
echo "--- capture resilience ---"
python tests/capture.test.py
echo "--- scoring accuracy rules ---"
python tests/scoring.test.py
echo "--- accounts, keys and sessions ---"
python tests/auth.test.py
echo "--- password reset ---"
python tests/reset.test.py
echo "--- entitlement ---"
python tests/billing.test.py
echo "--- cross-user health ---"
python tests/users.test.py
echo "--- capture health canary ---"
python tests/health.test.py
echo "--- app consistency ---"
python tests/consistency.test.py
