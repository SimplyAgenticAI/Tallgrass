/* Members and followers, read from the header and nowhere else.
 *
 * A group page is full of other people's numbers: the right rail lists related
 * groups with their member counts, and a post can say "we just hit 10K
 * followers". Any of those taken as the source's own count is a wrong number
 * on the dashboard, which is worse than no number. So these tests put the
 * decoys on the page next to the real count and insist only the real one is
 * read.
 *
 * Run: node tests/audience.test.js
 */
var H = require("./harness");
var runScan = H.runScan;

var FAILURES = [];

function check(name, got, want) {
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

function page(path, build) {
  var D = H.makeDoc();
  var root = D.el("div");
  function add(parent, tag, text, attrs) {
    var e = D.el(tag);
    if (text) e.textContent = text;
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    parent.appendChild(e);
    return e;
  }
  build(root, add);
  return runScan({ doc: D, root: root }, path);
}

function source(kind, path) {
  return { fb_id: kind + ":x", kind: kind, url: "https://www.facebook.com" + path };
}

console.log("parsing");
check("24K", runScan(H.buildPage([]), "/groups/1/").parseAudience("24K"), 24000);
check("1.2M", runScan(H.buildPage([]), "/groups/1/").parseAudience("1.2M"), 1200000);
check("1,204", runScan(H.buildPage([]), "/groups/1/").parseAudience("1,204"), 1204);
check("80M is not capped", runScan(H.buildPage([]), "/groups/1/").parseAudience("80M"), 80000000);
check("words are not a number", runScan(H.buildPage([]), "/groups/1/").parseAudience("lots"), 0);

console.log();
console.log("a group");

var api = page("/groups/cats/", function (root, add) {
  // The rail first, so a first-match reader would take it.
  add(root, "a", "310K members", { href: "/groups/catsofinstagram/members/" });
  add(root, "a", "24K members", { href: "https://www.facebook.com/groups/cats/members/" });
});
check("its own members link, not a related group's",
      api.readAudience(source("group", "/groups/cats")), 24000);

api = page("/groups/cats/", function (root, add) {
  // A suggestion in the side rail, placed first so a first-match reader takes it.
  var rail = add(root, "div", null, { role: "complementary" });
  add(rail, "span", "Public group · 88K members");
  add(root, "span", "Private group · 9.1K members");
});
check("the header line when there is no link",
      api.readAudience(source("group", "/groups/cats")), 9100);

api = page("/groups/cats/", function (root, add) {
  var article = add(root, "div", null, { role: "article" });
  add(article, "a", "50K members", { href: "/groups/cats/members/" });
  add(article, "span", "Public group · 50K members");
});
check("never from inside a post", api.readAudience(source("group", "/groups/cats")), 0);

api = page("/groups/cats/", function (root, add) {
  add(root, "a", "See all members", { href: "/groups/cats/members/" });
});
check("a members link with no count is no count",
      api.readAudience(source("group", "/groups/cats")), 0);

console.log();
console.log("a page or a profile");

api = page("/janedoe", function (root, add) {
  add(root, "a", "900 followers", { href: "/someoneelse/followers" });
  add(root, "a", "1.3K followers", { href: "/janedoe/followers" });
  add(root, "a", "500 friends", { href: "/janedoe/friends" });
});
check("its own followers, not a friend count or someone else's",
      api.readAudience(source("profile", "/janedoe")), 1300);

api = page("/janedoe", function (root, add) {
  add(root, "a", "2,041 followers", { href: "https://www.facebook.com/janedoe?sk=followers" });
});
check("the ?sk=followers form", api.readAudience(source("profile", "/janedoe")), 2041);

api = page("/p/Joes-Diner-100012345678/", function (root, add) {
  add(root, "a", "12K followers", { href: "/p/Joes-Diner-100012345678/followers/" });
});
check("a Page at /p/", api.readAudience(source("page", "/p/Joes-Diner-100012345678")), 12000);

api = page("/janedoe", function (root, add) {
  var article = add(root, "div", null, { role: "article" });
  add(article, "a", "10K followers", { href: "/janedoe/followers" });
});
check("a post celebrating a milestone is not the count",
      api.readAudience(source("profile", "/janedoe")), 0);

api = page("/", function () {});
check("the home feed has no count",
      api.readAudience({ fb_id: "feed:home", kind: "feed", isFeed: true,
                         url: "https://www.facebook.com/" }), 0);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("only the source's own audience is read");
process.exit(0);
