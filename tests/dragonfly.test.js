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

function load(opts) {
  opts = opts || {};
  var clock = 1759000000000;              // any fixed instant
  var drawn = { ellipses: 0 };
  var frames = [];
  var listeners = {};

  var ctx = {
    setTransform: function () {}, clearRect: function () {},
    beginPath: function () {}, moveTo: function () {},
    quadraticCurveTo: function () {}, stroke: function () {},
    fill: function () {}, save: function () {}, restore: function () {},
    translate: function () {}, rotate: function () {}, arc: function () {},
    ellipse: function () { drawn.ellipses += 1; }
  };
  var canvas = { style: {}, width: 0, height: 0, getContext: function () { return ctx; } };

  var sandbox = {
    JSON: JSON, Math: Math, isFinite: isFinite, console: console,
    setTimeout: function () {}, clearTimeout: function () {},
    cancelAnimationFrame: function () {},
    requestAnimationFrame: function (fn) { frames.push(fn); return frames.length; },
    // The only clock in the room.
    Date: { now: function () { return clock; } },
    document: {
      getElementById: function (id) { return id === "field" ? canvas : null; },
      // The multiples of the reader's own scored posts, as base.html supplies.
      body: { getAttribute: function () { return opts.scores || null; } },
      hidden: false,
      addEventListener: function (name, fn) { listeners["doc:" + name] = fn; }
    },
    window: {
      innerWidth: 1200, innerHeight: 800, devicePixelRatio: 1,
      matchMedia: function () { return { matches: !!opts.reduceMotion }; },
      addEventListener: function (name, fn) { listeners[name] = fn; }
    }
  };
  sandbox.window.document = sandbox.document;
  vm.runInContext(fs.readFileSync(SRC, "utf8"), vm.createContext(sandbox));

  var api = {
    field: sandbox.window.__field,
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
    /* Frames until `predicate` holds. Returns how many it took, or -1. */
    until: function (predicate, limit) {
      for (var i = 0; i < (limit || 8000); i++) {
        api.tick(16);
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
var app = load({ scores: JSON.stringify([2.1, 14.6, 3.4, 1.2, 8.8]) });
check("the field exposes itself for inspection", !!app.field, true);
check("blades were built", app.field.blades() > 20, true);
check("the perch is the tallest blade", app.field.perch(), app.field.tallest());
check("the hook cannot drive it, only watch it", typeof app.field.step, "undefined");

console.log();
console.log("it does not turn up straight away");
check("nothing on load", app.field.fly(), null);
app.tick(16);
check("a first visit is scheduled at least half a minute out",
      app.field.visitIn(app.now()) > 30000, true);
for (var w = 0; w < 1200; w++) app.tick(16);       // twenty seconds of frames
check("twenty seconds in, still nothing", app.field.fly(), null);

console.log();
console.log("then it arrives, and works its way over to the blade");
check("it arrives", app.until(function () { return !!app.field.fly(); }) > 0, true);
var arrived = app.field.fly();
check("  from off-screen", arrived.x < 0 || arrived.x > 1200, true);
check("  and it is flying", arrived.state, "arriving");

check("it settles on the blade", app.until(function () {
  var f = app.field.fly();
  return !!f && f.state === "perched";
}) > 0, true);
check("  which is still the tallest one", app.field.perch(), app.field.tallest());
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
console.log("the cursor startles it");
app.listeners.mousemove({ clientX: after.x + 10, clientY: after.y + 10 });
app.tick(16);
var spooked = app.field.fly();
check("it leaves", spooked && spooked.state, "leaving");
check("  away from the cursor", spooked.x < after.x + 10, true);
app.listeners.mousemove({ clientX: -9999, clientY: -9999 });

console.log();
console.log("once gone it is released, and invited back later");
check("nothing is left holding on",
      app.until(function () { return app.field.fly() === null; }) > 0, true);
check("a next visit is scheduled", app.field.visitIn(app.now()) > 0, true);
check("  minutes away, not seconds", app.field.visitIn(app.now()) > 120000, true);

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
