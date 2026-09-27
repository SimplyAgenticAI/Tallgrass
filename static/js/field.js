/* Animated background: a meadow that grows.
 *
 * Blades sprout from the bottom edge and sway on a slow wind, with a few
 * growing well above the rest and catching the light — the product's thesis
 * as organic growth rather than a starfield.
 *
 * Kept cheap: blade count scales to viewport width, everything is a single
 * quadratic curve, and the loop stops when the tab is hidden or the user
 * prefers reduced motion.
 */

(function () {
  "use strict";

  var canvas = document.getElementById("field");
  if (!canvas) return;

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    canvas.style.display = "none";
    return;
  }

  var ctx = canvas.getContext("2d", { alpha: true });

  /* The insect gets a canvas of its own, in FRONT of the page.
   *
   * The meadow is behind everything (z-index 0, and the cards have solid
   * backgrounds), which is right for a background and useless for something
   * that lands on a card's score badge — it would sit behind the card and
   * disappear. So the grass stays on the back canvas and the dragonfly is
   * drawn on a front one: same coordinates, same size, no pointer events, and
   * under both the tip bubble and the walkthrough spotlight. */
  var air = document.getElementById("field-air");
  var airCtx = air ? air.getContext("2d", { alpha: true }) : ctx;
  var width = 0, height = 0, dpr = 1;
  var blades = [];
  var motes = [];
  var mouse = { x: -9999, y: -9999 };
  var running = true;
  var frame = 0;
  var time = 0;

  var MOUSE_RADIUS = 170;

  function bladeCount() {
    // Roughly one blade per 9px of width, bounded so phones stay smooth and
    // ultrawides don't draw hundreds of curves per frame.
    return Math.max(40, Math.min(150, Math.round(width / 9)));
  }

  /* The reader's own scores, when the page has them.
   *
   * The tall blades used to be picked by `index % 11 === 4` — decoration in
   * the shape of the idea. But the numbers exist: the page can hand over the
   * multiples of everything scored, and then the meadow IS the data. The tall
   * ones are your actual breakouts, at their actual heights, in their actual
   * proportion.
   *
   * Signed out, or on a page with nothing scored, it falls back to the old
   * arbitrary rhythm — which is honest, because there is nothing to draw.
   */
  var scores = [];
  try {
    var raw = document.body.getAttribute("data-field-scores");
    if (raw) {
      scores = JSON.parse(raw).filter(function (n) {
        return typeof n === "number" && isFinite(n) && n > 0;
      });
    }
  } catch (error) {
    scores = [];
  }

  // Everything is drawn relative to the biggest, so one runaway post does not
  // flatten the rest of the field into stubble.
  var topScore = scores.reduce(function (a, b) { return Math.max(a, b); }, 0);

  function makeBlade(index, total) {
    var multiple = null;
    var isOutlier;

    if (scores.length) {
      // Spread the real scores across the width rather than clustering them,
      // so the field reads as a field and not as a bar chart.
      multiple = scores[Math.floor(index * scores.length / total) % scores.length];
      isOutlier = multiple >= 5;          // the same threshold the feed uses
    } else {
      isOutlier = index % 11 === 4;
    }

    var baseHeight;
    if (multiple !== null && topScore > 0) {
      // Square root, not linear: a 90x post is not thirty times taller than a
      // 3x one on any screen, and compressing the top keeps the ordinary
      // blades tall enough to still be a meadow.
      var share = Math.sqrt(multiple / topScore);
      baseHeight = height * (0.10 + share * 0.26);
    } else {
      baseHeight = height * (isOutlier ? 0.30 : 0.13);
    }

    return {
      x: (index / total) * width + (Math.random() - 0.5) * 14,
      height: baseHeight * (0.8 + Math.random() * 0.4),
      // Thicker blades read as nearer; drawn later so they sit in front.
      depth: isOutlier ? 1 : 0.35 + Math.random() * 0.5,
      phase: Math.random() * Math.PI * 2,
      speed: 0.4 + Math.random() * 0.5,
      lean: (Math.random() - 0.5) * 0.5,
      outlier: isOutlier,
      // Staggered so the meadow grows in rather than appearing at once.
      grown: 0,
      growRate: 0.006 + Math.random() * 0.012
    };
  }

  function makeMote() {
    return {
      x: Math.random() * width,
      y: height + Math.random() * height * 0.5,
      radius: 0.8 + Math.random() * 1.6,
      drift: (Math.random() - 0.5) * 0.18,
      rise: 0.18 + Math.random() * 0.34,
      phase: Math.random() * Math.PI * 2,
      alpha: 0.16 + Math.random() * 0.3
    };
  }

  function build() {
    var count = bladeCount();
    blades = [];
    for (var i = 0; i < count; i++) blades.push(makeBlade(i, count));
    // Near blades drawn last so depth reads correctly.
    blades.sort(function (a, b) { return a.depth - b.depth; });

    motes = [];
    var moteCount = Math.max(10, Math.min(28, Math.round(width / 70)));
    for (var m = 0; m < moteCount; m++) motes.push(makeMote());

    choosePerch();
  }

  /* ------------------------------------------------------- the dragonfly

     Every few minutes one arrives, rests a while, and leaves.

     It lands on the TALLEST blade, and the tall blades are the reader's own
     breakout posts at their real proportions — so it perches on their best
     post. Nothing says so and most people will never notice; the ones who do
     were not told, they worked it out, which is the only kind of detail worth
     putting in.

     It moves the way the insect does: short straight darts, dead stops, a
     hover with a slight wobble. Smooth arcs would read as a butterfly. It
     startles off if the cursor comes near — the grass already parts for the
     cursor, so the gesture is one this field already has — and comes back
     later.

     Cheap by construction: one object, a handful of ellipses, inside the loop
     that was already running. None of it runs under prefers-reduced-motion,
     because this file returns before any of it. */
  var fly = null;
  var perch = -1;             // the tallest blade, kept for the meadow's sake
  var at = null;              // the perch it is heading for or sitting on
  var nextVisit = 0;

  /* Around often enough to be a companion rather than an easter egg, and it
     stays a good while once it settles — long enough to be noticed, wondered
     about and tapped.

     It used to flee the cursor. That was right for a background decoration and
     exactly wrong now: you cannot tap something that runs away as your hand
     approaches. It holds its ground while perched, and startles only if
     something comes at it mid-flight. */
  var FIRST_VISIT = [12, 26];          // seconds after load
  var LATER_VISITS = [55, 140];        // seconds between visits
  var SIT = [26, 64];                  // seconds in ONE spot before moving on
  var HOPS = [3, 7];                   // spots per visit, then it goes
  var STARTLE_RADIUS = 70;             // only while flying

  /* How near a tap has to land.
   *
   * Reported as too hard to hit twice, so it is deliberately far larger than
   * the insect. Nothing else on the page competes for these clicks — the
   * canvas it is drawn on takes no pointer events at all — so a generous
   * radius costs nothing and a miss feels like a broken toy. */
  var TAP_RADIUS = 52;

  function between(range) {
    return range[0] + Math.random() * (range[1] - range[0]);
  }

  /* Somewhere to land.
   *
   * It used to be one place: the single tallest blade, every visit, for as long
   * as it stayed. Watching the same insect sit on the same stalk is watching a
   * screensaver. Now there is a list, and it hops between them — a handful of
   * the tall blades, and the parts of the page that mean something:
   *
   *   .post-badge    the breakout number on a card
   *   .scale-median  the notch that IS the group's median
   *   .stat-value    the headline figures at the top of the feed
   *   .meadow        a group's own drawn field
   *
   * The elements are measured live, so a perched dragonfly rides a card as the
   * page scrolls, and gives up a spot that scrolls out of sight.
   */
  var SPOT_SELECTORS = [".post-badge", ".scale-median", ".stat-value", ".meadow"];
  var TALL_BLADES = 6;

  function tallBlades() {
    var ranked = [];
    for (var i = 0; i < blades.length; i++) {
      ranked.push({ index: i, worth: blades[i].height * (blades[i].outlier ? 1.35 : 1) });
    }
    ranked.sort(function (a, b) { return b.worth - a.worth; });
    return ranked.slice(0, TALL_BLADES).map(function (row) {
      return { kind: "blade", index: row.index };
    });
  }

  function pageSpots() {
    var found = [];
    for (var s = 0; s < SPOT_SELECTORS.length; s++) {
      var nodes;
      try {
        nodes = document.querySelectorAll(SPOT_SELECTORS[s]) || [];
      } catch (error) {
        nodes = [];
      }
      for (var n = 0; n < nodes.length && found.length < 14; n++) {
        if (spotPoint({ kind: "node", el: nodes[n] })) {
          found.push({ kind: "node", el: nodes[n] });
        }
      }
    }
    return found;
  }

  /* Where a perch is, right now, in window coordinates — or null if it is not
   * a place to sit any more. The canvas is fixed to the viewport, so an
   * element's own rectangle is already in the right coordinate space. */
  function spotPoint(spot) {
    if (!spot) return null;
    if (spot.kind === "blade") {
      var blade = blades[spot.index];
      if (!blade || blade.tipX === undefined) return null;
      return { x: blade.tipX, y: blade.tipY - 7, blade: blade };
    }
    var box;
    try {
      box = spot.el.getBoundingClientRect();
    } catch (error) {
      return null;
    }
    if (!box || !box.width || !box.height) return null;
    // Wholly on screen, with room above for the insect to sit.
    if (box.top < 60 || box.bottom > height - 8) return null;
    if (box.right < 20 || box.left > width - 20) return null;
    return { x: box.left + box.width / 2, y: box.top - 7 };
  }

  function choosePerch() {
    var spots = tallBlades();
    perch = spots.length ? spots[0].index : -1;
    if (!at) at = spots[0] || null;
  }

  /* A different place from the one it is on. Page furniture is weighted over
   * grass, because a dragonfly on the median notch is the one that makes
   * somebody look twice. */
  function anotherSpot(avoid) {
    var spots = pageSpots();
    var grass = tallBlades();
    var pool = spots.concat(spots.length ? grass.slice(0, 2) : grass);
    var usable = [];
    for (var i = 0; i < pool.length; i++) {
      if (!same(pool[i], avoid) && spotPoint(pool[i])) usable.push(pool[i]);
    }
    if (!usable.length) return null;
    return usable[Math.floor(Math.random() * usable.length)];
  }

  function same(a, b) {
    if (!a || !b || a.kind !== b.kind) return false;
    return a.kind === "blade" ? a.index === b.index : a.el === b.el;
  }

  function makeFly() {
    // Arrives from whichever side its first perch is further from, so there is
    // a journey to watch rather than a pop-in.
    var first = spotPoint(at);
    var fromLeft = !first || first.x > width / 2;
    return {
      hops: 0,
      sitUntil: 0,
      x: fromLeft ? -40 : width + 40,
      y: height * (0.45 + Math.random() * 0.25),
      vx: 0, vy: 0,
      angle: 0,
      state: "arriving",
      until: 0,                 // when the current hover ends
      wing: 0,
      waypoint: null
    };
  }

  function nextWaypoint(f, now) {
    var target = spotPoint(at);
    if (!target) {
      // Whatever it was heading for has gone. Try elsewhere before giving up.
      at = anotherSpot(at);
      target = spotPoint(at);
    }
    if (!target) {
      f.state = "leaving";
      f.vx = 4; f.vy = -2;
      return;
    }
    var dx = target.x - f.x;
    var dy = target.y - f.y;
    var far = Math.sqrt(dx * dx + dy * dy);

    // Close enough to settle; otherwise dart to a point roughly on the way,
    // off the straight line so the approach reads as an insect's.
    if (far < 26) {
      f.waypoint = { x: target.x, y: target.y, settle: true };
      return;
    }
    var stride = Math.min(far, 90 + Math.random() * 130);
    var heading = Math.atan2(dy, dx) + (Math.random() - 0.5) * 1.1;
    f.waypoint = {
      x: f.x + Math.cos(heading) * stride,
      y: Math.max(40, Math.min(height - 12, f.y + Math.sin(heading) * stride)),
      settle: false
    };
    f.until = now + 140 + Math.random() * 420;     // the hover after the dart
  }

  function startled(f) {
    var dx = f.x - mouse.x;
    var dy = f.y - mouse.y;
    return (dx * dx + dy * dy) < STARTLE_RADIUS * STARTLE_RADIUS;
  }

  function stepFly(now) {
    if (!fly) {
      if (!nextVisit) nextVisit = now + between(FIRST_VISIT) * 1000;
      // A blade has no tip until it has finished growing in (draw() skips one
      // under a pixel tall), and a dragonfly that arrives before then finds
      // nothing to aim at and turns straight round. Waiting a moment is the
      // whole fix; in a browser the meadow is grown long before the first
      // visit is due, so this only matters on a page that was just resized.
      var target = perch >= 0 ? blades[perch] : null;
      if (now >= nextVisit && target && target.tipX !== undefined) {
        fly = makeFly();
        nextVisit = 0;
      }
      return;
    }

    var f = fly;
    f.wing += 1;

    // Only in the air, and never while it is being talked to: a perched
    // dragonfly that bolts when the pointer nears cannot be tapped.
    if (f.state === "arriving" && !said && startled(f)) {
      f.state = "leaving";
      f.vx = (f.x < mouse.x ? -1 : 1) * 6;      // away from the cursor
      f.vy = -3.4;
    }

    if (f.state === "arriving") {
      if (!f.waypoint) nextWaypoint(f, now);
      if (!f.waypoint) return;
      var wp = f.waypoint;
      var dx = wp.x - f.x, dy = wp.y - f.y;
      var dist = Math.sqrt(dx * dx + dy * dy) || 1;

      if (dist < 4) {
        if (wp.settle) {
          f.state = "perched";
          f.hops += 1;
          f.sitUntil = now + between(SIT) * 1000;
          f.maxHops = f.maxHops || Math.round(between(HOPS));
        } else if (now >= f.until) {
          f.waypoint = null;                  // hover over; dart again
        }
      } else {
        // Fast, and faster the further it has to go: a dart, not a drift.
        var speed = Math.min(7.5, 2.2 + dist * 0.06);
        f.x += (dx / dist) * speed;
        f.y += (dy / dist) * speed;
        f.angle = Math.atan2(dy, dx);
      }
      return;
    }

    if (f.state === "perched") {
      var here = spotPoint(at);
      var done = now >= f.sitUntil;

      // Its seat vanished — the card scrolled away, the page changed — or it
      // has sat here long enough. Either way, somewhere else.
      if (!here || done) {
        var next = anotherSpot(at);
        if (next && f.hops < (f.maxHops || 4)) {
          at = next;
          f.state = "arriving";
          f.waypoint = null;
          return;
        }
        f.state = "leaving";
        f.vx = (Math.random() < 0.5 ? -1 : 1) * 4.5;
        f.vy = -2.6;
        return;
      }

      // Rides whatever it is on: a blade as it sways, a card as it scrolls.
      f.x = here.x;
      f.y = here.y;
      f.angle = here.blade
        ? -Math.PI / 2 + Math.sin(time * here.blade.speed + here.blade.phase) * 0.12
        : -Math.PI / 2;
      return;
    }

    // Leaving.
    f.x += f.vx;
    f.y += f.vy;
    f.vy -= 0.02;
    f.angle = Math.atan2(f.vy, f.vx);
    if (f.x < -60 || f.x > width + 60 || f.y < -60) {
      fly = null;
      nextVisit = now + between(LATER_VISITS) * 1000;
    }
  }

  function drawFly() {
    // Its own layer, cleared every frame whether or not anything is on it.
    if (air) airCtx.clearRect(0, 0, width, height);
    if (!fly) return;
    var f = fly;
    var perched = f.state === "perched";

    var ctx = airCtx;              // shadows the meadow's context here only
    ctx.save();
    ctx.translate(f.x, f.y);
    ctx.rotate(f.angle);

    /* A slow breath of light while it is sitting there.
     *
     * Nothing else on the page invites a click, so without this it is scenery
     * and nobody would ever think to try. A pulse is enough of a hint; a
     * "click me" label would spoil the only part of this worth having. */
    if (perched) {
      var pulse = 0.5 + Math.sin(time * 1.6) * 0.5;
      var halo = ctx.createRadialGradient(0, 0, 1, 0, 0, 34);
      halo.addColorStop(0, "rgba(110, 231, 183, " + (0.12 + pulse * 0.1).toFixed(3) + ")");
      halo.addColorStop(1, "rgba(110, 231, 183, 0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(0, 0, 34, 0, Math.PI * 2);
      ctx.fill();
    }

    /* An actual dragonfly, at a size you can see and hit.
     *
     * The first version was three ellipses, which at a glance was a moth. What
     * makes the silhouette read as THIS insect, in order of how much each one
     * does: four wings held out sideways rather than folded back; a long
     * needle of an abdomen, segmented and tapering; and a blunt head that is
     * mostly two enormous eyes.
     *
     * Head toward +x, wings across y. Two body lengths longer than before and
     * about half again as wide, which is what makes it a target.
     */
    var beat = perched ? 0.04 : Math.sin(f.wing * 1.9) * 0.42;

    // WINGS. Held nearly square to the body — a dragonfly at rest does not
    // fold them away, which is most of why the shape is recognisable.
    var wings = [
      { at: 3.5, span: 21, width: 3.4, side: -1 },      // forewings
      { at: 3.5, span: 21, width: 3.4, side: 1 },
      { at: -1.5, span: 18, width: 3.9, side: -1 },     // hindwings, shorter
      { at: -1.5, span: 18, width: 3.9, side: 1 }       // and a touch broader
    ];
    for (var w = 0; w < wings.length; w++) {
      var wing = wings[w];
      ctx.save();
      ctx.translate(wing.at, 0);
      // Perched: swept back a few degrees from square. Flying: beating.
      ctx.rotate(wing.side * (1.36 + beat));
      ctx.beginPath();
      ctx.ellipse(0, wing.span * 0.5, wing.width, wing.span * 0.5, 0, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(220, 248, 236, " + (perched ? 0.26 : 0.16) + ")";
      ctx.fill();
      // A leading edge and, on the forewings, the dark stigma near the tip —
      // both tiny, both what the eye uses to read it as a wing rather than a
      // petal.
      ctx.lineWidth = 0.6;
      ctx.strokeStyle = "rgba(167, 243, 208, " + (perched ? 0.5 : 0.32) + ")";
      ctx.beginPath();
      ctx.moveTo(-wing.width * 0.5, 1);
      ctx.lineTo(-wing.width * 0.2, wing.span * 0.94);
      ctx.stroke();
      if (wing.span > 20) {
        ctx.beginPath();
        ctx.ellipse(-wing.width * 0.25, wing.span * 0.82, 0.9, 1.9, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(16, 60, 42, 0.5)";
        ctx.fill();
      }
      ctx.restore();
    }

    // ABDOMEN. A long taper rather than one ellipse, with segment lines — the
    // thing that stops it reading as a bee.
    var tail = ctx.createLinearGradient(-30, 0, 0, 0);
    tail.addColorStop(0, "rgba(16, 185, 129, 0.75)");
    tail.addColorStop(1, "rgba(110, 231, 183, 0.95)");
    ctx.beginPath();
    ctx.moveTo(-1, -2.1);
    ctx.quadraticCurveTo(-16, -1.5, -29, -0.5);
    ctx.quadraticCurveTo(-31, 0, -29, 0.5);
    ctx.quadraticCurveTo(-16, 1.5, -1, 2.1);
    ctx.closePath();
    ctx.fillStyle = tail;
    ctx.fill();

    ctx.strokeStyle = "rgba(6, 40, 27, 0.35)";
    ctx.lineWidth = 0.5;
    for (var seg = 1; seg <= 5; seg++) {
      var sx = -3 - seg * 4.6;
      var half = 1.9 * (1 - seg / 7);
      ctx.beginPath();
      ctx.moveTo(sx, -half);
      ctx.lineTo(sx, half);
      ctx.stroke();
    }

    // THORAX, where the wings are anchored: short, deep, slightly hunched.
    ctx.beginPath();
    ctx.ellipse(1.5, 0, 5.4, 3.2, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(52, 211, 153, 0.95)";
    ctx.fill();

    // HEAD: mostly eyes. Two of them, wide apart, which no moth has.
    ctx.beginPath();
    ctx.ellipse(7.6, 0, 2.6, 2.9, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(110, 231, 183, 0.95)";
    ctx.fill();

    ctx.fillStyle = "rgba(217, 180, 95, 0.92)";
    ctx.beginPath();
    ctx.ellipse(8.6, -1.9, 2.1, 2.3, 0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(8.6, 1.9, 2.1, 2.3, -0.3, 0, Math.PI * 2);
    ctx.fill();
    // A catchlight on each, so they read as eyes and not as blobs.
    ctx.fillStyle = "rgba(255, 252, 240, 0.85)";
    ctx.beginPath();
    ctx.arc(9.5, -2.4, 0.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(9.5, 2.4, 0.6, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (air) {
      air.width = canvas.width;
      air.height = canvas.height;
      air.style.width = width + "px";
      air.style.height = height + "px";
      airCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    build();
  }

  function step() {
    time += 0.006;

    for (var i = 0; i < blades.length; i++) {
      var b = blades[i];
      if (b.grown < 1) b.grown = Math.min(1, b.grown + b.growRate);
    }

    for (var m = 0; m < motes.length; m++) {
      var mote = motes[m];
      mote.y -= mote.rise;
      mote.x += mote.drift + Math.sin(time * 2 + mote.phase) * 0.16;
      // Recycle at the bottom rather than accumulating new objects.
      if (mote.y < -12) {
        mote.y = height + 12;
        mote.x = Math.random() * width;
      }
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);

    // One shared wind wave so the meadow moves together instead of each
    // blade wobbling on its own.
    var gust = Math.sin(time * 0.7) * 0.5 + Math.sin(time * 1.9) * 0.18;

    for (var i = 0; i < blades.length; i++) {
      var b = blades[i];
      var h = b.height * b.grown;
      if (h < 1) continue;

      var sway = Math.sin(time * b.speed + b.phase) * 0.24 + gust * 0.5;

      /* The cursor parts the grass it passes through.
       *
       * Two limits, both because the dragonfly is now something you reach for:
       *
       * The cursor has to be DOWN in the grass, past the blade's halfway
       * point, rather than anywhere above its tip. It used to be
       * `height - b.height * 1.6`, which on a tall blade is most of the
       * window — so crossing the middle of the page pushed the tall blades
       * about, and the tall blades are exactly where the insect sits.
       *
       * And the blade it is sitting on does not move for the cursor at all
       * while it is there. Riding a tip that recoils from your pointer means
       * the thing you are trying to click walks away from you as you approach
       * it, which is the most quietly infuriating interaction there is. */
      var occupied = fly && fly.state === "perched" && i === perch;
      var dx = b.x - mouse.x;
      if (!occupied && mouse.y > height - h * 0.5 &&
          dx > -MOUSE_RADIUS && dx < MOUSE_RADIUS) {
        var push = (1 - Math.abs(dx) / MOUSE_RADIUS);
        sway += (dx > 0 ? 1 : -1) * push * 0.9;
      }

      var tipX = b.x + (b.lean + sway) * h * 0.42;
      var tipY = height - h;
      // Kept on the blade so the dragonfly can perch on a tip that is moving.
      b.tipX = tipX;
      b.tipY = tipY;
      var ctrlX = b.x + (b.lean + sway) * h * 0.16;
      var ctrlY = height - h * 0.55;

      ctx.beginPath();
      ctx.moveTo(b.x, height);
      ctx.quadraticCurveTo(ctrlX, ctrlY, tipX, tipY);

      ctx.lineWidth = b.outlier ? 2 : 0.7 + b.depth * 1.1;
      ctx.lineCap = "round";

      if (b.outlier) {
        ctx.strokeStyle = "rgba(110, 231, 183, " + (0.34 * b.grown).toFixed(3) + ")";
        ctx.shadowBlur = 10;
        ctx.shadowColor = "rgba(52, 211, 153, 0.5)";
      } else {
        // Nearer blades slightly brighter, so the field has depth.
        var alpha = (0.07 + b.depth * 0.14) * b.grown;
        ctx.strokeStyle = "rgba(52, 211, 153, " + alpha.toFixed(3) + ")";
        ctx.shadowBlur = 0;
      }
      ctx.stroke();

      // A seed head on the tall ones, catching the light.
      if (b.outlier && b.grown > 0.85) {
        ctx.beginPath();
        ctx.arc(tipX, tipY, 2.1, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(110, 231, 183, " + (0.5 + Math.sin(time * 2 + b.phase) * 0.28).toFixed(3) + ")";
        ctx.fill();
      }
    }
    ctx.shadowBlur = 0;

    // Pollen drifting up through the meadow.
    for (var m = 0; m < motes.length; m++) {
      var mote = motes[m];
      ctx.beginPath();
      ctx.arc(mote.x, mote.y, mote.radius, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(167, 243, 208, " + mote.alpha.toFixed(3) + ")";
      ctx.fill();
    }
  }


  /* ------------------------------------------------- what it has to say

     tips.py chose these for this page and this account, best first, and they
     are taken in order rather than at random — the first tap should get the
     most relevant thing, not the luckiest.

     The bubble is real DOM, not canvas: text that can be selected, read by a
     screen reader, and themed by the stylesheet, none of which a painted
     rectangle can do.

     The canvas cannot take clicks — it lies under the whole page with
     pointer-events off, and turning that on would swallow every click in the
     app. So the window is listened to instead, and only a click that lands on
     the insect is treated as one. Everything else passes through untouched. */
  var tips = [];
  var tipAt = 0;
  var said = null;                    // the open bubble, if any

  try {
    var rawTips = document.body.getAttribute("data-tips");
    if (rawTips) {
      tips = JSON.parse(rawTips).filter(function (t) {
        return typeof t === "string" && t.length > 8;
      });
    }
  } catch (error) {
    tips = [];
  }

  function withinTap(x, y) {
    if (!fly) return false;
    var dx = fly.x - x, dy = fly.y - y;
    return (dx * dx + dy * dy) < TAP_RADIUS * TAP_RADIUS;
  }

  function hush() {
    if (!said) return;
    said.parentNode && said.parentNode.removeChild(said);
    said = null;
  }

  function speak() {
    if (!tips.length || !fly) return;
    hush();

    var text = tips[tipAt % tips.length];
    tipAt += 1;

    var bubble = document.createElement("div");
    bubble.className = "dfly-say";
    // A live region: somebody who cannot see the dragonfly still hears the tip
    // when it opens.
    bubble.setAttribute("role", "status");
    bubble.setAttribute("aria-live", "polite");

    var words = document.createElement("p");
    words.textContent = text;
    bubble.appendChild(words);

    var more = document.createElement("button");
    more.type = "button";
    more.className = "dfly-more";
    more.textContent = tips.length > 1 ? "Tell me another" : "Thanks";
    bubble.appendChild(more);

    var shut = document.createElement("button");
    shut.type = "button";
    shut.className = "dfly-shut";
    shut.setAttribute("aria-label", "Close");
    shut.textContent = "×";
    bubble.appendChild(shut);

    more.addEventListener("click", function (event) {
      event.stopPropagation();
      if (tips.length > 1) speak(); else hush();
    });
    shut.addEventListener("click", function (event) {
      event.stopPropagation();
      hush();
    });

    document.body.appendChild(bubble);
    said = bubble;
    placeBubble();

    // Sitting still while it is being talked to, however long that takes.
    if (fly.state === "perched") fly.sitUntil = Date.now() + between(SIT) * 1000;
  }

  function placeBubble() {
    if (!said || !fly) return;
    var width = said.offsetWidth || 260;
    var height = said.offsetHeight || 90;
    // Beside it, and flipped to whichever side has room.
    var left = fly.x + 26;
    if (left + width > window.innerWidth - 12) left = fly.x - width - 26;
    var top = fly.y - height - 14;
    if (top < 12) top = fly.y + 22;
    said.style.left = Math.max(12, left) + "px";
    said.style.top = top + "px";
  }

  window.addEventListener("click", function (event) {
    if (withinTap(event.clientX, event.clientY)) {
      // Not preventDefault: nothing underneath was clicked, because the canvas
      // does not take clicks. This only stops the document handler below from
      // immediately closing what just opened.
      event.stopPropagation();
      speak();
    } else if (said && !said.contains(event.target)) {
      hush();
    }
  }, true);

  window.addEventListener("keydown", function (event) {
    if (event.key === "Escape") hush();
  });

  // The pointer says what is tappable, since the insect cannot.
  var pointing = false;
  function pointer(x, y) {
    var over = withinTap(x, y);
    if (over === pointing) return;
    pointing = over;
    try {
      document.body.style.cursor = over ? "pointer" : "";
    } catch (error) { /* nothing worth breaking a page over */ }
  }

  function loop() {
    if (!running) return;
    step();
    draw();
    // After draw(), which is what puts this frame's tip positions on the
    // blades — and so the dragonfly sits in front of the grass it lands on.
    stepFly(Date.now());
    drawFly();
    if (said) {
      // It flew off mid-sentence: the words go with it.
      if (!fly) hush(); else placeBubble();
    }
    pointer(mouse.x, mouse.y);
    frame = requestAnimationFrame(loop);
  }

  window.addEventListener("resize", function () {
    clearTimeout(window.__fieldResize);
    window.__fieldResize = setTimeout(function () {
      // A rebuild replaces every blade, including the one it was sitting on.
      hush();
      fly = null;
      resize();
    }, 180);
  });

  window.addEventListener("mousemove", function (event) {
    mouse.x = event.clientX;
    mouse.y = event.clientY;
  }, { passive: true });

  window.addEventListener("mouseout", function () {
    mouse.x = -9999;
    mouse.y = -9999;
  });

  // A background animation has no business burning cycles on a hidden tab.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(frame);
    } else if (!running) {
      running = true;
      loop();
    }
  });

  /* A read-only window onto the animation.
   *
   * The dragonfly is a state machine — it arrives, perches on a particular
   * blade, startles, leaves, comes back — and none of that is testable by
   * looking at a canvas. This is how tests/dragonfly.test.js drives it, and
   * it is a useful thing to poke at in a console. It exposes copies and
   * functions only; nothing here can change the field.
   */
  window.__field = {
    blades: function () { return blades.length; },
    perch: function () { return perch; },
    tip: function () {
      var b = blades[perch];
      return b ? { x: b.tipX, y: b.tipY, grown: b.grown, height: b.height } : null;
    },
    tallest: function () {
      var best = -1, worth = -1;
      for (var i = 0; i < blades.length; i++) {
        var w = blades[i].height * (blades[i].outlier ? 1.35 : 1);
        if (w > worth) { worth = w; best = i; }
      }
      return best;
    },
    fly: function () {
      return fly ? { x: fly.x, y: fly.y, state: fly.state } : null;
    },
    visitIn: function (now) { return nextVisit ? nextVisit - now : null; },
    tips: function () { return tips.length; },
    spot: function () {
      if (!at) return null;
      return at.kind === "blade" ? { kind: "blade", index: at.index }
                                 : { kind: "node", of: at.el.className || "node" };
    },
    spots: function () { return pageSpots().length; },
    hops: function () { return fly ? fly.hops : 0; },
    saying: function () {
      return said ? said.querySelector("p").textContent : null;
    },
    // What a click at this point would do, without dispatching one.
    tappableAt: function (x, y) { return withinTap(x, y); },
    running: function () { return running; }
  };

  resize();
  loop();
})();
