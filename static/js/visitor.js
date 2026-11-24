/* Heading math is shared with tests/visitor.test.js. The sprite is drawn
   facing +x. scaleX(-1) turns it to face left. Pitch is only the small
   tilt off that axis, so a right-side approach never spins through 180. */
function normDeg(d) {
  d = d % 360;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return d;
}

function poseForVelocity(vx, vy) {
  var heading = Math.atan2(vy, vx) * 180 / Math.PI;
  if (!isFinite(heading)) heading = 0;
  var facing = vx < 0 ? -1 : 1;
  var base = facing < 0 ? 180 : 0;
  var pitch = normDeg(heading - base);
  return { facing: facing, pitch: pitch, heading: heading };
}

function restCenterY(cardTop, spriteH) {
  return cardTop - spriteH / 2;
}

function spriteBox(cx, cy, w, h) {
  return {
    left: cx - w / 2,
    top: cy - h / 2,
    right: cx + w / 2,
    bottom: cy + h / 2
  };
}

function boxesIntersect(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

// A scroll or resize moves the perch. A couple of pixels is layout noise.
function perchShifted(rest, live, tol) {
  return Math.abs(live.x - rest.x) > tol || Math.abs(live.y - rest.y) > tol;
}

// The step at the end of an ease-in exit can be 40–70px. Keep the direction,
// drop the length to a glide.
function capStep(dx, dy, maxPx) {
  var dist = Math.hypot(dx, dy);
  if (!(dist > maxPx) || !(maxPx > 0)) return { x: dx, y: dy };
  var scale = maxPx / dist;
  return { x: dx * scale, y: dy * scale };
}

// Up and out. The first tangent rises more than it slides, so a perch that
// moved does not drag the insect sideways across the copy.
function liftGeometry(x, y, facing) {
  var dir = facing < 0 ? -1 : 1;
  return {
    start: { x: x, y: y },
    control: { x: x + dir * 40, y: y - 140 },
    end: { x: x + dir * 180, y: -100 }
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    normDeg: normDeg,
    poseForVelocity: poseForVelocity,
    restCenterY: restCenterY,
    spriteBox: spriteBox,
    boxesIntersect: boxesIntersect,
    perchShifted: perchShifted,
    capStep: capStep,
    liftGeometry: liftGeometry
  };
}

/* A dragonfly that stops by, rarely.
 *
 * It is an inline SVG, not the meadow's canvas insect: that one lives in the
 * grass. This one crosses the page, lands on the lip of a card, rests, and
 * leaves. Three times a visit at most, and never in the first few seconds.
 * It cannot take a click. It is absent when motion is reduced, and its loop
 * stops while the tab is hidden. Between visits it does not animate at all.
 */

(function () {
  "use strict";

  if (typeof window === "undefined" || !window.matchMedia) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "visitor");
  svg.setAttribute("viewBox", "0 0 86 48");
  svg.setAttribute("aria-hidden", "true");

  function el(name, attrs) {
    var node = document.createElementNS(NS, name);
    var key;
    for (key in attrs) {
      if (key === "className") node.setAttribute("class", attrs[key]);
      else node.setAttribute(key, attrs[key]);
    }
    return node;
  }

  function wing(low) {
    var g = el("g", { className: "visitor-wing" + (low ? " visitor-wing-low" : "") });
    var y = low ? 37 : 11;
    var hindY = low ? 33 : 15;
    // Head is toward +x. These wings sit on that side of the thorax.
    g.appendChild(el("ellipse", { cx: "56", cy: String(y), rx: "18", ry: "5.2" }));
    g.appendChild(el("ellipse", {
      className: "visitor-wing-hind",
      cx: "46", cy: String(hindY), rx: "13", ry: "4"
    }));
    return g;
  }

  svg.appendChild(wing(false));
  svg.appendChild(wing(true));
  // Tail on the left, head on the right, so rotate(atan2) points the head
  // along the direction of travel.
  svg.appendChild(el("ellipse", { className: "visitor-abdomen", cx: "28", cy: "24", rx: "18", ry: "3.1" }));
  svg.appendChild(el("circle", { className: "visitor-thorax", cx: "46", cy: "24", r: "4.4" }));
  svg.appendChild(el("circle", { className: "visitor-head", cx: "55", cy: "24", r: "3.8" }));
  svg.appendChild(el("circle", { className: "visitor-eye", cx: "56.8", cy: "22.4", r: "1.15" }));
  svg.appendChild(el("circle", { className: "visitor-eye", cx: "56.8", cy: "25.6", r: "1.15" }));

  var MAX_VISITS = 3;
  var visits = 0;
  var raf = 0;
  var timer = 0;
  var phase = "idle";
  var started = 0;
  var duration = 0;
  var from = null;
  var control = null;
  var to = null;
  var ratio = 0.5;
  var target = null;
  var restFacing = 1;
  var coast = null;
  var lifting = false;
  var prevPos = null;
  var lastNow = 0;
  var PERCH_TOL = 3;
  var EXIT_CAP = 16;
  var hidden = false;
  var pausedAt = 0;
  var box = { w: 54, h: 32 };

  function place(x, y, pitch, facing, opacity) {
    svg.style.transform = "translate3d(" + (x - box.w / 2).toFixed(1) + "px," +
      (y - box.h / 2).toFixed(1) + "px,0) rotate(" + pitch.toFixed(1) +
      "deg) scaleX(" + facing + ")";
    svg.style.opacity = String(opacity);
  }

  // The gap above the card is about the height of the sprite. A hover of
  // a couple of pixels either covers the line above or drops into the card,
  // and it was the hop at takeoff.
  function bob() {
    return 0;
  }

  var entrySide = 1;

  function headerFloor() {
    var bar = document.querySelector(".lp-bar, .topbar");
    if (!bar) return 24;
    return bar.getBoundingClientRect().bottom + 24;
  }

  // The outer top edge, fully on screen: below the sticky header, and above
  // the bottom of the viewport. A card slid under the bar is not a perch.
  function edgeOk(node) {
    if (!node || !node.getBoundingClientRect) return false;
    var r = node.getBoundingClientRect();
    var y = r.top + 1;
    if (r.width < 40) return false;
    if (y < headerFloor()) return false;
    if (y > window.innerHeight - 40) return false;
    if (r.right < 32 || r.left > window.innerWidth - 32) return false;
    return true;
  }

  function choose() {
    // The whole Black Friday card, or a whole feed card. A row inside the
    // preview is not a card, so it is not a perch.
    var promo = document.querySelector(".lp-promo");
    var cards = document.querySelectorAll(".post-card, .lp-proof");
    var pool = [];
    var i;
    if (promo && edgeOk(promo)) pool.push(promo);
    for (i = 0; i < cards.length; i++) {
      if (cards[i] !== promo && edgeOk(cards[i])) pool.push(cards[i]);
    }
    if (!pool.length) return null;
    if (promo && edgeOk(promo) && Math.random() < 0.7) return promo;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function pointOn(node) {
    var r = node.getBoundingClientRect();
    // Feet on the rim: the whole sprite, wings included, sits above the edge.
    return { x: r.left + ratio * r.width, y: restCenterY(r.top, box.h) };
  }

  function bezier(t) {
    var u = 1 - t;
    return {
      x: u * u * from.x + 2 * u * t * control.x + t * t * to.x,
      y: u * u * from.y + 2 * u * t * control.y + t * t * to.y
    };
  }

  function bezierDeriv(u) {
    var o = 1 - u;
    return {
      x: 2 * o * (control.x - from.x) + 2 * u * (to.x - control.x),
      y: 2 * o * (control.y - from.y) + 2 * u * (to.y - control.y)
    };
  }

  function alongOf(t) {
    if (phase === "in" || lifting) return easeOut(t);
    return easeIn(t);
  }

  function alongRate(t) {
    if (phase === "in" || lifting) return 3 * Math.pow(1 - t, 2) / duration;
    return 3 * t * t / duration;
  }

  function velocityAt(t) {
    var d = bezierDeriv(alongOf(t));
    var rate = alongRate(t);
    return { x: d.x * rate, y: d.y * rate };
  }

  function textRects() {
    var nodes = document.querySelectorAll(
      ".lp-h1, .lp-lede, .lp-eyebrow, .lp-reassure, .post-body, .lpc-caption, .lpc-meta"
    );
    var rects = [];
    var i;
    for (i = 0; i < nodes.length; i++) {
      var r = nodes[i].getBoundingClientRect();
      if (r.width > 8 && r.height > 8) rects.push(r);
    }
    return rects;
  }

  function quad(start, control, end, u) {
    var o = 1 - u;
    return {
      x: o * o * start.x + 2 * o * u * control.x + u * u * end.x,
      y: o * o * start.y + 2 * o * u * control.y + u * u * end.y
    };
  }

  function bodyHits(x, y, rects) {
    var halfW = 28;
    var halfH = 16;
    var i;
    for (i = 0; i < rects.length; i++) {
      var r = rects[i];
      if (x + halfW > r.left && x - halfW < r.right &&
          y + halfH > r.top && y - halfH < r.bottom) return true;
    }
    return false;
  }

  function pathClear(start, control, end, texts) {
    var s;
    for (s = 1; s <= 14; s++) {
      var p = quad(start, control, end, s / 14);
      if (bodyHits(p.x, p.y, texts)) return false;
    }
    return true;
  }

  // Come in from a side, bend through the margin beside the headline, and
  // descend onto the rim. The bend is pushed out and down until it misses
  // the copy. Leaving takes the other side.
  // Lowest y the body center may use without the sprite covering copy
  // that sits above the perch.
  function copyFloor(texts, land) {
    var bottom = headerFloor();
    var i;
    for (i = 0; i < texts.length; i++) {
      var r = texts[i];
      if (r.bottom < land.y + 4 && r.bottom > bottom) bottom = r.bottom;
    }
    return bottom + 18;
  }

  function planIn(land) {
    var search = window.location.search || "";
    if (/[?&]entry=right(?:&|$)/.test(search)) entrySide = 1;
    else if (/[?&]entry=left(?:&|$)/.test(search)) entrySide = -1;
    else entrySide = Math.random() < 0.5 ? -1 : 1;
    var texts = textRects();
    var floor = copyFloor(texts, land);
    var start = {
      x: entrySide < 0 ? -100 : window.innerWidth + 100,
      y: Math.max(floor, land.y - 56 - Math.random() * 20)
    };
    var control = {
      x: entrySide < 0 ? Math.min(200, land.x - 70) : Math.max(window.innerWidth - 200, land.x + 70),
      y: Math.max(floor, land.y - 36)
    };
    var i;
    for (i = 0; i < 6 && !pathClear(start, control, land, texts); i++) {
      control.y = Math.max(control.y, floor) + 8;
      start.y = Math.max(start.y, floor);
      if (control.y > land.y) control.y = land.y;
    }
    // Level out onto the rim when that still misses the copy, so the rest
    // pose (pitch 0, facing the way we arrived) matches the last velocity.
    var flat = { x: control.x, y: land.y };
    if (pathClear(start, flat, land, texts)) control = flat;
    return { start: start, control: control, end: land };
  }

  function planOut(land) {
    // Keep going the way we arrived. entry from the left means leave right.
    var dir = restFacing || (-entrySide || 1);
    var texts = textRects();
    var floor = copyFloor(texts, land);
    var end = {
      x: dir < 0 ? -100 : window.innerWidth + 100,
      y: Math.max(floor, land.y - 28)
    };
    var control = {
      x: land.x + dir * 140,
      y: land.y
    };
    var i;
    for (i = 0; i < 6 && !pathClear(land, control, end, texts); i++) {
      control.y = Math.min(land.y, control.y + 8);
      end.y = Math.min(land.y, Math.max(end.y, floor));
    }
    return { start: { x: land.x, y: land.y }, control: control, end: end };
  }

  function arm(next, ms, start, end, perch, controlPoint) {
    phase = next;
    duration = ms;
    started = performance.now();
    from = start;
    to = end;
    control = controlPoint;
    target = perch || null;
    prevPos = null;
    svg.classList.toggle("is-flying", next !== "resting");
    svg.classList.toggle("is-resting", next === "resting");
    svg.classList.add("is-on");
    if (!raf) raf = requestAnimationFrame(tick);
  }

  function later(ms) {
    clearTimeout(timer);
    timer = setTimeout(function () {
      timer = 0;
      if (!hidden) launch();
    }, ms);
  }

  function launch() {
    if (hidden || visits >= MAX_VISITS) return;
    var perch = choose();
    if (!perch) {
      later(7000);
      return;
    }
    visits += 1;
    lifting = false;
    ratio = 0.32 + Math.random() * 0.36;
    var land = pointOn(perch);
    var path = planIn(land);
    restFacing = entrySide < 0 ? 1 : -1;
    arm("in", 2800, path.start, path.end, perch, path.control);
  }

  function easeIn(t) {
    return t * t * t;
  }

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function depart(here) {
    lifting = false;
    var path = planOut(here);
    arm("out", 2100, path.start, path.end, null, path.control);
  }

  // The card moved under a resting insect. Leave upward and outward now,
  // instead of sitting on the old screen point and then sliding across copy.
  function liftOff(here) {
    var path = liftGeometry(here.x, here.y, restFacing || 1);
    lifting = true;
    arm("out", 2100, path.start, path.end, null, path.control);
  }

  // Keep the current direction and speed. A new ease-in from zero would
  // stop the insect in mid-air.
  function coastOn(x, y, vx, vy) {
    var sp = Math.hypot(vx, vy);
    if (sp < 0.05) {
      vx = (restFacing || 1) * 0.25;
      vy = 0;
      sp = 0.25;
    }
    lifting = false;
    phase = "coast";
    coast = { x: x, y: y, vx: vx, vy: vy };
    started = performance.now();
    duration = 2100;
    target = null;
    svg.classList.add("is-flying");
    svg.classList.remove("is-resting");
    if (!raf) raf = requestAnimationFrame(tick);
  }

  function tick(now) {
    raf = requestAnimationFrame(tick);
    if (hidden) return;

    var frameMs = 16;
    if (lastNow) {
      frameMs = now - lastNow;
      if (!(frameMs > 0) || frameMs > 48) frameMs = 16;
    }
    lastNow = now;

    var t = Math.min(1, (now - started) / duration);
    var wobble = bob(now);

    if (phase === "coast") {
      var dt = 16;
      var damp = 1 - 0.35 * t;
      coast.x += coast.vx * dt * damp;
      coast.y += coast.vy * dt * damp;
      var coastPose = poseForVelocity(coast.vx, coast.vy);
      var coastFade = t > 0.65 ? 1 - (t - 0.65) / 0.35 : 1;
      place(coast.x, coast.y + wobble, coastPose.pitch, coastPose.facing,
        0.9 * Math.max(0, coastFade));
      if (t >= 1) {
        phase = "idle";
        svg.classList.remove("is-flying", "is-resting", "is-on");
        svg.style.opacity = "0";
        cancelAnimationFrame(raf);
        raf = 0;
        if (visits < MAX_VISITS) later(22000 + Math.random() * 8000);
      }
      return;
    }

    if (phase === "resting") {
      var live = target ? pointOn(target) : null;
      if (!live || !edgeOk(target) || perchShifted(to, live, PERCH_TOL)) {
        liftOff(to);
        return;
      }
      place(to.x, to.y + wobble, 0, restFacing, 0.88);
      if (t >= 1) depart(to);
      return;
    }

    if (phase === "in" && target && !edgeOk(target)) {
      var lost = bezier(easeOut(t));
      var lostV = velocityAt(t);
      coastOn(lost.x, lost.y, lostV.x, lostV.y);
      return;
    }

    var along = alongOf(t);
    var pos = bezier(along);
    var vel = velocityAt(t);
    if (phase === "out" && prevPos) {
      var capped = capStep(pos.x - prevPos.x, pos.y - prevPos.y, Math.min(EXIT_CAP, 0.9 * frameMs));
      pos = { x: prevPos.x + capped.x, y: prevPos.y + capped.y };
      if (Math.hypot(capped.x, capped.y) > 0.35) vel = { x: capped.x, y: capped.y };
    }
    if (phase === "out") prevPos = { x: pos.x, y: pos.y };
    var flight = poseForVelocity(vel.x, vel.y);
    var fade = phase === "in" ? Math.min(1, t / 0.18)
      : (lifting ? Math.pow(1 - t, 3) : (t > 0.65 ? 1 - (t - 0.65) / 0.35 : 1));
    place(pos.x, pos.y + wobble, flight.pitch, flight.facing, 0.9 * Math.max(0, fade));
    if (t < 1) return;

    if (phase === "in" && target && edgeOk(target)) {
      var nowP = pointOn(target);
      // One correction as the feet meet the rim, not a chase along the way.
      // A layout shift of a few pixels still counts as the same perch.
      if (Math.abs(nowP.x - to.x) < 48 && Math.abs(nowP.y - to.y) < 48) {
        to = nowP;
        phase = "resting";
        duration = 4600;
        started = performance.now();
        svg.classList.remove("is-flying");
        svg.classList.add("is-resting");
        place(to.x, to.y, 0, restFacing, 0.88);
        return;
      }
    }
    if (phase === "in") {
      coastOn(pos.x, pos.y, vel.x, vel.y);
      return;
    }

    lifting = false;
    phase = "idle";
    svg.classList.remove("is-flying", "is-resting", "is-on");
    svg.style.opacity = "0";
    cancelAnimationFrame(raf);
    raf = 0;
    if (visits < MAX_VISITS) later(22000 + Math.random() * 8000);
  }

  document.addEventListener("visibilitychange", function () {
    hidden = document.hidden;
    document.documentElement.classList.toggle("is-away", hidden);
    if (hidden) {
      pausedAt = performance.now();
      cancelAnimationFrame(raf);
      raf = 0;
      clearTimeout(timer);
      timer = 0;
      return;
    }
    var drift = pausedAt ? performance.now() - pausedAt : 0;
    pausedAt = 0;
    if (phase === "idle") {
      if (visits < MAX_VISITS) later(drift > 0 ? 1500 : 8000);
      return;
    }
    started += drift;
    if (!raf) raf = requestAnimationFrame(tick);
  });

  function start() {
    document.body.appendChild(svg);
    var measured = svg.getBoundingClientRect();
    if (measured.width) {
      box.w = measured.width;
      box.h = measured.height;
    }
    // After the hero has settled, not on the first paint. Later visits
    // are much further apart.
    later(5000 + Math.random() * 2000);
  }

  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
