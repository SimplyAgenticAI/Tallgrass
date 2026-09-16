/* Messenger: who is waiting on you, and what was said.
 *
 * Two readings everything else depends on. The chat list decides who spoke
 * last — a wrong answer puts a chat you already answered in front of you, or
 * hides one somebody is waiting on. The open conversation decides who said
 * what — a wrong answer drafts a reply to your own message. And the chat list
 * must never let the words themselves out of the browser.
 *
 * These are fixtures, not the real page. The real check is the Messages page
 * against what Messenger shows, and __outlier.saveMessengerReport() when it
 * disagrees.
 *
 * Run: node tests/messenger.test.js
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

var D = H.makeDoc();
var root = D.el("div");

function add(parent, tag, attrs, text) {
  var e = D.el(tag);
  parent.appendChild(e);
  Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
  if (text) e.textContent = text;
  return e;
}

function chatRow(list, id, name, last, when, extra) {
  var a = add(list, "a", Object.assign({ href: "/messages/t/" + id + "/", role: "link" }, extra || {}));
  add(a, "span", {}, name);
  var line = add(a, "div", {});
  add(line, "span", {}, last);
  add(line, "span", {}, "·");
  add(line, "span", {}, when);
  return a;
}

var nav = add(root, "div", { role: "navigation", "aria-label": "Chats" });
chatRow(nav, "1001", "Jane Doe", "How much for the full website package?", "2h");
chatRow(nav, "1002", "Mark Twain", "You: Sounds good, talk soon", "5d");
chatRow(nav, "1003", "Sara Lee", "Are you free Thursday?", "Mon");
chatRow(nav, "1004", "Tom Hanks", "Haha love it", "3w");
chatRow(nav, "1005", "Ana Ruiz", "You sent a photo.", "1w");
chatRow(nav, "1006", "Lee Chan", "Still available?", "12:30 PM", { "aria-label": "Lee Chan, unread" });

// The open conversation with Jane.
var main = add(root, "div", { role: "main" });
var grid = add(main, "div", { role: "grid", "aria-label": "Messages in conversation with Jane Doe" });
function messageRow(heading, words, side) {
  var row = add(grid, "div", { role: "row" });
  if (heading) add(row, "h5", {}, heading);
  var bubble = add(row, "div", { dir: "auto" });
  var text = add(bubble, "span", {}, words);
  if (side) {
    text.getBoundingClientRect = function () {
      return side === "right" ? { left: 400, width: 150 } : { left: 40, width: 150 };
    };
  }
  return row;
}
add(grid, "div", { role: "row" }, "Today at 9:02 AM");
messageRow("Jane Doe", "Hi! Saw your post about websites", null);
messageRow("You sent", "Hey Jane, thanks for reaching out!", null);
messageRow(null, "What kind of site are you after?", "right");
messageRow(null, "How much for the full website package?", "left");
add(main, "div", { contenteditable: "true", role: "textbox", "aria-label": "Message" });

var api = runScan({ doc: D, root: root }, "/messages/t/1001/");

console.log("the chat list");
var list = api.readChatList();
function byName(n) { return list.filter(function (t) { return t.name === n; })[0]; }
check("every chat read", list.length, 6);
check("they spoke last", byName("Jane Doe").last_from, "them");
check("\"You:\" means you spoke last", byName("Mark Twain").last_from, "me");
check("\"You sent a photo\" too", byName("Ana Ruiz").last_from, "me");
check("a price question is an opportunity", byName("Jane Doe").signal, "opportunity");
check("\"Still available?\" is an opportunity", byName("Lee Chan").signal, "opportunity");
check("a plain question is a question", byName("Sara Lee").signal, "question");
check("a friendly line is neither", byName("Tom Hanks").signal, null);
check("your own last line carries no signal", byName("Mark Twain").signal, null);
check("unread is read from the label", [byName("Lee Chan").unread, byName("Jane Doe").unread], [true, false]);
check("the link is the chat", byName("Jane Doe").url, "https://www.facebook.com/messages/t/1001/");
check("the time is read", byName("Mark Twain").when_text, "5d");
check("  and turned into an approximate date", typeof byName("Mark Twain").last_at, "string");
var days = (Date.now() - Date.parse(byName("Mark Twain").last_at + "Z")) / 864e5;
check("  about five days back", days > 4.9 && days < 5.1, true);
check("a clock time is today", api.chatTime("12:30 PM").slice(0, 10),
      new Date(new Date().setHours(12, 30, 0, 0)).toISOString().slice(0, 10));
check("a weekday is within the last week",
      (Date.now() - Date.parse(api.chatTime("Mon") + "Z")) / 864e5 <= 7, true);
check("nothing in the summary is the message itself",
      JSON.stringify(list.map(function (t) {
        return { key: t.key, name: t.name, url: t.url, last_from: t.last_from, last_at: t.last_at,
                 unread: t.unread, signal: t.signal, last_hash: t.last_hash };
      })).indexOf("website package"), -1);

console.log();
console.log("the open conversation");
var convo = api.readConversation();
check("named from the chat list", convo.name, "Jane Doe");
check("date lines are not messages", convo.messages.length, 4);
check("who said what",
      convo.messages.map(function (m) { return m.from; }), ["them", "me", "me", "them"]);
check("what was said", convo.messages[0].text, "Hi! Saw your post about websites");
check("nobody left unplaced", convo.unknown, 0);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES");
  process.exit(1);
}
console.log("chats read the way Messenger shows them");
process.exit(0);
