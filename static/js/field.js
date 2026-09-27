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
  var perch = -1;
  var nextVisit = 0;

  // Rare on purpose. A visitor that turns up constantly is a mascot.
  var FIRST_VISIT = [40, 90];          // seconds after load
  var LATER_VISITS = [150, 330];       // seconds between visits
  var STAY = [18, 45];                 // seconds perched
  var STARTLE_RADIUS = 95;

  function between(range) {
    return range[0] + Math.random() * (range[1] - range[0]);
  }

  function choosePerch() {
    // The tallest, preferring the ones the feed calls outliers.
    var best = -1, bestWorth = -1;
    for (var i = 0; i < blades.length; i++) {
      var worth = blades[i].height * (blades[i].outlier ? 1.35 : 1);
      if (worth > bestWorth) { bestWorth = worth; best = i; }
    }
    perch = best;
  }

  function makeFly() {
    // Arrives from whichever side the perch is further from, so there is a
    // journey to watch rather than a pop-in.
    var target = blades[perch];
    var fromLeft = !target || target.x > width / 2;
    return {
      x: fromLeft ? -40 : width + 40,
      y: height * (0.45 + Math.random() * 0.25),
      vx: 0, vy: 0,
      angle: 0,
      state: "arriving",
      until: 0,                 // when the current hover ends
      leaveAt: 0,               // when to give up the perch
      wing: 0,
      waypoint: null
    };
  }

  function nextWaypoint(f, now) {
    var target = blades[perch];
    if (!target || target.tipX === undefined) {
      f.state = "leaving";
      f.vx = 4; f.vy = -2;
      return;
    }
    var dx = target.tipX - f.x;
    var dy = (target.tipY - 6) - f.y;
    var far = Math.sqrt(dx * dx + dy * dy);

    // Close enough to settle; otherwise dart to a point roughly on the way,
    // off the straight line so the approach reads as an insect's.
    if (far < 26) {
      f.waypoint = { x: target.tipX, y: target.tipY - 5, settle: true };
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

    if (f.state !== "leaving" && startled(f)) {
      // Away from the cursor rather than in a fixed direction.
      f.state = "leaving";
      f.vx = (f.x < mouse.x ? -1 : 1) * 6;
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
          f.leaveAt = now + between(STAY) * 1000;
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
      var blade = blades[perch];
      if (!blade || blade.tipX === undefined || now >= f.leaveAt) {
        f.state = "leaving";
        f.vx = (Math.random() < 0.5 ? -1 : 1) * 4.5;
        f.vy = -2.6;
        return;
      }
      // Rides the blade as it sways, body along the stem.
      f.x = blade.tipX;
      f.y = blade.tipY - 5;
      f.angle = -Math.PI / 2 + Math.sin(time * blade.speed + blade.phase) * 0.12;
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
    if (!fly) return;
    var f = fly;
    var perched = f.state === "perched";

    ctx.save();
    ctx.translate(f.x, f.y);
    ctx.rotate(f.angle);

    // Wings. A beat too fast to resolve reads as a blur, which is what the eye
    // actually sees; at rest they are held open and still, as the insect does.
    var beat = perched ? 0.06 : Math.sin(f.wing * 1.9) * 0.5;
    var span = perched ? 13 : 12;
    ctx.fillStyle = "rgba(214, 245, 232, " + (perched ? 0.3 : 0.18) + ")";
    var pairs = [[-1, -3], [1, -3], [-1, 2], [1, 2]];
    for (var w = 0; w < pairs.length; w++) {
      var side = pairs[w][0], along = pairs[w][1];
      ctx.save();
      ctx.translate(along, 0);
      ctx.rotate(side * (0.5 + beat));
      ctx.beginPath();
      ctx.ellipse(0, side * span * 0.42, span, 2.3, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // A long tail, a thicker thorax, and one gold glint of an eye.
    ctx.beginPath();
    ctx.ellipse(-9, 0, 9, 1.2, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(52, 211, 153, 0.85)";
    ctx.fill();

    ctx.beginPath();
    ctx.ellipse(1, 0, 4, 2.2, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(110, 231, 183, 0.95)";
    ctx.fill();

    ctx.beginPath();
    ctx.arc(5.4, 0, 1.9, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(217, 180, 95, 0.9)";
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

      // The cursor parts the grass it passes over.
      var dx = b.x - mouse.x;
      if (mouse.y > height - b.height * 1.6 && dx > -MOUSE_RADIUS && dx < MOUSE_RADIUS) {
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

  function loop() {
    if (!running) return;
    step();
    draw();
    // After draw(), which is what puts this frame's tip positions on the
    // blades — and so the dragonfly sits in front of the grass it lands on.
    stepFly(Date.now());
    drawFly();
    frame = requestAnimationFrame(loop);
  }

  window.addEventListener("resize", function () {
    clearTimeout(window.__fieldResize);
    window.__fieldResize = setTimeout(function () {
      // A rebuild replaces every blade, including the one it was sitting on.
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
    running: function () { return running; }
  };

  resize();
  loop();
})();
