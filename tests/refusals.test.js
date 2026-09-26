/* What the scanner does when the dashboard says no.
 *
 * A rejected batch is put back at the front of the queue, which is right for a
 * dropped connection and wrong for an answer that will be the same next time.
 * A free account at its post cap (402) and an account over the hourly ingest
 * ceiling (429) refuse every batch — so re-queueing meant offering the same
 * posts again and again for as long as the scan ran. The server-side guard
 * added to stop runaway ingest would have produced a runaway client.
 *
 * And a batch can be accepted in part: the dashboard trims what would cross a
 * limit and reports the remainder. Ignoring that left "sent 50, 30 new" on
 * screen with twenty posts gone, which is the failure this HUD exists to
 * prevent.
 *
 * Run: node tests/refusals.test.js
 */
var H = require("./harness");
var runScan = H.runScan, buildPage = H.buildPage;

var FAILURES = [];

function check(name, got, want) {
  if (arguments.length === 2) { want = true; }
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

function scanWith(reply) {
  global.__testSends = [];
  var page = buildPage([
    { body: "A post that needs to reach the dashboard", likes: 90, comments: 4, shares: 2 }
  ]);
  var api = runScan(page, "/groups/1234567890/", { reply: reply });
  api.scanPosts();
  return api;
}

function captures() {
  return (global.__testSends || []).filter(function (m) {
    return m.type === "OUTLIER_CAPTURE";
  }).length;
}

console.log("a connection problem is held and retried");
var flaky = scanWith({ ok: false, error: "Could not reach the dashboard" });
flaky.flush();
check("the batch is kept", flaky.queue().length, 1);
check("  the reason is shown", flaky.stats().lastError, "Could not reach the dashboard");
check("  and it was offered once so far", captures(), 1);
flaky.flush();
check("  and offered again, which is the point", captures(), 2);

console.log();
console.log("the plan cap is not retried — it would refuse every time");
var capped = scanWith({
  ok: false, retryable: false, upgrade: true,
  error: "Free covers 1,000 posts and you've reached it."
});
capped.flush();
check("it was offered once", captures(), 1);
check("the dashboard's own words are shown",
      capped.stats().lastError, "Free covers 1,000 posts and you've reached it.");
check("the queue is not holding it for another go", capped.queue().length, 0);
capped.flush();
check("  so nothing is sent again", captures(), 1);
check("and the scan has stopped", capped.scanning ? capped.scanning() : false, false);

console.log();
console.log("the hourly ceiling behaves the same way");
var throttled = scanWith({
  ok: false, retryable: false,
  error: "That's 10,000 posts in an hour, which is far more than a scan sends."
});
throttled.flush();
throttled.flush();
check("offered once and not again", captures(), 1);
check("with the reason shown",
      /10,000 posts in an hour/.test(throttled.stats().lastError || ""), true);

console.log();
console.log("a batch accepted in PART says so");
var trimmed = scanWith({ ok: true, new: 1, over_cap: 20, throttled: 0 });
trimmed.flush();
check("what landed is counted", trimmed.stats().sent, 1);
check("and the shortfall is reported, not swallowed",
      /20 posts went past your plan's limit/.test(trimmed.stats().lastError || ""), true);

var overHour = scanWith({ ok: true, new: 1, over_cap: 0, throttled: 7 });
overHour.flush();
check("the hourly case is worded for the hourly limit",
      /7 posts were over the hourly limit/.test(overHour.stats().lastError || ""), true);

var whole = scanWith({ ok: true, new: 1, over_cap: 0, throttled: 0 });
whole.flush();
check("and a batch that all landed says nothing", whole.stats().lastError, null);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES: " + FAILURES.join(", "));
  process.exit(1);
}
console.log("a no is taken as a no, and a partial is never called whole");
// Explicit, because a scan leaves its own timers behind and node would sit
// waiting on them rather than ending.
process.exit(0);
