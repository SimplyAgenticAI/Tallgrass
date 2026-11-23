/* A scan keeps its pace as the page fills up.
 *
 * Reported on 31.2: smooth to about a hundred posts, then slower, then
 * stalled near three hundred. Every pass re-checked every post on the page
 * from the first one, re-read cards that could never be captured for the
 * rest of the scan, and each scroll step was cancelled halfway by a second
 * smooth scroll. This file holds each of those fixed, and the panel log that
 * now says how long passes take and exactly why a scan stopped.
 *
 * Run: node tests/speed.test.js
 */
var H = require("./harness");

var FAILURES = [];
function check(name, got, want) {
  if (arguments.length === 2) { want = true; }
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

function withClock(fn) {
  var real = Date.now;
  var now = 1700000000000;
  Date.now = function () { return now; };
  try { fn(function (ms) { now += ms; }); } finally { Date.now = real; }
}

function articles(page) {
  return page.root.children.filter(function (el) {
    return el.getAttribute && el.getAttribute("role") === "article";
  });
}

console.log("a post read in full is not re-checked on later passes");
var page = H.buildPage([
  { body: "A finished post with its reactions already loaded on it.", likes: 120 },
  { body: "A second finished post, also with plenty of numbers on it.", likes: 80 }
]);
var api = H.runScan(page, "/groups/growth");
api.scanPosts();
check("both captured on the first pass", api.queue().length, 2);
var looked = 0;
articles(page).forEach(function (art) {
  var real = art.querySelectorAll;
  art.querySelectorAll = function (sel) { looked++; return real.call(art, sel); };
});
api.scanPosts();
api.scanPosts();
check("  and later passes never search inside them again", looked, 0);
check("  nor capture them twice", api.queue().length, 2);

console.log();
console.log("a card that can never be captured stops being read");
withClock(function (advance) {
  var twin = H.buildPage([
    { body: "Exactly the same post, rendered twice by Facebook here.", likes: 40, author: "Dana Fletcher" },
    { body: "Exactly the same post, rendered twice by Facebook here.", likes: 40, author: "Dana Fletcher" }
  ]);
  var run = H.runScan(twin, "/groups/growth");
  var copy = articles(twin)[1];
  for (var i = 0; i < 5; i++) { run.scanPosts(); advance(1000); }
  check("one row for the two copies", run.queue().length, 1);
  check("  five quick reads are not enough to give up on the copy",
        !!copy.__tallgrassDead, false);
  for (var j = 0; j < 5; j++) { run.scanPosts(); advance(2000); }
  check("  a few more seconds of it, and it is given up on", copy.__tallgrassDead, true);
  var looked2 = 0;
  var real = copy.querySelectorAll;
  copy.querySelectorAll = function (sel) { looked2++; return real.call(copy, sel); };
  run.scanPosts();
  check("  after which it is never searched again", looked2, 0);
  check("  and the post itself was never given up on",
        !!articles(twin)[0].__tallgrassDead, false);
});

console.log();
console.log("a card that fills in late, inside the grace, is still captured");
withClock(function (advance) {
  var late = H.buildPage([{ body: "", likes: 0, bare: true, author: "Sam Reyes" }]);
  var run = H.runScan(late, "/groups/growth");
  run.scanPosts(); advance(2200);
  run.scanPosts(); advance(2200);
  check("nothing to capture while it is empty", run.queue().length, 0);
  var art = articles(late)[0];
  art.children.forEach(function (c) {
    if (c.getAttribute("dir") === "auto") c.textContent = "Filled in a few seconds late, the way Facebook does.";
    if (/reactions/.test(c.getAttribute("aria-label") || "")) c.setAttribute("aria-label", "64 reactions");
  });
  run.scanPosts();
  check("  captured once it has filled in", run.queue().length, 1);
  check("  and not given up on", !!art.__tallgrassDead, false);
});

console.log();
console.log("a confident comment verdict is not worked out again");
var cpage = H.buildPage([
  { body: "Reads like a post, but was already judged to be a reply.", likes: 30 }
]);
var crun = H.runScan(cpage, "/groups/growth");
var cart = articles(cpage)[0];
var verdict = { isPost: false, confident: true, why: "test" };
cart.__tallgrassVerdict = verdict;
crun.scanPosts();
check("the cached verdict is the one used", cart.__tallgrassVerdict === verdict, true);
check("  so it is skipped, not captured", crun.queue().length, 0);

console.log();
console.log("one scroll per step, and it is a real one");
var spage = H.buildPage([
  { body: "Somewhere near the bottom of what has loaded so far.", likes: 10 }
]);
var srun = H.runScan(spage, "/groups/growth");
var intoView = 0;
articles(spage).forEach(function (art) {
  art.scrollIntoView = function () { intoView++; };
});
global.document.hidden = false;
srun.startAutoScroll();
var before = global.window.scrollBy.calls || 0;
srun.stepScroll();
check("the page is scrolled once in the step", (global.window.scrollBy.calls || 0) - before, 1);
check("  by more than a screen", global.window.scrollBy.last.top, Math.round(900 * 1.4));
check("  smoothly while visible, so every post passes through view",
      global.window.scrollBy.last.behavior, "smooth");
check("  and no second scroll is started to cancel it", intoView, 0);

console.log();
console.log("the panel log says why a scan stopped, how long it took, and how long passes take");
srun.scanPosts();
srun.stopAutoScroll(null, "Stopped — 1 posts captured");
// Not necessarily the newest line: the stop also sends what was queued.
var line = srun.stats().log.filter(function (l) { return /Stopped —/.test(l); })[0] || "";
check("the stop is logged", /Stopped — 1 posts captured/.test(line), true);
check("  with the scan's length", / min/.test(line), true);
check("  and its pass timing", /passes avg \d+ ms, max \d+ ms/.test(line), true);

var rpage = H.buildPage([{ body: "A post on a page where capture gets switched off.", likes: 5 }]);
var rrun = H.runScan(rpage, "/groups/growth");
rrun.startAutoScroll();
rrun.stopAutoScroll("Capture turned off");
check("a stop with only a reason is logged too",
      rrun.stats().log.some(function (l) { return /■ Stopped: Capture turned off/.test(l); }), true);
var count = rrun.stats().log.length;
rrun.stopAutoScroll("Capture turned off");
check("  once, not again when nothing was running", rrun.stats().log.length, count);

withClock(function (advance) {
  var tpage = H.buildPage([{ body: "A post on a long scan, timed as it goes along.", likes: 9 }]);
  var trun = H.runScan(tpage, "/groups/growth");
  trun.startAutoScroll();
  trun.scanPosts();
  advance(5000);
  trun.scanPosts();
  var quiet = trun.stats().log.filter(function (l) { return / pass \d+ ms/.test(l); }).length;
  check("pass timing is not written on every pass", quiet, 0);
  advance(31000);
  trun.scanPosts();
  var timed = trun.stats().log.filter(function (l) { return /pass \d+ ms \(avg \d+, max \d+\) · \d+ on page/.test(l); });
  check("  but every half minute or so", timed.length, 1);
  trun.stopAutoScroll();
});

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("a scan keeps its pace");
process.exit(0);
