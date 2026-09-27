/* The dragonfly that visits the meadow.
 *
 * It is a state machine — arrives, darts, perches, startles, leaves, returns —
 * and none of that is testable by looking at a canvas. field.js exposes a
 * read-only window (__field) for exactly this.
 *
 * The test owns the CLOCK and the FRAMES, and nothing else. An earlier version
 * of this file called into the animation with its own timestamps while the loop
 * still read the real clock, and the two disagreed: the dragonfly settled on
 * the blade and left again on the very next frame, because its leave-time was
 * written from one clock and compared against the other. A browser has one
 * clock, so that test was proving a fault that cannot happen — worse than no
 * test. Here tick(ms) advances the only clock there is.
 *
 * What matters, in order:
 *
 *   quiet        nothing animates at all under prefers-reduced-motion. That is
 *                the whole file's contract and a decoration must not break it.
 *   rare         it does not appear on load, and after leaving, the next visit
 *                is minutes off rather than seconds.
 *   the best     it perches on the TALLEST blade, which is the reader's own
 *   blade        biggest outlier. If this ever lands somewhere arbitrary the
 *                detail is gone and nobody would notice for months.
 *   rides        perched, it tracks the blade's moving tip rather than floating
 *                beside it.
 *   startles     the cursor coming near sends it away from the cursor.
 *   released     once off-screen nothing is left holding on, and it is
 *                rescheduled.
 *
 * Run: node tests/dragonfly.test.js
 */
var fs = require("fs");
var path = require("path");
var vm = require("vm");

var SRC = path.join(__dirname, "..", "static", "js", "field.js");

var FAILURES = [];

function check(name, got, want) {
  if (arguments.length === 2) { want = true; }
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) { FAILURES.push(name); }
}

/* Every instance is seeded.
 *
 * Which perch it takes, how long it sits, how many hops a visit gets and when
 * it first turns up are all deliberately random — that is the feature. It also
 * means an unseeded test is a different test every run, and chasing those
 * failures cost more than the tests were worth. Each instance gets its own
 * fixed seed, so a wait that fits today fits tomorrow; pass `seed` to pin a
 * particular sequence on purpose. */
var SEEDS = 0;

function load(opts) {
  opts = opts || {};
  opts.seed = opts.seed || (20260927 + (SEEDS += 7919));
  var clock = 1759000000000;              // any fixed instant
  var drawn = { ellipses: 0 };
  var frames = [];
  var listeners = {};
  var bubbles = [];

  var ctx = {
    setTransform: function () {}, clearRect: function () {},
    beginPath: function () {}, moveTo: function () {},
    quadraticCurveTo: function () {}, stroke: function () {},
    fill: function () {}, save: function () {}, restore: function () {},
    translate: function () {}, rotate: function () {}, arc: function () {},
    ellipse: function () { drawn.ellipses += 1; },
    // The wing veins, the abdomen taper and its segment lines.
    lineTo: function () {}, closePath: function () {},
    createLinearGradient: function () {
      return { addColorStop: function () {} };
    },
    // The halo it wears while perched.
    createRadialGradient: function () {
      return { addColorStop: function () {} };
    }
  };
  var canvas = { style: {}, width: 0, height: 0, getContext: function () { return ctx; } };
  var air = { style: {}, width: 0, height: 0, getContext: function () { return ctx; } };

  /* A seeded Math for the tests that need to know what it will choose.
   *
   * Which perch it takes next is deliberately random, which is right for the
   * feature and miserable for a test that then wants to scroll the thing it
   * happens to be sitting on. With a seed the sequence is fixed and the test
   * is about scrolling rather than about luck. */
  var maths = Math;
  if (opts.seed) {
    maths = Object.create(Math);
    var state = opts.seed >>> 0;
    maths.random = function () {
      state = (state + 0x6D2B79F5) >>> 0;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
      t = (t ^ (t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0))) >>> 0;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  var sandbox = {
    JSON: JSON, Math: maths, isFinite: isFinite, console: console,
    setTimeout: function () {}, clearTimeout: function () {},
    cancelAnimationFrame: function () {},
    requestAnimationFrame: function (fn) { frames.push(fn); return frames.length; },
    // The only clock in the room.
    Date: { now: function () { return clock; } },
    document: {
      getElementById: function (id) {
        if (id === "field") return canvas;
        if (id === "field-air") return air;
        return null;
      },
      // The multiples of the reader's own scored posts, as base.html supplies.
      body: {
        style: {},
        getAttribute: function (name) {
          if (name === "data-tips") return opts.tips || null;
          return opts.scores || null;
        },
        appendChild: function (node) { node.parentNode = this; bubbles.push(node); },
        removeChild: function (node) {
          var at = bubbles.indexOf(node);
          if (at !== -1) bubbles.splice(at, 1);
          node.parentNode = null;
        },
        contains: function () { return false; }
      },
      createElement: function (tag) {
        return {
          tagName: tag, style: {}, children: [], attrs: {}, parentNode: null,
          textContent: "", className: "", offsetWidth: 260, offsetHeight: 90,
          setAttribute: function (k, v) { this.attrs[k] = v; },
          appendChild: function (child) { this.children.push(child); return child; },
          addEventListener: function (name, fn) { this["on:" + name] = fn; },
          querySelector: function (sel) {
            for (var i = 0; i < this.children.length; i++) {
              if (this.children[i].tagName === sel) return this.children[i];
            }
            return null;
          },
          contains: function (node) { return this.children.indexOf(node) !== -1; }
        };
      },
      hidden: false,
      addEventListener: function (name, fn) { listeners["doc:" + name] = fn; }
    },
    window: {
      // Narrow on purpose: the blade count scales with width, every frame draws
      // all of them, and this file waits out minutes of clock. 640px is ~70
      // blades instead of ~135 and halves the runtime without changing a single
      // thing being tested.
      innerWidth: opts.width || 640, innerHeight: 800, devicePixelRatio: 1,
      // Recorded per name AND per capture flag, because the click handler is
      // registered as a capturing listener.
      matchMedia: function () { return { matches: !!opts.reduceMotion }; },
      addEventListener: function (name, fn) { listeners[name] = fn; }
    }
  };
  sandbox.window.document = sandbox.document;
  vm.runInContext(fs.readFileSync(SRC, "utf8"), vm.createContext(sandbox));

  var api = {
    field: sandbox.window.__field,
    bubbles: bubbles,
    canvas: canvas,
    drawn: drawn,
    listeners: listeners,
    now: function () { return clock; },
    /* One animation frame, `ms` later. field.js queues the next frame from
     * inside the current one, so the newest queued callback is the loop. */
    tick: function (ms) {
      clock += (ms === undefined ? 16 : ms);
      var next = frames.pop();
      frames.length = 0;
      if (next) next();
    },
    /* Frames until `predicate` holds. Returns how many it took, or -1.
     *
     * `ms` is how much clock each frame carries: 16 for anything about
     * movement, and much larger when the wait is for a time to arrive. A
     * three-minute perch is 11,000 frames at 16ms and 700 at 250ms, and the
     * state machine cannot tell the difference. */
    until: function (predicate, limit, ms) {
      for (var i = 0; i < (limit || 1500); i++) {
        api.tick(ms || 16);
        if (predicate()) return i + 1;
      }
      return -1;
    }
  };
  return api;
}

console.log("reduced motion means nothing moves");
var calm = load({ reduceMotion: true });
check("the canvas is hidden", calm.canvas.style.display, "none");
check("and no animation exists at all", calm.field === undefined, true);

console.log();
console.log("a meadow built from the reader's own scores");
var TIPS = JSON.stringify([
  "Your best captured post so far did 14.6x the median of its group.",
  "A 4x post you could plausibly have written beats a 28x post you couldn't.",
  "The median, not the average, so one viral post can't skew a group."
]);
var app = load({ scores: JSON.stringify([2.1, 14.6, 3.4, 1.2, 8.8]), tips: TIPS });
check("the field exposes itself for inspection", !!app.field, true);
check("blades were built", app.field.blades() > 20, true);
check("the tallest blade is known", app.field.perch(), app.field.tallest());
check("the hook cannot drive it, only watch it", typeof app.field.step, "undefined");

console.log();
console.log("it does not turn up straight away");
check("nothing on load", app.field.fly(), null);
app.tick(16);
// Sooner than it used to be — a companion you meet once an hour is scenery —
// but never instant, so arriving still reads as a visit.
var wait = app.field.visitIn(app.now());
check("a first visit is scheduled", wait > 10000 && wait < 60000, true);
for (var w = 0; w < 160; w++) app.tick(50);        // eight seconds of frames
check("eight seconds in, still nothing", app.field.fly(), null);

console.log();
console.log("then it arrives, and works its way over to the blade");
check("it arrives",
      app.until(function () { return !!app.field.fly(); }, 1200, 40) > 0, true);
var arrived = app.field.fly();
check("  from off-screen", arrived.x < 0 || arrived.x > 640, true);
check("  and it is flying", arrived.state, "arriving");

check("it settles on the blade", app.until(function () {
  var f = app.field.fly();
  return !!f && f.state === "perched";
}) > 0, true);
check("  on one of its chosen spots", !!app.field.spot(), true);
var tip = app.field.tip();
var sat = app.field.fly();
check("  sitting at its tip",
      Math.abs(sat.x - tip.x) < 6 && Math.abs(sat.y - tip.y) < 12, true);

console.log();
console.log("and it rides the blade, which is swaying");
var before = app.field.fly();
for (var s = 0; s < 60; s++) app.tick(16);
var after = app.field.fly();
check("still perched", after && after.state, "perched");
check("but moved with the tip", before.x !== after.x, true);

console.log();
console.log("perched, it holds its ground — you cannot tap what runs away");
app.listeners.mousemove({ clientX: after.x + 6, clientY: after.y + 6 });
for (var n = 0; n < 30; n++) app.tick(16);
check("still there with the cursor on it", app.field.fly().state, "perched");
var atRest = app.field.fly();
check("and the pointer says it is tappable",
      app.field.tappableAt(atRest.x + 6, atRest.y + 6), true);
check("  while the page away from it is not",
      app.field.tappableAt(atRest.x + 300, atRest.y), false);

console.log();
console.log("the blade it sits on ignores the cursor, so it can be reached");
// The bug this pins: blades recoil from the pointer, the insect rides its
// blade's tip, so reaching for it pushed it sideways and you chased it round
// the screen.
var sitting = app.field.fly();
app.listeners.mousemove({ clientX: sitting.x, clientY: sitting.y });
app.tick(16);
var held = app.field.fly();
check("it has not been shoved aside", Math.abs(held.x - sitting.x) < 4, true);
check("  and is still tappable where it was",
      app.field.tappableAt(sitting.x, sitting.y), true);
// Twenty more frames of the cursor sitting on it.
for (var hold = 0; hold < 20; hold++) app.tick(16);
check("still within reach after a moment's hovering",
      app.field.tappableAt(app.field.fly().x, app.field.fly().y), true);
check("  and still perched", app.field.fly().state, "perched");
app.listeners.mousemove({ clientX: -9999, clientY: -9999 });

console.log();
console.log("but the grass still parts — lower down, where the cursor is in it");
var field = load({ scores: JSON.stringify([6.0, 1.0]) });
for (var grow = 0; grow < 140; grow++) field.tick(60);   // grown, nothing landed yet
check("nothing has landed yet", field.field.fly(), null);
var still = field.field.tip();
// The cursor up at the blade's own height does nothing now.
field.listeners.mousemove({ clientX: still.x, clientY: still.y - 20 });
field.tick(16);
var high = field.field.tip();
check("a cursor up at the tip leaves it alone", Math.abs(high.x - still.x) < 4, true);
// Down among the stems, it parts them.
field.listeners.mousemove({ clientX: still.x + 30, clientY: 790 });
field.tick(16);
var low = field.field.tip();
check("a cursor down in the grass still moves it",
      Math.abs(low.x - high.x) > 8, true);

console.log();
console.log("tapping it gets a tip");
check("it has tips to give", app.field.tips() > 1, true);
check("nothing is being said yet", app.field.saying(), null);
var here = app.field.fly();
app.listeners.click({ clientX: here.x, clientY: here.y, stopPropagation: function () {} });
var first = app.field.saying();
check("it says something", typeof first === "string" && first.length > 10, true);
check("  in a bubble on the page", app.bubbles.length, 1);
check("  which is the most relevant tip first", first, JSON.parse(TIPS)[0]);

var bubble = app.bubbles[0];
check("the bubble is announced to a screen reader", bubble.attrs["aria-live"], "polite");
var another = bubble.querySelector("button");
check("  and offers another", another.textContent, "Tell me another");

another["on:click"]({ stopPropagation: function () {} });
check("a second tap gives a DIFFERENT tip", app.field.saying() !== first, true);
check("  still only one bubble", app.bubbles.length, 1);

console.log();
console.log("and it can be dismissed");
app.listeners.keydown({ key: "Escape" });
check("Escape closes it", app.field.saying(), null);
check("  leaving nothing behind", app.bubbles.length, 0);

app.listeners.click({ clientX: here.x, clientY: here.y, stopPropagation: function () {} });
check("tapping again reopens it", !!app.field.saying(), true);
app.listeners.click({ clientX: 20, clientY: 20, stopPropagation: function () {},
                      target: { nodeName: "DIV" } });
check("a click elsewhere closes it", app.field.saying(), null);

console.log();
console.log("it is still startled in the AIR, where nobody is trying to tap it");
var flying = load({ scores: JSON.stringify([9.9, 2.0]), tips: TIPS });
flying.until(function () { return !!flying.field.fly(); });
var inAir = flying.field.fly();
flying.listeners.mousemove({ clientX: inAir.x, clientY: inAir.y });
flying.tick(16);
check("it veers off", flying.field.fly().state, "leaving");

console.log();
console.log("once gone it is released, and invited back later");
// Its own visit, never tapped: a tap extends the stay deliberately, and this is
// about what happens when it simply decides to go.
var visit = load({ scores: JSON.stringify([4.4, 1.0]), tips: TIPS });
visit.until(function () {
  var f = visit.field.fly();
  return !!f && f.state === "perched";
});
check("nothing is left holding on",
      visit.until(function () { return visit.field.fly() === null; }, 6000, 400) > 0, true);
check("a next visit is scheduled", visit.field.visitIn(visit.now()) > 0, true);
check("  a minute or more away, not seconds",
      visit.field.visitIn(visit.now()) > 50000, true);

console.log();
console.log("if it leaves mid-sentence, the words go with it");
// Seeded, because a departure means every hop used up — up to seven of them,
// each with its own flight — and how many there are is random. With a seed this
// is a fixed length instead of a coin toss against the budget below.
var chatty = load({ scores: JSON.stringify([7.7, 1.1]), tips: TIPS, seed: 31415 });
chatty.until(function () {
  var f = chatty.field.fly();
  return !!f && f.state === "perched";
});
var seat = chatty.field.fly();
chatty.listeners.click({ clientX: seat.x, clientY: seat.y, stopPropagation: function () {} });
check("it is saying something", !!chatty.field.saying(), true);
// A departure means every hop used up - up to seven, each with its own flight -
// so this is a lot of CLOCK and few frames. 400ms a frame, with headroom.
chatty.until(function () { return chatty.field.fly() === null; }, 6000, 400);
check("and when it goes, the bubble goes", chatty.field.saying(), null);
check("  with nothing left on the page", chatty.bubbles.length, 0);

console.log();
console.log("it never lands where you cannot see it");
// Reported: the first blade it took was at the very edge of the window and the
// insect was half off-screen. Blades grow at every x including nearly zero, and
// the tallest is as likely to be at an edge as anywhere.
var EDGE = 56;
var edgy = load({ scores: JSON.stringify([12.0, 3.0, 1.5]) });
var landings = [];
for (var hop = 0; hop < 3; hop++) {
  edgy.until(function () {
    var f = edgy.field.fly();
    return !!f && f.state === "perched";
  }, 1500, 40);
  var perchedAt = edgy.field.fly();
  if (perchedAt) landings.push(perchedAt.x);
  // Move it on, so this samples several perches rather than one.
  edgy.until(function () {
    var f = edgy.field.fly();
    return !f || f.state !== "perched";
  }, 600, 250);
}
check("it landed several times", landings.length >= 3, true);
check("  and every landing was clear of both edges",
      landings.filter(function (x) { return x <= EDGE || x >= 640 - EDGE; }), []);

// And the rule is checked against the LIST, not only against where it happened
// to land: not one blade on offer may be near an edge.
var offered = edgy.field.spotXs().filter(function (x) { return x !== null; });
check("several perches are on offer", offered.length > 1, true);
check("  and none of them is near an edge",
      offered.filter(function (x) { return x <= EDGE || x >= 640 - EDGE; }), []);

console.log();
console.log("it hangs about on a blade, then moves to another one");
// It briefly landed on the page itself — score badges, the median notch — and
// rode them as the page scrolled. Removed: a thing that moves while you read
// takes your eye off the words every time. Blades are fixed to the window, so
// it hops between them and stays still while the page moves.
var hopper = load({ scores: JSON.stringify([9.0, 4.0, 2.0, 1.2]) });
check("every perch on offer is a blade",
      hopper.field.spots() > 1 && !!hopper.field.spot(), true);
hopper.until(function () {
  var f = hopper.field.fly();
  return !!f && f.state === "perched";
}, 1500, 40);
var sat = hopper.field.spot();
check("it settles on one", sat && sat.kind, "blade");

var went = hopper.until(function () {
  var now = hopper.field.spot();
  return !!now && now.index !== sat.index;
}, 900, 250);
check("it moves to a different blade", went > 0, true);
check("  without leaving", !!hopper.field.fly(), true);
check("  after sitting a while, not seconds", went * 250 > 20000, true);
hopper.until(function () {
  var f = hopper.field.fly();
  return !!f && f.state === "perched";
}, 1200, 40);
check("  and it is a second landing, not a second visit",
      hopper.field.hops() >= 2, true);

console.log();
console.log("it perches with no scores too — there is always a tallest blade");
var blank = load({});
check("a perch is chosen", blank.field.perch() >= 0, true);
check("and it lands", blank.until(function () {
  var f = blank.field.fly();
  return !!f && f.state === "perched";
}) > 0, true);

console.log();
console.log("and it is actually drawn");
var drawing = load({ scores: JSON.stringify([9.9, 2.0]) });
drawing.until(function () { return !!drawing.field.fly(); });
var beforeDraw = drawing.drawn.ellipses;
drawing.tick(16);
check("wings and body reach the canvas", drawing.drawn.ellipses > beforeDraw, true);

console.log();
if (FAILURES.length) {
  console.log(FAILURES.length + " FAILURES: " + FAILURES.join(", "));
  process.exit(1);
}
console.log("it visits, lands on the best blade, and knows when it is not wanted");
process.exit(0);
