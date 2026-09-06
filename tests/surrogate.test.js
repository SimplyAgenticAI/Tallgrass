/* Truncating text must not cut a character in half.
 *
 * A live capture died with:
 *   UnicodeEncodeError: 'utf-8' codec can't encode character '\ud835'
 *
 * U+D835 is HALF of a character. The groups this app is pointed at write in
 * mathematical "bold" text — 𝗕𝗼𝗹𝗱 — which lives outside the Basic
 * Multilingual Plane. A JavaScript string is UTF-16, so each of those
 * characters is TWO code units, and slice(0, n) can land between them. The
 * string then ends in an unpaired surrogate, which is not encodable as UTF-8
 * at all, and the dashboard rejected the entire batch rather than one post.
 *
 * cut() exists to trim that orphan off. These tests pin the boundary, because
 * the failure only appears when the limit falls in exactly the wrong place —
 * which is why it survived every scan until a post happened to be the wrong
 * length.
 *
 * Run: node tests/surrogate.test.js
 */
var fs = require("fs");
var path = require("path");

var FAILURES = [];

function check(name, got, want) {
  var ok = got === want;
  console.log((ok ? "  ok   " : " FAIL  ") + name +
              (ok ? "" : "   got " + JSON.stringify(got) +
                    ", want " + JSON.stringify(want)));
  if (!ok) FAILURES.push(name);
}

// Lift cut() out of content.js rather than duplicating it, so this tests the
// function that actually runs.
var source = fs.readFileSync(
  path.join(__dirname, "..", "extension", "content.js"), "utf8");
var match = source.match(/function cut\(text, limit\) \{[\s\S]*?\n  \}/);
if (!match) {
  console.log("FAIL: cut() not found in content.js");
  process.exit(1);
}
var cut = new Function("return " + match[0].trim())();

var BOLD_A = "\u{1D5D4}";        // 𝗔 — one character, two UTF-16 code units

console.log("a whole character is never left as half of one");
// Limit lands exactly between the two halves of BOLD_A. This is the case that
// crashed: slice() happily returns the high surrogate on its own.
var text = "abc" + BOLD_A + "def";
check("slice alone splits it",
      "abc".length + 1 === text.slice(0, 4).length &&
      text.slice(0, 4).charCodeAt(3) >= 0xd800 &&
      text.slice(0, 4).charCodeAt(3) <= 0xdbff, true);

var trimmed = cut(text, 4);
check("cut drops the orphan", trimmed, "abc");
check("  leaving nothing unpaired", hasLoneSurrogate(trimmed), false);

console.log();
console.log("but a limit that does not split anything keeps everything");
check("just before the character", cut(text, 3), "abc");
check("both halves together", cut(text, 5), "abc" + BOLD_A);
check("past the end", cut(text, 100), text);

console.log();
console.log("a string of bold text survives at every limit");
// The real shape: a whole post written in bold. Every cut point must produce
// something encodable, not just the convenient ones.
var bold = "";
for (var i = 0; i < 40; i++) bold += String.fromCodePoint(0x1d5d4 + (i % 26));
var bad = 0;
for (var limit = 0; limit <= bold.length + 2; limit++) {
  if (hasLoneSurrogate(cut(bold, limit))) bad++;
}
check("no cut point leaves half a character", bad, 0);

console.log();
console.log("ordinary text is untouched");
check("plain ascii", cut("hello world", 5), "hello");
check("empty", cut("", 10), "");
check("null becomes empty", cut(null, 10), "");
check("undefined becomes empty", cut(undefined, 10), "");
// Accented characters are single code units — nothing to protect, nothing to
// lose.
check("accents are not surrogates", cut("café", 4), "café");
// Emoji are astral too, and get the same protection.
check("an emoji is kept whole", cut("hi 👋", 4), "hi ");
check("  or kept entirely", cut("hi 👋", 5), "hi 👋");

function hasLoneSurrogate(value) {
  for (var i = 0; i < value.length; i++) {
    var code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      var next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      i++;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
}

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES: " + FAILURES.join(", "));
  process.exit(1);
}
console.log("text is truncated without breaking characters");
process.exit(0);
