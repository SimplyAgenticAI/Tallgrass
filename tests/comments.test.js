/* Who commented, and did you answer them.
 *
 * Phase 0 of reply drafting: the thread has to read right before anything is
 * drafted from it. A reply tool that calls an answered comment "unanswered"
 * makes you look careless in public, so these tests are mostly about the ways
 * that could happen — a different Jeff replying, replies nested inside their
 * comment instead of after it, and replies folded away out of sight.
 *
 * The real-page check is the comment report saved from the popup; this pins
 * the logic so the fixes that report prompts cannot quietly undo each other.
 *
 * Run: node tests/comments.test.js
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

var api = runScan(H.buildPage([]), "/groups/1/");

console.log("labels");
check("a comment", api.parseCommentLabel("Comment by Jane Doe 2 days ago"),
      { kind: "comment", author: "Jane Doe", to: null });
check("a reply names who it answers",
      api.parseCommentLabel("Reply by Jeff Randle to Jane Doe's comment 1 day ago"),
      { kind: "reply", author: "Jeff Randle", to: "Jane Doe" });
check("a curly apostrophe",
      api.parseCommentLabel("Reply by Jeff Randle to Jane Doe’s comment 3h"),
      { kind: "reply", author: "Jeff Randle", to: "Jane Doe" });
check("no age at all", api.parseCommentLabel("Comment by Ana Ruiz"),
      { kind: "comment", author: "Ana Ruiz", to: null });
check("a post is not a comment", api.parseCommentLabel("Jane Doe's post"), null);

// Built strictly top-down: the harness orders elements by when they were
// attached, so a child attached before its parent would read as coming first.
var D = H.makeDoc();
var root = D.el("div");

function add(parent, tag, attrs, text) {
  var e = D.el(tag);
  parent.appendChild(e);
  Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
  if (text) e.textContent = text;
  return e;
}

function comment(parent, label, author, says) {
  var a = add(parent, "div", { role: "article", "aria-label": label });
  add(a, "div", { dir: "auto" }, author);
  add(a, "div", { dir: "auto" }, says);
  add(a, "div", { role: "button" }, "Reply");
  return a;
}

var banner = add(root, "div", { role: "banner" });
add(banner, "a", { "aria-label": "Jeff Randle" });

var dialog = add(root, "div", { role: "dialog" });
add(dialog, "div", { dir: "auto" }, "New website packages are live this week");

comment(dialog, "Comment by Jane Doe 2 days ago", "Jane Doe", "How much for the website package?");
comment(dialog, "Reply by Jeff Randle to Jane Doe's comment 1 day ago", "Jeff Randle", "Sent you a DM!");

comment(dialog, "Comment by Mark Twain 3 hours ago", "Mark Twain", "Do you do logos too?");

comment(dialog, "Comment by Sara Lee 5h", "Sara Lee", "Great post");
add(dialog, "span", { role: "button" }, "View 2 replies");

comment(dialog, "Comment by Jeff Randle 1 hour ago", "Jeff Randle", "Thanks everyone");

comment(dialog, "Comment by Tom Hanks 2 days ago", "Tom Hanks", "Is this still available?");
comment(dialog, "Reply by Jeff Smith to Tom Hanks's comment 1 day ago", "Jeff Smith", "Following");

// The nested shape: the reply lives inside its comment.
var nested = comment(dialog, "Comment by Ana Ruiz 1 day ago", "Ana Ruiz", "Can I book a call?");
comment(nested, "Reply by Jeff Randle to Ana Ruiz's comment 20 hours ago", "Jeff Randle", "Yes, link sent");

var badge = comment(dialog, "Comment by Lee Chan 4 days ago", "Lee Chan", "");
// "Top fan" sits where the text would be, and must not be read as the comment.
badge.children[1].textContent = "Top fan";
add(badge, "div", { dir: "auto" }, "Where are you based?");

add(dialog, "span", { role: "button" }, "View more comments");

// Noise outside the post dialog, which must be ignored.
comment(root, "Comment by Someone Else 1 day ago", "Someone Else", "Not this post");

api = runScan({ doc: D, root: root }, "/jeffrandle");
api.resetViewerNames();
var r = api.readCommentThread();

function verdictOf(author) {
  return r.threads.filter(function (c) { return c.author === author; })
    .map(function (c) { return c.verdict; })[0];
}

console.log();
console.log("a real thread");
check("reads from the open post, not the page", r.scope, "post dialog");
check("knows who you are", r.viewer, ["jeff randle"]);
check("top-level comments", r.threads.length, 7);
check("replies are not top-level", r.comments.length - r.threads.length, 3);
check("your reply answers it", verdictOf("Jane Doe"), "answered");
check("no reply is unanswered", verdictOf("Mark Twain"), "unanswered");
check("folded replies are unknown, never unanswered", verdictOf("Sara Lee"), "unknown");
check("your own comment is yours", verdictOf("Jeff Randle"), "yours");
check("a different Jeff is not you", verdictOf("Tom Hanks"), "unanswered");
check("a reply nested inside its comment still counts", verdictOf("Ana Ruiz"), "answered");
check("the comment text is read", r.threads[0].text, "How much for the website package?");
check("a badge is not the comment",
      r.threads.filter(function (c) { return c.author === "Lee Chan"; })[0].text,
      "Where are you based?");
check("folded comments are flagged", r.moreComments, 1);
check("nothing outside the dialog",
      r.comments.some(function (c) { return c.author === "Someone Else"; }), false);

console.log();
console.log("you, from the comment box, with no name in the banner");
// The shape of a real post dialog: Facebook keeps another dialog mounted
// first, the banner carries only "Your profile", and the one thing on the
// page that names you is the composer under the post.
D = H.makeDoc();
root = D.el("div");
var bare = add(root, "div", { role: "banner" });
add(bare, "a", { "aria-label": "Your profile" });
add(root, "div", { role: "dialog" }, "Notifications");
var post = add(root, "div", { role: "dialog" });
comment(post, "Comment by Jeff Randle 1w", "Jeff Randle", "Some seasons of building feel like progress.");
comment(post, "Comment by Daniel Medina 2w", "Daniel Medina", "quack!");
add(post, "span", { role: "button" }, "View 1 reply");
comment(post, "Comment by Chris M Utter 2w", "Chris M Utter", "I can vouch for both the guys in this image.");
add(post, "div", {}, "Comment as Jeff Randle");

api = runScan({ doc: D, root: root }, "/TheLucidMage89");
api.resetViewerNames();
r = api.readCommentThread();
check("the post dialog, not the first dialog", r.scope, "post dialog");
check("named by the comment box", r.viewerFrom, { "jeff randle": "composer" });
check("so your comment is yours", verdictOf("Jeff Randle"), "yours");
check("a folded reply is unclear", verdictOf("Daniel Medina"), "unknown");
check("and an unreplied comment is unanswered", verdictOf("Chris M Utter"), "unanswered");

console.log();
console.log("what is sent to the dashboard");
D = H.makeDoc();
root = D.el("div");
post = add(root, "div", { role: "dialog" });
add(post, "div", { dir: "auto" }, "Some seasons of building feel like progress");
var jane = comment(post, "Comment by Jane Doe 2 days ago", "Jane Doe", "How much?");
add(jane, "a", { href: "/jeffrandle/posts/pfbid02abc?comment_id=111" }, "2d");
var reply = comment(post, "Reply by Jeff Randle to Jane Doe's comment 1 day ago", "Jeff Randle", "Sent a DM");
add(reply, "a", { href: "/jeffrandle/posts/pfbid02abc?comment_id=111&reply_comment_id=222" }, "1d");
comment(post, "Comment by Mark Twain 3h", "Mark Twain", "Logos too?");
add(post, "div", {}, "Comment as Jeff Randle");

api = runScan({ doc: D, root: root }, "/jeffrandle/posts/pfbid02abc");
api.resetViewerNames();
var body = api.commentPayload();
check("the post is keyed on its id", body.post.key, "p:pfbid02abc");
check("the post links to itself", body.post.url, "https://www.facebook.com/jeffrandle/posts/pfbid02abc");
check("and is named by its own words", body.post.title, "Some seasons of building feel like progress");
check("a comment is keyed on Facebook's comment id", body.comments[0].key, "c:111");
check("a reply on its reply id", body.comments[1].key, "c:222");
check("  and points at its comment", body.comments[1].parent_key, "c:111");
check("the reply carries no verdict of its own", body.comments[1].verdict, undefined);
check("a comment with no link is keyed on its words",
      /^h:/.test(body.comments[2].key), true);
check("verdicts travel", body.comments.map(function (c) { return c.verdict; }),
      ["answered", undefined, "unanswered"]);

console.log();
console.log("quick respond on Facebook");
D = H.makeDoc();
root = D.el("div");
post = add(root, "div", { role: "dialog" });
comment(post, "Comment by Jeff Randle 1w", "Jeff Randle", "Thanks for all the support");
var ana = comment(post, "Comment by Ana Ruiz 1 day ago", "Ana Ruiz", "Can I book a call?");
comment(ana, "Reply by Tom Hanks to Ana Ruiz's comment 20 hours ago", "Tom Hanks", "Me too");
comment(post, "Comment by Mark Twain 3h", "Mark Twain", "Logos too?");
add(post, "div", {}, "Comment as Jeff Randle");

api = runScan({ doc: D, root: root }, "/jeffrandle/posts/pfbid02abc");
api.resetViewerNames();

var anaEl = post.children[1];
var ownReply = api.ownReplyButton(anaEl);
check("a comment's own Reply, not the reply's under it",
      ownReply && ownReply.parentElement === anaEl, true);

check("links added beside other people's comments", api.injectQuickRespond(), 2);
function suggestLinks() {
  return root.querySelectorAll('[data-tallgrass-suggest]').map(function (el) {
    var owner = el.closest('div[role="article"]');
    return owner.getAttribute("aria-label").split(" ").slice(2, 4).join(" ");
  });
}
check("  on Ana and Mark, never on your own comment", suggestLinks(), ["Ana Ruiz", "Mark Twain"]);
check("  and never twice", api.injectQuickRespond(), 0);
check("the link does not change how the thread reads",
      api.readCommentThread().threads.map(function (c) { return c.verdict; }),
      ["yours", "unanswered", "unanswered"]);

console.log();
console.log("an unchanged post is not re-read every tick");
var readsBefore = api.perf().threadReads;
api.injectQuickRespond();
api.injectQuickRespond();
api.injectQuickRespond();
check("three ticks with nothing changed, no full reads", api.perf().threadReads, readsBefore);
comment(post, "Comment by New Person 1m", "New Person", "Just saw this, how do I sign up?");
check("a new comment is read on the next tick", api.injectQuickRespond(), 1);
check("  with one full read", api.perf().threadReads, readsBefore + 1);

console.log();
console.log("a reply you post is noticed");
var saved = [];
chrome.runtime.sendMessage = function (m, cb) { saved.push(m); if (cb) cb({ ok: true, comments: 3, new: 0, verdicts: {} }); };
check("nothing new, nothing saved", api.watchComments(api.readCommentThread()), false);
comment(post.children[2], "Reply by Jeff Randle to Mark Twain's comment 1m", "Jeff Randle", "Yes! DM me");
check("your reply to Mark is noticed", api.watchComments(api.readCommentThread()), true);
check("  and the thread is saved at once", [saved.length, saved[0] && saved[0].type], [1, "OUTLIER_COMMENTS"]);
check("  with Mark now answered",
      saved[0].body.comments.filter(function (c) { return c.author === "Mark Twain"; })[0].verdict, "answered");
check("  once", api.watchComments(api.readCommentThread()), false);

console.log();
console.log("opening the whole thread before saving");
D = H.makeDoc();
root = D.el("div");
post = add(root, "div", { role: "dialog" });
add(post, "div", {}, "Comment as Jeff Randle");
var sara = comment(post, "Comment by Sara Lee 5h", "Sara Lee", "Great post");
var fold = add(post, "span", { role: "button" }, "View 1 reply");
fold.onClick = function () {
  fold.textContent = "Hide 1 reply";
  comment(sara, "Reply by Jeff Randle to Sara Lee's comment 4h", "Jeff Randle", "Thank you!");
};
var more = add(post, "div", { role: "button" }, "View more comments");
more.onClick = function () {
  more.textContent = "";
  comment(post, "Comment by Late Comer 1h", "Late Comer", "How much is it?");
  var laterFold = add(post, "span", { role: "button" }, "View 2 replies");
  laterFold.onClick = function () { laterFold.textContent = "Hide 2 replies"; };
};
var reply2 = add(post, "div", { role: "button" }, "Reply");
var hide = add(post, "div", { role: "button" }, "Hide");

api = runScan({ doc: D, root: root }, "/jeffrandle/posts/pfbid02abc");
api.resetViewerNames();
api.setExpandWait(1);
check("before: one comment, its reply folded",
      api.readCommentThread().threads.map(function (c) { return c.verdict; }), ["unknown"]);
saved = [];
chrome.runtime.sendMessage = function (m, cb) { saved.push(m); if (cb) cb({ ok: true }); };
api.injectQuickRespond();           // the watcher's first look at the post
api.expandThread(function () {}, function (opened, how) {
  check("every fold was opened, including one that appeared after a click", opened, 3);
  check("  and it says it finished", how, "everything is open");
  check("  never Reply or Hide", [reply2.clicked, hide.clicked], [0, 0]);
  var after = api.readCommentThread();
  check("after: the late comment is there, and Sara's reply is visible",
        after.threads.map(function (c) { return c.author + ":" + c.verdict; }),
        ["Sara Lee:answered", "Late Comer:unanswered"]);
  // Save sends the opened thread; the next tick must not call Sara's reply —
  // opened by Save, not written just now — a reply you just posted.
  saved = [];
  api.saveComments(function () {});
  api.injectQuickRespond();
  api.injectQuickRespond();
  check("a reply opened by Save is not announced as one you just posted",
        saved.filter(function (m) { return m.type === "OUTLIER_COMMENTS"; }).length, 1);

  console.log();
  if (FAILURES.length) {
    console.log(FAILURES.length + " FAILURES");
    process.exit(1);
  }
  console.log("threads read the way you would read them");
  process.exit(0);
});
