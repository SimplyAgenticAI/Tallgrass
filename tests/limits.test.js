/* Posts to scan, chosen from the panel.
 *
 * The limit a group, page or profile scan stops at always existed, but only as
 * a slider in the toolbar popup. The panel now sets it too — and it must be
 * the SAME setting, saved the same way, or the popup and the panel would
 * disagree about when a scan stops.
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
check("a scan stops at 200 by default", api.postLimits(), { maxPosts: 200, maxMinutes: 10 });

api.setPostTarget(500);
check("choosing 500 in the panel raises the limit now", api.postLimits().maxPosts, 500);
check("  with the time ceiling scaled as the popup scales it", api.postLimits().maxMinutes, 25);
chrome.storage.local.get(["maxPosts", "maxMinutes"], function (stored) {
  check("  and saved to the setting the popup's slider uses",
        [stored.maxPosts, stored.maxMinutes], [500, 25]);
});

api.setPostTarget(50);
check("a small scan keeps a five-minute floor", api.postLimits(), { maxPosts: 50, maxMinutes: 5 });

var saved = H.runScan(H.buildPage([]), "/groups/1234567890/", { maxPosts: 100 });
check("a limit chosen earlier is what the next page load uses", saved.postLimits().maxPosts, 100);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("one limit, set from either place");
process.exit(0);
