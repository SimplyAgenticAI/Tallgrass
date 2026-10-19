/* Posts to scan, chosen from the panel.
 *
 * The limit a group, page or profile scan stops at always existed, but only as
 * a slider in the toolbar popup. The panel now sets it too — and it must be
 * the SAME setting, saved the same way, or the popup and the panel would
 * disagree about when a scan stops.
 *
 * It must also be ACHIEVABLE, which is what this file mostly exists for now.
 * Reported: a 500-post scan kept stopping around 250. The ceiling was
 * round(n / 20) — three seconds per post — while one scroll step costs
 * STEP_EVERY_MS (2.2s) and yields at most ONE new post, usually well under one
 * once duplicates, shells, comments and tall video posts come out. So the
 * budget could not be met even in the best case, and in practice it ran out at
 * about half. The arithmetic is asserted here rather than the number, because
 * a number can be changed without anybody noticing it has gone back under the
 * cost of the work.
 *
 * Run: node tests/limits.test.js
 */
var H = require("./harness");

var FAILURES = [];
function check(name, got, want) {
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

var api = H.runScan(H.buildPage([]), "/groups/1234567890/");
check("a scan stops at 200 by default", api.postLimits().maxPosts, 200);

api.setPostTarget(500);
check("choosing 500 in the panel raises the limit now", api.postLimits().maxPosts, 500);
chrome.storage.local.get(["maxPosts", "maxMinutes"], function (stored) {
  check("  and saved to the setting the popup's slider uses",
        stored.maxPosts, 500);
});

api.setPostTarget(50);
check("a small scan keeps a five-minute floor", api.postLimits(),
      { maxPosts: 50, maxMinutes: 5 });

var saved = H.runScan(H.buildPage([]), "/groups/1234567890/", { maxPosts: 100 });
check("a limit chosen earlier is what the next page load uses",
      saved.postLimits().maxPosts, 100);

console.log();
console.log("the clock allows the work to actually be done");

/* One step per 2.2 seconds, and a step captures at most one post. So the
 * minimum conceivable time for n posts is n * 2.2 seconds, and a budget at or
 * under that is a budget that cannot be met. The real yield is lower again,
 * which is why the test asks for headroom rather than for feasibility by a
 * hair. */
var STEP_SECONDS = 2.2;
[50, 100, 200, 500].forEach(function (n) {
  api.setPostTarget(n);
  var minutes = api.postLimits().maxMinutes;
  var floorMinutes = n * STEP_SECONDS / 60;
  check("  " + n + " posts: " + minutes + " min beats the " +
        Math.ceil(floorMinutes) + " min a perfect run would take",
        minutes >= floorMinutes, true);
  check("    with room for steps that capture nothing",
        minutes >= floorMinutes * 1.5, true);
});

api.setPostTarget(500);
check("500 posts is no longer given 25 minutes",
      api.postLimits().maxMinutes > 25, true);

/* A stored ceiling is never read back.
 *
 * Somebody who had already chosen 500 had 25 minutes saved against it — the
 * too-tight figure — so reading storage would have kept the bug for exactly
 * the people who hit it. The ceiling is derived from the target on load. */
var stale = H.runScan(H.buildPage([]), "/groups/1234567890/",
                      { maxPosts: 500, maxMinutes: 25 });
check("a stale ceiling saved by an older build is recomputed, not adopted",
      stale.postLimits().maxMinutes > 25, true);

console.log();
console.log("a scan that has stopped capturing says so, and says which fault");

/* The second way to stop at half, and the one the clock was accidentally
 * handling. idleScrolls only counts steps where the article count did NOT grow,
 * so a feed that keeps rendering posts the extractor refuses resets it to zero
 * every step and never trips it — the scan just scrolled a page it could not
 * read until the clock ran out.
 *
 * Driven with the test owning the clock, the same way dragonfly.test.js does,
 * because the alternative is a test that waits three real minutes. */
function stuckRun(articlesAfter) {
  var page = H.buildPage([]);
  var run = H.runScan(page, "/groups/1234567890/");
  var realNow = Date.now;
  var started = realNow();
  try {
    run.startAutoScroll();
    // Three minutes and a bit later, having captured nothing.
    Date.now = function () { return started + 3.2 * 60 * 1000; };
    // Empty articles: they count as rendered posts and carry nothing the
    // extractor will accept, which is the fault being reproduced.
    for (var i = 0; i < articlesAfter; i++) {
      var art = page.doc.el("div");
      art.setAttribute("role", "article");
      page.root.appendChild(art);
    }
    run.stepScan();
  } finally {
    Date.now = realNow;
    try { run.stopAutoScroll(); } catch (e) {}
  }
  return run;
}

var quiet = stuckRun(0);
check("it stops rather than scrolling on", quiet.scanning(), false);
check("  and says it is stuck, with the count",
      /Stuck at 0 of/.test(quiet.stats().done || ""), true);
check("  naming the fault: nothing more arrived",
      /stopped loading more/.test(quiet.stats().done || ""), true);

var refused = stuckRun(40);
check("posts loading but none readable also stops", refused.scanning(), false);
check("  and is reported as the OTHER fault",
      /none could be read/.test(refused.stats().done || ""), true);
check("  with how many arrived, so the report names a number",
      /loaded \d+ more posts/.test(refused.stats().done || ""), true);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("one limit, set from either place — and reachable");
process.exit(0);
