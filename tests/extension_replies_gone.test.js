/* The extension does not read comments or private messages.
 *
 * It used to: the comment thread under a post, a Suggest reply link injected
 * into Facebook's own comment UI, the Messenger chat list, a draft for an open
 * conversation, and a reply queue in the panel. The dashboard stopped showing
 * any of it in V32.6 — answering people is work Facebook already carries — so
 * what was left was reading somebody's private messages and the comments on
 * their posts and sending them where nothing could be seen.
 *
 * That is also the hardest thing in a store listing to justify: personal
 * communications read for a feature with no interface. So it went out before
 * the submission rather than after it.
 *
 * The distinction this file exists to protect is the one that is easy to get
 * wrong. The post extractor has comment logic of its OWN — it has to know
 * where a post ends and its comments begin, or it reads a comment as the post
 * body — and that logic stays. "No comment reading" means no reading of
 * comments as content to send; it does not mean the extractor forgets they
 * exist.
 *
 * Run: node tests/extension_replies_gone.test.js
 */
var fs = require("fs");
var path = require("path");

var EXT = path.join(__dirname, "..", "extension");
var content = fs.readFileSync(path.join(EXT, "content.js"), "utf8");
var background = fs.readFileSync(path.join(EXT, "background.js"), "utf8");
var manifest = JSON.parse(fs.readFileSync(path.join(EXT, "manifest.json"), "utf8"));

var FAILURES = [];

function check(name, got, want) {
  if (arguments.length === 2) { want = true; }
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

/* Code, not comments. Every assertion below is about what the file DOES, and
 * the explanations left behind name the things that were removed — so a naive
 * substring search would find them all and pass. */
function code(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

var contentCode = code(content);
var backgroundCode = code(background);

console.log("nothing reads a comment thread or a chat");
[
  "readCommentThread", "sendComments", "expandThread", "commentPayload",
  "injectQuickRespond", "suggestReply", "putInReplyBox", "watchComments",
  "readChatList", "scanChats", "sendChatList", "readConversation",
  "watchConversation", "suggestMessage", "chatSignal", "sortChats",
  "refreshReplyQueue", "renderReplyQueue", "renderMessengerHud"
].forEach(function (fn) {
  check("  " + fn + " is gone", new RegExp("function\\s+" + fn + "\\b").test(contentCode), false);
  check("    and nothing calls it", new RegExp("\\b" + fn + "\\s*\\(").test(contentCode), false);
});

console.log();
console.log("nothing posts a comment or a message anywhere");
[
  "/api/comments", "/api/comments/draft", "/api/messages/threads",
  "/api/messages/draft", "/api/messages/sort", "/api/messages/signal",
  "/api/today"
].forEach(function (route) {
  check("  " + route + " is never called",
        contentCode.indexOf(route) !== -1 || backgroundCode.indexOf(route) !== -1, false);
});
[
  "OUTLIER_COMMENTS", "OUTLIER_DRAFT", "OUTLIER_THREADS", "OUTLIER_MESSAGE_DRAFT",
  "OUTLIER_MESSAGE_SORT", "OUTLIER_SIGNAL", "OUTLIER_TODAY", "OUTLIER_TODAY_DONE"
].forEach(function (msg) {
  check("  " + msg + " is neither sent nor handled",
        contentCode.indexOf(msg) !== -1 || backgroundCode.indexOf(msg) !== -1, false);
});

console.log();
console.log("and it does not run on Messenger at all");
/* Belt as well as braces. Even with the readers gone, a content script that
 * loads on /messages is a content script a reviewer has to take on trust. */
var script = manifest.content_scripts.filter(function (cs) {
  return cs.js.indexOf("content.js") !== -1;
})[0];
check("the content script is excluded from /messages",
      (script.exclude_matches || []).slice().sort(),
      ["https://web.facebook.com/messages/*", "https://www.facebook.com/messages/*"]);
check("  while still running on the rest of Facebook",
      script.matches.slice().sort(),
      ["https://web.facebook.com/*", "https://www.facebook.com/*"]);

console.log();
console.log("the store listing asks for no more than it needs");
check("no wildcard over plain http",
      (manifest.optional_host_permissions || []).indexOf("http://*/*"), -1);
check("  the https wildcard stays, for a self-hosted dashboard",
      (manifest.optional_host_permissions || []).indexOf("https://*/*") !== -1, true);
check("permissions are still the three it uses",
      manifest.permissions.slice().sort(), ["activeTab", "alarms", "storage"]);
check("the description does not promise replies",
      /repl(y|ies)|messenger|comment/i.test(manifest.description), false);
check("  and fits what the store accepts", manifest.description.length <= 132, true);

console.log();
console.log("but the post extractor still knows what a comment is");
/* The part that is easy to break by being thorough. A post's own comments have
 * to be recognised, or the body of the post becomes whatever the first
 * commenter wrote. */
[
  "isCommentArticle", "findCommentBoundary", "nonCommentArticles",
  "countOutsideComments", "isChatBubble"
].forEach(function (fn) {
  check("  " + fn + " is still here",
        new RegExp("function\\s+" + fn + "\\b").test(contentCode), true);
});
check("  and the body extractor still uses the boundary",
      /findCommentBoundary\s*\(/.test(contentCode), true);

console.log();
console.log("capture itself is untouched");
["scanPosts", "startAutoScroll", "stepScan", "flush", "detectSource",
 "extractEngagement", "extractBody"].forEach(function (fn) {
  check("  " + fn, new RegExp("function\\s+" + fn + "\\b").test(contentCode), true);
});
/* The page hands a batch to the service worker and the worker posts it — the
 * content script never fetches the dashboard itself, which is why the route
 * lives in background.js. */
check("  the page still hands batches to the worker",
      contentCode.indexOf("OUTLIER_CAPTURE") !== -1, true);
check("  and the worker still posts them",
      backgroundCode.indexOf("/api/capture") !== -1, true);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES: " + FAILURES.join(", "));
  process.exit(1);
}
console.log("the extension reads posts, and nothing anybody wrote to anybody");
process.exit(0);
