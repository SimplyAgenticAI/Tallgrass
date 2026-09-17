/* Checking the comments on your recent posts, one after another.
 *
 * The batch does what a person would: click a post's "N comments", wait for
 * the comments to open — in a pop-up or in place — save them, close the
 * pop-up, next. What must never happen: reading someone else's post as if it
 * were yours, stopping at a post with no comments, or leaving a pop-up open
 * over the next one.
 *
 * Run: node tests/postcheck.test.js
 */
var H = require("./harness");

var FAILURES = [];
function check(name, got, want) {
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

var D = H.makeDoc();
var root = D.el("div");

function add(parent, tag, attrs, text) {
  var e = D.el(tag);
  parent.appendChild(e);
  Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
  if (text) e.textContent = text;
  return e;
}

function comment(parent, author, says) {
  var a = add(parent, "div", { role: "article", "aria-label": "Comment by " + author + " 1h" });
  add(a, "div", { dir: "auto" }, author);
  add(a, "div", { dir: "auto" }, says);
  return a;
}

var banner = add(root, "div", { role: "banner" });
add(banner, "a", { "aria-label": "Jeff Randle" });

var opened = [];
function post(n, author, body, opens) {
  var art = add(root, "div", { "aria-posinset": String(n) });
  add(art, "a", { role: "link", href: "/jeffrandle" }, author);
  add(art, "div", { dir: "auto" }, body);
  add(art, "a", { href: "/jeffrandle/posts/pfbid0" + n }, "2d");
  add(art, "div", { "aria-label": "Send this to friends or post it on your profile" });
  if (opens) {
    var count = add(art, "span", { role: "button" }, opens.count + " comments");
    count.onClick = function () {
      opened.push(author + ":" + n);
      if (opens.inPlace) {
        comment(art, "Inline Person", "Where do I sign up?");
        return;
      }
      var dialog = add(root, "div", { role: "dialog" });
      add(dialog, "a", { href: "/jeffrandle/posts/pfbid0" + n }, "2d");
      opens.comments.forEach(function (c) { comment(dialog, c[0], c[1]); });
      var close = add(dialog, "div", { "aria-label": "Close", role: "button" });
      close.onClick = function () {
        root.children.splice(root.children.indexOf(dialog), 1);
        dialog.isConnected = false;
      };
    };
  }
  add(art, "div", { role: "button", "aria-label": "Like" }, "Like Comment Share");
  return art;
}

post(1, "Jeff Randle", "New website packages are live", {
  count: 2, comments: [["Dana Brooks", "How much?"], ["Marcus Lee", "Do you do restaurants?"]] });
post(2, "Someone Else", "Anyone recommend a plumber?", {
  count: 5, comments: [["Nope", "Not yours"]] });
post(3, "Jeff Randle", "Quiet Sunday", null);
post(4, "Jeff Randle", "Logo refresh for a local bakery", { count: 1, inPlace: true });

var api = H.runScan({ doc: D, root: root }, "/jeffrandle");
api.resetViewerNames();
api.setExpandWait(1);
api.setPostCheckWaits(1, 50, 1);

var saves = [];
chrome.runtime.sendMessage = function (m, cb) {
  if (m.type === "OUTLIER_COMMENTS") saves.push(m.body);
  if (cb) cb({ ok: true, comments: m.body ? m.body.comments.length : 0 });
};

var stages = [];
api.checkMyPosts(10, function (n, saved, stage) { stages.push(stage); }, function (result) {
  console.log("checking your recent posts");
  check("only your posts with comments were opened", opened, ["Jeff Randle:1", "Jeff Randle:4"]);
  check("someone else's post was never touched", opened.indexOf("Someone Else:2"), -1);
  check("two posts checked", result.checked, 2);
  check("  their comments saved, one save per post", saves.length, 2);
  check("  the pop-up post's comments",
        saves[0].comments.map(function (c) { return c.author; }), ["Dana Brooks", "Marcus Lee"]);
  check("  the in-place post's comments",
        saves[1].comments.map(function (c) { return c.author; }), ["Inline Person"]);
  check("  each saved under its own post", [saves[0].post.key, saves[1].post.key].indexOf(undefined), -1);
  check("the pop-up was closed before moving on",
        root.children.filter(function (c) { return c.getAttribute("role") === "dialog"; }).length, 0);
  check("it says how it finished", result.reason, "no more of your posts with comments on this page");
  check("progress was reported", stages.indexOf("saved") !== -1, true);

  console.log();
  console.log("a group where your name can't be found");
  var G = H.makeDoc();
  var groot = G.el("div");
  var gpost = G.el("div");
  groot.appendChild(gpost);
  gpost.setAttribute("aria-posinset", "1");
  var gapi = H.runScan({ doc: G, root: groot }, "/groups/cats/");
  gapi.resetViewerNames();
  gapi.checkMyPosts(5, function () {}, function (r) {
    check("reads nothing rather than other people's posts", [r.checked, /couldn't tell/.test(r.reason)], [0, true]);

    console.log();
    if (FAILURES.length) {
      console.log(FAILURES.length + " FAILURES");
      process.exit(1);
    }
    console.log("your posts, checked one after another");
    process.exit(0);
  });
});
