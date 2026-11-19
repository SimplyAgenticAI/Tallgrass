/* Auto-scroll used to stop on its own after a couple of posts.
 *
 * Two separate stops, both reproduced here:
 *
 *   The first time a page was identified, that counted as "moved to a new
 *   group", so the first read ended the scan. Start had to be pressed again.
 *
 *   Six steps with no new article counted as the end of the feed. Facebook
 *   lazy-loads, and a virtualized feed does not grow the article count, so
 *   a pause of about thirteen seconds was called the end. Posts captured by
 *   the mutation observer during the settle did not count either, because
 *   only this step's own return value was looked at.
 *
 * A nested feed was also never the thing that moved: only the window was
 * scrolled, so Facebook was never asked for the next batch and the quiet
 * counter ran out on the posts already on screen.
 *
 * Run: node tests/autoscroll.test.js
 */
var H = require("./harness");

var FAILURES = [];
function check(name, got, want) {
  if (arguments.length === 2) want = true;
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) FAILURES.push(name);
}

function posts(n) {
  var out = [];
  for (var i = 0; i < n; i++) {
    out.push({
      author: "Author Person " + i,
      body: "A real post number " + i + " with enough caption text to keep.",
      likes: "10 reactions"
    });
  }
  return out;
}

function articleNodes(page) {
  return page.root.children.filter(function (el) {
    return el.getAttribute && el.getAttribute("role") === "article";
  });
}

function detach(parent, el) {
  var at = parent.children.indexOf(el);
  if (at >= 0) parent.children.splice(at, 1);
}

function addArticle(page, n) {
  var art = page.doc.el("div");
  art.setAttribute("role", "article");
  var head = page.doc.el("a");
  head.setAttribute("role", "link");
  head.textContent = "Late Author " + n;
  art.appendChild(head);
  var body = page.doc.el("div");
  body.setAttribute("dir", "auto");
  body.textContent = "Brand new post " + n + " swapped in by a virtualized feed.";
  art.appendChild(body);
  var counts = page.doc.el("div");
  counts.setAttribute("aria-label", (20 + n) + " reactions");
  art.appendChild(counts);
  var share = page.doc.el("div");
  share.setAttribute("aria-label", "Send this to friends or post it on your profile");
  art.appendChild(share);
  var bar = page.doc.el("div");
  bar.setAttribute("role", "button");
  bar.setAttribute("aria-label", "Like");
  bar.textContent = "Like Comment Share";
  art.appendChild(bar);
  page.root.appendChild(art);
  return art;
}

// Where the document scroller is sitting. The harness does not move
// scrollTop when scrollBy is called, so a test sets the position itself.
function place(page, top, height) {
  page.root.scrollTop = top;
  page.root.scrollHeight = height;
  page.root.clientHeight = 900;
}

function withClock(fn) {
  var real = Date.now;
  var now = 1700000000000;
  Date.now = function () { return now; };
  try {
    fn(function (ms) { now += ms; });
  } finally {
    Date.now = real;
  }
}

function stop(api) {
  try { if (api && api.scanning()) api.stopAutoScroll(); } catch (e) {}
}

console.log("the first read of a page is not a navigation");
var first = H.runScan(H.buildPage(posts(2)), "/groups/growth/");
first.startAutoScroll();
first.stepScroll();
first.stepScan();
check("the scan is still running after the posts on screen are read",
      first.scanning(), true);
check("  and those posts were actually captured", first.stats().sent > 0, true);
check("  and it did not announce a new group", first.stats().lastError, null);
stop(first);

console.log();
console.log("changing group still stops the scan");
var moved = H.runScan(H.buildPage(posts(2)), "/groups/growth/");
moved.startAutoScroll();
moved.stepScroll();
moved.stepScan();
check("it was going", moved.scanning(), true);
global.location = new URL("https://www.facebook.com/groups/othergroup/");
moved.stepScroll();
moved.stepScan();
check("a different group stops it", moved.scanning(), false);
check("  and that stop is not reported as the end of the feed",
      /Reached the end/.test(moved.stats().done || ""), false);
stop(moved);

console.log();
console.log("a short quiet gap at the bottom is not the end");
withClock(function (advance) {
  var page = H.buildPage(posts(2));
  var api = H.runScan(page, "/groups/growth/");
  // Already at the bottom of what Facebook has loaded. This is the state
  // a lazy-load pause looks like: nothing new yet, scroller cannot move.
  place(page, 3200, 4000);
  api.startAutoScroll();
  api.stepScroll();
  api.stepScan();
  check("started, and the first read did not stop it", api.scanning(), true);
  for (var i = 0; i < 7; i++) {
    advance(2200);
    api.stepScroll();
    api.stepScan();
  }
  check("seven quiet steps (about fifteen seconds) keeps going",
        api.scanning(), true);
  for (var j = 0; j < 5; j++) {
    advance(2200);
    api.stepScroll();
    api.stepScan();
  }
  check("a long quiet gap at the bottom does end it", api.scanning(), false);
  check("  and the panel says the feed ended",
        /Reached the end/.test(api.stats().done || ""), true);
  stop(api);
});

console.log();
console.log("not at the bottom, so silence is not the end");
withClock(function (advance) {
  var page = H.buildPage(posts(2));
  var api = H.runScan(page, "/groups/growth/");
  place(page, 0, 8000);
  api.startAutoScroll();
  api.stepScroll();
  api.stepScan();
  for (var i = 0; i < 12; i++) {
    advance(2200);
    api.stepScroll();
    api.stepScan();
  }
  check("twelve quiet steps while there is still page left keeps going",
        api.scanning(), true);
  stop(api);
});

console.log();
console.log("posts read during the settle count, even when the article total does not");
withClock(function (advance) {
  var page = H.buildPage(posts(2));
  var api = H.runScan(page, "/groups/growth/");
  place(page, 3200, 4000);
  api.startAutoScroll();
  api.stepScroll();
  api.stepScan();
  var sent = api.stats().sent;
  for (var i = 0; i < 12; i++) {
    advance(2200);
    api.stepScroll();
    // Virtualized: one article leaves, one arrives, the count stays put.
    // The mutation observer reads the new one before this step's scan.
    var nodes = articleNodes(page);
    detach(page.root, nodes[0]);
    addArticle(page, 100 + i);
    api.scanPosts();
    api.stepScan();
  }
  check("the article count stayed flat", articleNodes(page).length, 2);
  check("the new posts were still captured", api.stats().sent > sent, true);
  check("and the scan did not call that the end", api.scanning(), true);
  stop(api);
});

console.log();
console.log("a nested feed is what gets scrolled");
function armFeed(page, overflowY, role) {
  var feed = page.doc.el("div");
  if (role) feed.setAttribute("role", role);
  feed.scrollHeight = 5000;
  feed.clientHeight = 800;
  feed.scrollTop = 100;
  feed.scrolls = [];
  feed.scrollBy = function (opts) {
    feed.scrolls.push(opts || {});
    feed.scrollTop += (opts && opts.top) || 0;
  };
  page.root.children.forEach(function (el) {
    if (el.getAttribute && el.getAttribute("role") === "article") el.parentElement = feed;
  });
  feed.parentElement = page.root;
  global.window.getComputedStyle = function (node) {
    if (node === feed) return { overflowY: overflowY, overflow: overflowY };
    return {};
  };
  return feed;
}

var nestedPage = H.buildPage(posts(3));
var nested = H.runScan(nestedPage, "/groups/growth/");
var feed = armFeed(nestedPage, "auto", "feed");
nested.startAutoScroll();
global.document.hidden = false;
nested.stepScroll();
check("the feed container is scrolled", feed.scrolls.length > 0, true);
check("  by most of its own height", feed.scrolls[0] && feed.scrolls[0].top, 680);
check("  smoothly while the tab is visible",
      feed.scrolls[0] && feed.scrolls[0].behavior, "smooth");
global.document.hidden = true;
nested.stepScroll();
check("and instantly while the tab is hidden",
      feed.scrolls[feed.scrolls.length - 1] && feed.scrolls[feed.scrolls.length - 1].behavior,
      "auto");
stop(nested);

var hiddenPage = H.buildPage(posts(2));
var hiddenFeedRun = H.runScan(hiddenPage, "/groups/growth/");
var hiddenFeed = armFeed(hiddenPage, "hidden", "main");
hiddenFeedRun.startAutoScroll();
hiddenFeedRun.stepScroll();
check("a feed box that clips instead of overflowing is still scrolled",
      hiddenFeed.scrolls.length > 0, true);
stop(hiddenFeedRun);

console.log();
console.log("one broken tick does not stop the loop");
var shaky = H.runScan(H.buildPage(posts(2)), "/groups/growth/");
shaky.startAutoScroll();
var origQuery = global.document.querySelectorAll;
global.document.querySelectorAll = function () {
  throw new Error("tick blew up");
};
var threw = false;
try { shaky.stepScroll(); } catch (e) { threw = true; }
check("the error does not escape the tick", threw, false);
check("  and the scan is still running", shaky.scanning(), true);
global.document.querySelectorAll = origQuery;
var scrolledBefore = global.window.scrollBy.calls || 0;
shaky.stepScroll();
check("  the next tick still scrolls",
      (global.window.scrollBy.calls || 0) > scrolledBefore, true);
stop(shaky);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("auto-scroll keeps going");
process.exit(0);
