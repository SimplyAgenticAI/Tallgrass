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
  var REST = -8;
  var hidden = false;
  var pausedAt = 0;
  var box = { w: 54, h: 32 };

  function place(x, y, deg, opacity) {
    svg.style.transform = "translate3d(" + (x - box.w / 2).toFixed(1) + "px," +
      (y - box.h / 2).toFixed(1) + "px,0) rotate(" + deg.toFixed(1) + "deg)";
    svg.style.opacity = String(opacity);
  }

  function inView(node) {
    var r = node.getBoundingClientRect();
    return r.width > 40 && r.bottom > 90 && r.top < window.innerHeight - 36;
  }

  function choose() {
    // The whole Black Friday card, or a whole feed card. A row inside the
    // preview is not a card, so it is not a perch.
    var promo = document.querySelector(".lp-promo");
    var cards = document.querySelectorAll(".post-card, .lp-proof");
    var pool = [];
    var i;
    if (promo && inView(promo)) pool.push(promo);
    for (i = 0; i < cards.length; i++) {
      if (inView(cards[i])) pool.push(cards[i]);
    }
    if (!pool.length) return null;
    if (promo && inView(promo) && Math.random() < 0.7) return promo;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function pointOn(node) {
    var r = node.getBoundingClientRect();
    return { x: r.left + ratio * r.width, y: r.top + 1 };
  }

  function bezier(t) {
    var u = 1 - t;
    return {
      x: u * u * from.x + 2 * u * t * control.x + t * t * to.x,
      y: u * u * from.y + 2 * u * t * control.y + t * t * to.y
    };
  }

  function heading(t) {
    var a = bezier(Math.max(0, t - 0.05));
    var b = bezier(Math.min(1, t + 0.05));
    return Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
  }

  function lerpAngle(a, b, u) {
    var d = ((b - a + 540) % 360) - 180;
    return a + d * u;
  }

  function smooth(u) {
    return u * u * (3 - 2 * u);
  }

  // The last part of the approach eases from the flight angle onto the
  // resting tilt, so the landing does not snap. The start of the departure
  // eases back off that tilt.
  function pose(t) {
    var fly = heading(t);
    if (phase === "in" && t > 0.68) {
      return lerpAngle(fly, REST, smooth((t - 0.68) / 0.32));
    }
    if (phase === "out" && t < 0.32) {
      return lerpAngle(REST, fly, smooth(t / 0.32));
    }
    return fly;
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

  function hitsText(x, y, rects) {
    var i;
    for (i = 0; i < rects.length; i++) {
      var r = rects[i];
      if (x > r.left - 6 && x < r.right + 6 && y > r.top - 6 && y < r.bottom + 6) {
        return true;
      }
    }
    return false;
  }

  // Level with the card's outer top edge. If that line would cross copy,
  // drop onto the rim rather than arc up into the paragraph.
  function route(start, end) {
    var texts = textRects();
    var drop = 0;
    var step;
    for (step = 0; step < 5; step++) {
      var clear = true;
      var s;
      for (s = 1; s <= 10; s++) {
        var u = s / 10;
        var x = start.x + (end.x - start.x) * u;
        var y = start.y + (end.y - start.y) * u + drop;
        // The body sits on the path. Its upper half must stay off the copy too.
        if (hitsText(x, y, texts) || hitsText(x, y - 14, texts)) {
          clear = false;
          break;
        }
      }
      if (clear) break;
      drop += 5;
    }
    return {
      x: (start.x + end.x) / 2,
      y: (start.y + end.y) / 2 + drop
    };
  }

  function arm(next, ms, start, end, perch) {
    phase = next;
    duration = ms;
    started = performance.now();
    from = start;
    to = end;
    control = route(start, end);
    target = perch || null;
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
    ratio = 0.32 + Math.random() * 0.36;
    var land = pointOn(perch);
    // From the left, level with the outer top edge, so the head (facing +x)
    // leads and the path stays off the headline.
    arm("in", 2800, { x: -80, y: land.y }, land, perch);
  }

  function tick(now) {
    raf = requestAnimationFrame(tick);
    if (hidden) return;

    if (phase === "resting" || (phase === "in" && target)) {
      to = pointOn(target);
    }

    var t = Math.min(1, (now - started) / duration);
    if (phase === "resting") {
      place(to.x, to.y, REST, 0.88);
      if (t >= 1) {
        arm("out", 2100, { x: to.x, y: to.y }, {
          x: window.innerWidth + 80,
          y: to.y
        }, null);
      }
      return;
    }

    var pos = bezier(t);
    var fade = phase === "in" ? Math.min(1, t / 0.18) : (t > 0.65 ? 1 - (t - 0.65) / 0.35 : 1);
    place(pos.x, pos.y, pose(t), 0.9 * Math.max(0, fade));
    if (t < 1) return;

    if (phase === "in" && target) {
      to = pointOn(target);
      phase = "resting";
      duration = 4600;
      started = performance.now();
      svg.classList.remove("is-flying");
      svg.classList.add("is-resting");
      place(to.x, to.y, REST, 0.88);
      return;
    }

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
