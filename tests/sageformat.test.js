/* Sage's answers, laid out rather than printed.
 *
 * Reported with a real reply pasted in: "### Suggested Graphic Concept",
 * "**Graphic Type**: Meme-style Image", "- **Top Text**: ..." — every marker
 * the model wrote arriving on screen as the literal character, because the
 * reply was rendered with textContent.
 *
 * Two halves fix it. The prompt now asks for plain prose (sage.py), and this is
 * the other half: whatever markdown still leaks becomes typography.
 *
 * The safety property is the point of the design and the first thing tested.
 * The model's input includes post bodies captured from strangers on Facebook,
 * so its output is attacker-influenced and must never be treated as markup.
 * layOut builds DOM nodes and every string goes in through textContent — so a
 * tag in the answer stays text, visibly, rather than becoming an element.
 *
 * Run: node tests/sageformat.test.js
 */
var fs = require("fs");
var path = require("path");
var vm = require("vm");

var SRC = path.join(__dirname, "..", "static", "js", "outlier.js");

var FAILURES = [];

function check(name, got, want) {
  if (arguments.length === 2) { want = true; }
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

/* A DOM stub with just enough of it to build a tree and read it back.
 *
 * textContent on a node with children returns the concatenated text, which is
 * what lets a test assert "no asterisk survived anywhere" in one line. */
function makeNode(name) {
  var node = {
    nodeName: name.toUpperCase(),
    tagName: name,
    childNodes: [],
    className: "",
    classList: {
      add: function (c) {
        if (!node.className.split(" ").includes(c)) {
          node.className = (node.className + " " + c).trim();
        }
      },
      contains: function (c) { return node.className.split(" ").indexOf(c) !== -1; }
    },
    appendChild: function (child) {
      child.parentNode = node;
      node.childNodes.push(child);
      return child;
    },
    replaceChild: function (fresh, old) {
      var at = node.childNodes.indexOf(old);
      if (at !== -1) { node.childNodes[at] = fresh; fresh.parentNode = node; }
    },
    querySelectorAll: function (selector) {
      var out = [];
      (function walk(n) {
        for (var i = 0; i < n.childNodes.length; i++) {
          var kid = n.childNodes[i];
          if (kid.tagName === selector) out.push(kid);
          walk(kid);
        }
      })(node);
      return out;
    }
  };
  Object.defineProperty(node, "firstChild", {
    get: function () { return node.childNodes[0] || null; }
  });
  Object.defineProperty(node, "textContent", {
    get: function () {
      return node.childNodes.map(function (k) { return k.textContent; }).join("");
    },
    set: function (value) {
      node.childNodes = [];
      if (value !== "") node.appendChild(makeText(String(value)));
    }
  });
  return node;
}

function makeText(text) {
  return { nodeName: "#text", tagName: "#text", childNodes: [], textContent: text };
}

/* Load outlier.js far enough to get at layOut. The file is one IIFE, so the
 * function is reached by exposing it the way the app does for its own tests:
 * through a global the script sets. Rather than edit the app for the test, the
 * source is read and the formatter block evaluated on its own — it depends on
 * nothing but `document`. */
function loadFormatter() {
  var src = fs.readFileSync(SRC, "utf8");
  var start = src.indexOf("  function inlineInto(parent, text) {");
  var end = src.indexOf("  /* Answers already on the page when it loads");
  if (start === -1 || end === -1) {
    throw new Error("could not find the formatter in outlier.js");
  }
  var sandbox = {
    document: {
      createElement: makeNode,
      createTextNode: makeText,
      querySelectorAll: function () { return []; }
    },
    console: console
  };
  vm.runInContext(src.slice(start, end) + "\n;this.layOut = layOut;",
                  vm.createContext(sandbox));
  return sandbox.layOut;
}

var layOut = loadFormatter();

function laid(text) {
  var el = makeNode("div");
  return layOut(text, el);
}

console.log("model output never becomes markup");
var nasty = laid('A post said "<img src=x onerror=alert(1)>" and <script>bad()</script>');
check("the tag is still text", /<img src=x onerror/.test(nasty.textContent), true);
check("  and no element was created from it",
      nasty.querySelectorAll("img").length + nasty.querySelectorAll("script").length, 0);
check("  it is a paragraph of words", nasty.querySelectorAll("p").length, 1);

console.log();
console.log("the reported reply, laid out");
var REPLY = [
  "For the \"Vibe Coding is Life\" group, we'll craft an original graphic concept.",
  "",
  "### Suggested Graphic Concept",
  "",
  "**Graphic Type**: Meme-style Image",
  "",
  "**Visual Elements**:",
  "- **Background**: A minimalist workspace with dual monitors.",
  "- **Center Visual**: A cartoon character typing at a keyboard.",
  "- **Text Overlay**:",
  "  - **Top Text**: \"Decoding Life, One Line at a Time.\"",
  "",
  "### Why it Should Work",
  "",
  "- **Visual Appeal**: The digital aesthetic fits a tech-savvy audience.",
  "1. High share potential, because the hook is relatable.",
  "",
  "This should capture the community spirit of the group."
].join("\n");

var out = laid(REPLY);
check("not one hash survives", out.textContent.indexOf("#"), -1);
check("not one asterisk survives", out.textContent.indexOf("*"), -1);
check("the words are all still there",
      /Decoding Life, One Line at a Time/.test(out.textContent), true);
check("  including the opening sentence",
      /craft an original graphic concept/.test(out.textContent), true);

function headings(node) {
  return node.childNodes.filter(function (n) { return n.className === "msg-h"; });
}
check("the two ### lines and the bold run-in all became headings",
      headings(out).map(function (h) { return h.textContent; }),
      ["Suggested Graphic Concept", "Visual Elements", "Why it Should Work"]);
check("  but a bold LABEL with words after it stays a sentence",
      /Graphic Type/.test(out.querySelectorAll("p").map(function (p) {
        return p.textContent;
      }).join(" ")), true);
check("the bullets became one list each",
      out.querySelectorAll("ul").length, 2);
check("  with every item kept",
      out.querySelectorAll("li").length, 6);
check("a numbered item is a list item too",
      /High share potential/.test(out.querySelectorAll("li").map(function (li) {
        return li.textContent;
      }).join(" ")), true);
check("the bolded run-ins are bold",
      out.querySelectorAll("b").length >= 5, true);
check("  and 'Background' is one of them",
      out.querySelectorAll("b").map(function (b) { return b.textContent; })
        .indexOf("Background") !== -1, true);

console.log();
console.log("a line that is entirely bold reads as a heading");
var runIn = laid("**Visual Elements**");
check("it is not left as a bold paragraph", runIn.querySelectorAll("p").length, 0);
check("  it is a heading", runIn.childNodes[0].className, "msg-h");
check("  with the colon trimmed", laid("**Hook:**").textContent, "Hook");

console.log();
console.log("plain prose is left alone");
var prose = laid("Your best post did 14.6x the median of its group.\nOpen it and Write can build on it.");
check("one paragraph, both lines", prose.querySelectorAll("p").length, 1);
check("  joined with a space",
      /group\. Open it/.test(prose.textContent), true);
check("no stray markup", prose.querySelectorAll("b").length + prose.querySelectorAll("ul").length, 0);

var spaced = laid("First thought.\n\nSecond thought.");
check("a blank line starts a new paragraph", spaced.querySelectorAll("p").length, 2);

console.log();
console.log("the awkward inputs");
check("empty text gives an empty body", laid("").textContent, "");
check("null does not throw", laid(null).textContent, "");
check("an unclosed marker stays as written",
      /\*\*Hoo/.test(laid("**Hoo").textContent), true);
check("backticks become code",
      laid("Use `engagement_read` for that.").querySelectorAll("code").length, 1);
check("  and the ticks are gone",
      laid("Use `engagement_read` for that.").textContent.indexOf("`"), -1);
check("the body is marked as laid out", laid("x").className.indexOf("is-laid-out") !== -1, true);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES: " + FAILURES.join(", "));
  process.exit(1);
}
console.log("typography, not punctuation — and still never markup");
process.exit(0);
