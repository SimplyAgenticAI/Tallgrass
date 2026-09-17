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
console.log("noticing a reply as it is sent");
var sent = [];
var signals = [];
// Only chat saves are counted in `sent`; the panel's queue refresh also
// messages the worker, and the first look sends the chat's label.
chrome.runtime.sendMessage = function (m, cb) {
  if (m.type === "OUTLIER_SIGNAL") signals.push(m.body);
  else if (m.type !== "OUTLIER_TODAY") sent.push(m);
  if (cb) cb({ ok: true });
};
check("the first look only records where the chat stands", api.watchConversation(), null);
check("  and saves nothing", sent.length, 0);
check("  but labels the chat from everything they said since your last message",
      signals, [{ key: "t:1001", signal: "opportunity" }]);
check("an opportunity hidden behind a harmless last line is found",
      api.chatSignal({ messages: [{ from: "me", text: "Hey, thanks for following!" },
                                  { from: "them", text: "Quick one, how much for a logo" },
                                  { from: "them", text: "Hi!" }] }), "opportunity");
check("  but not from before your last message",
      api.chatSignal({ messages: [{ from: "them", text: "How much?" },
                                  { from: "me", text: "It's $300" },
                                  { from: "them", text: "Thanks!" }] }), null);
check("  and the panel says it is watching",
      /^watching/.test(api.liveSeen("1001").decision) && api.liveSeen("1001").from, "them");
check("nothing new, nothing sent", api.watchConversation(), null);

messageRow("You sent", "It's [price] for the full package — want details?", null);
var moved = api.watchConversation();
check("your reply is noticed", moved && moved.last_from, "me");
check("  sent to the dashboard as that one chat", [sent.length, sent[0].type, sent[0].body.threads.length],
      [1, "OUTLIER_THREADS", 1]);
check("  keyed like the chat list", sent[0].body.threads[0].key, "t:1001");
check("  stamped now", Math.abs(Date.parse(moved.last_at + "Z") - Date.now()) < 5000, true);
check("  with no words in it", JSON.stringify(sent[0].body).indexOf("full package"), -1);
check("  and only once", api.watchConversation(), null);

messageRow("Jane Doe", "Yes please! Can we book a call?", null);
var back = api.watchConversation();
check("their answer is noticed too", back && back.last_from, "them");
check("  and read as an opportunity", back && back.signal, "opportunity");

// A different conversation's messages replacing these (a chat switch, or a
// chat still loading) changes the last line without anything being sent.
grid.children = [];
messageRow("Tom Hanks", "Haha love it", null);
check("a replaced conversation is a fresh look, not a reply", api.watchConversation(), null);
check("  nothing sent for it", sent.length, 2);
check("  and the panel says why", /reloading, not a new message/.test(api.liveSeen("1001").decision), true);

// A save the dashboard refuses must be said, not swallowed.
chrome.runtime.sendMessage = function (m, cb) { if (cb) cb({ ok: false, error: "Invalid or missing API key" }); };
messageRow("You sent", "Sure thing!", null);
api.watchConversation();
check("a failed save is shown in the panel",
      api.liveSeen("1001").decision, "noticed the new message, but saving failed: Invalid or missing API key");

/* A list like Facebook's: 120 chats, ten rows rendered at a time, the rest
 * unmounted until scrolled to. Reading it once finds ten. */
/* opts.noBox: no element that measures as scrollable — the case where the
 *   first version read one screen and quit. Rows scroll the list themselves.
 * opts.lazy: Facebook loads older chats in batches of 20, a while after the
 *   list reaches the bottom of what it has. */
function virtualInbox(total, opts) {
  opts = opts || {};
  var VD = H.makeDoc();
  var vroot = VD.el("div");
  var scroller = VD.el("div");
  vroot.appendChild(scroller);
  var top = 0;
  var loaded = opts.lazy ? 20 : total;
  if (!opts.noBox) {
    scroller.clientHeight = 500;
    Object.defineProperty(scroller, "scrollHeight", { get: function () { return loaded * 50; } });
  }
  function moveTo(v) {
    top = Math.max(0, Math.min(v, loaded * 50 - 500));
    if (opts.lazy && top >= loaded * 50 - 500 && loaded < total) {
      setTimeout(function () { loaded = Math.min(total, loaded + 20); render(); }, 15);
    }
    render();
  }
  function render() {
    scroller.children = [];
    var first = Math.floor(top / 50);
    for (var i = first; i < Math.min(loaded, first + 10); i++) {
      var a = VD.el("a");
      a.setAttribute("href", "/messages/t/" + (5000 + i) + "/");
      if (opts.noBox) {
        (function (index) { a.scrollIntoView = function () { moveTo(index * 50); }; })(i);
      }
      scroller.appendChild(a);
      var n = VD.el("span"); n.textContent = "Person " + i; a.appendChild(n);
      var l = VD.el("span"); l.textContent = (i % 3 ? "You: ok" : "Is this still available?"); a.appendChild(l);
      var w = VD.el("span"); w.textContent = "2d"; a.appendChild(w);
    }
  }
  Object.defineProperty(scroller, "scrollTop", {
    get: function () { return top; },
    set: function (v) { moveTo(v); }
  });
  render();
  return { doc: VD, root: vroot, scroller: scroller };
}

function scanTest(total, target, opts, then) {
  var inbox = virtualInbox(total, opts);
  var vapi = runScan({ doc: inbox.doc, root: inbox.root }, "/messages/");
  vapi.setChatScrollWait(1, opts.lazy ? 200 : 3);
  check("one screen shows only ten", vapi.readChatList().length, 10);
  var seen = [];
  vapi.scanChats(target, function (n) { seen.push(n); }, function (threads, stopped, reason, scrolls) {
    then(threads, stopped, seen, inbox, reason, scrolls);
  });
}

console.log();
console.log("reading more than one screen");
scanTest(120, 50, {}, function (threads, stopped, progress, inbox, reason) {
  check("scrolls until it has as many as asked", threads.length, 50);
  check("  each chat once", Object.keys(threads.reduce(function (a, t) { a[t.key] = 1; return a; }, {})).length, 50);
  check("  in list order, from the top", [threads[0].name, threads[49].name], ["Person 0", "Person 49"]);
  check("  reporting progress as it goes", progress[progress.length - 1], 50);
  check("  and returns the list to the top", inbox.scroller.scrollTop, 0);
  check("  not stopped", stopped, false);
  check("  and says why it finished", reason, "reached 50");

  scanTest(120, 250, {}, function (threads2, s2, p2, i2, reason2) {
    check("an inbox smaller than asked is read to its end", threads2.length, 120);
    check("  and says it hit the end", /stopped growing|wouldn't scroll/.test(reason2), true);

    console.log();
    console.log("the reported failure: no box that measures as scrollable");
    scanTest(120, 100, { noBox: true }, function (threads3, s3, p3, i3, reason3, scrolls3) {
      check("it still scrolls, by bringing the last row into view", threads3.length, 100);
      check("  in order, nothing skipped",
            threads3.map(function (t) { return t.name; }).slice(0, 3).concat([threads3[99].name]),
            ["Person 0", "Person 1", "Person 2", "Person 99"]);
      check("  and it took real scrolls, not one read", scrolls3 >= 10, true);

      console.log();
      console.log("Facebook slow to load older chats");
      scanTest(100, 250, { lazy: true }, function (threads4, s4, p4, i4, reason4) {
        check("it waits for each batch instead of quitting at the first pause", threads4.length, 100);
        check("  and ends only when no more come", /stopped growing|wouldn't scroll/.test(reason4), true);
        finishTests();
      });
    });
  });
});

function finishTests() {
  console.log();
  if (FAILURES.length) {
    console.log(FAILURES.length + " FAILURES");
    process.exit(1);
  }
  console.log("chats read the way Messenger shows them");
  process.exit(0);
}
