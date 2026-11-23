/* A healthy scan keeps the panel still.
 *
 * Reported on 31.3: "Waiting to send" and "Filed under" appeared after every
 * pass and disappeared at the next send four seconds later, so the panel
 * bounced up and down for the whole scan. A healthy scan always has a few
 * posts waiting for the next send; that is not news. The rows now appear only
 * when there is a problem: an error, a page that cannot be named, or posts
 * that have sat unsent for twelve seconds.
 *
 * Run: node tests/quiet_hud.test.js
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

function hudOf(page) {
  return page.root.children.filter(function (el) { return el.id === "tallgrass-hud"; })[0];
}

console.log("posts waiting for the next send are not news");
withClock(function (advance) {
  var page = H.buildPage([
    { body: "A post read on this pass and queued for the next send.", likes: 70 },
    { body: "Another one, queued alongside it, which is perfectly normal.", likes: 40 }
  ]);
  var api = H.runScan(page, "/groups/growth");
  var hud = hudOf(page);
  check("the panel is on the page", !!hud, true);
  api.scanPosts();
  check("two posts are waiting", api.queue().length, 2);
  var text = hud.textContent;
  check("  but no Waiting to send row", /Waiting to send/.test(text), false);
  check("  no Filed under row", /Filed under/.test(text), false);
  check("  and no warning", /waiting to send/.test(text), false);

  advance(5000);
  api.scanPosts();
  check("still quiet a few seconds later", /Waiting to send|Filed under/.test(hud.textContent), false);

  console.log();
  console.log("posts that have sat unsent for twelve seconds are");
  advance(8000);
  api.scanPosts();
  text = hud.textContent;
  check("Waiting to send appears", /Waiting to send/.test(text), true);
  check("  with where they would be filed", /Filed under/.test(text), true);
  check("  and the warning, since nothing has been sent", /waiting to send/.test(text), true);

  console.log();
  console.log("and a send that goes through puts the panel back");
  api.flush();
  api.scanPosts();
  check("the queue is empty", api.queue().length, 0);
  check("  and the rows are gone again", /Waiting to send|Filed under/.test(hud.textContent), false);
});

console.log();
console.log("a send that fails is shown at once");
withClock(function () {
  var page = H.buildPage([{ body: "A post whose batch the dashboard turns away.", likes: 12 }]);
  var api = H.runScan(page, "/groups/growth");
  var hud = hudOf(page);
  api.scanPosts();
  api.stats().lastError = "Dashboard rejected the batch";
  api.scanPosts();
  check("Filed under shows with the error", /Filed under/.test(hud.textContent), true);
  check("  and so does the queue it left behind", /Waiting to send/.test(hud.textContent), true);
});

console.log();
console.log("a redraw that changes nothing leaves the panel alone");
var page = H.buildPage([{ body: "One post, read once, and then the page sits still.", likes: 33 }]);
var api = H.runScan(page, "/groups/growth");
api.scanPosts();
api.flush();
api.scanPosts();
var hud = hudOf(page);
function firstRow() {
  var found = null;
  (function walk(el) {
    if (found) return;
    (el.children || []).forEach(function (c) {
      if (!found && /Captured|Posts to scan/.test(c.textContent) && c.children.length) found = c;
    });
    (el.children || []).forEach(walk);
  })(hud);
  return found;
}
var before = firstRow();
api.scanPosts();
api.scanPosts();
check("the same rows are still the ones on screen", firstRow() === before, true);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("a healthy scan keeps the panel still");
process.exit(0);
