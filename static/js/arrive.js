/* Landing-page arrivals.
 *
 * The feed already reveals its cards from outlier.js. This is the same idea
 * for the public page, which does not load that file: a block marked .arrive
 * fades up the first time it scrolls into view, the preview rings draw
 * themselves, and the multiple counts up.
 *
 * The "js" class is added before the body is parsed (this file sits in the
 * head), so the hidden state never flashes. Without the script the CSS keeps
 * everything visible. Reduced motion shows the finished state immediately.
 */

(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function countUp(el) {
    var raw = el.getAttribute("data-countup");
    var target = parseFloat(raw);
    if (isNaN(target)) return;
    var decimals = raw.indexOf(".") !== -1 ? 1 : 0;
    if (reduceMotion) {
      el.textContent = target.toFixed(decimals);
      return;
    }
    // Set the start before the next paint, so the finished number never
    // flashes at the moment the card becomes visible.
    el.textContent = (0).toFixed(decimals);
    var duration = Math.max(700, Math.min(700 + Math.abs(target) * 17, 1400));
    var start = performance.now();
    function frame(now) {
      var progress = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = (target * eased).toFixed(decimals);
      if (progress < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  var seen = [];

  function activate(el) {
    if (seen.indexOf(el) !== -1) return;
    seen.push(el);
    el.classList.add("in");
    var nums = el.querySelectorAll("[data-countup]");
    for (var i = 0; i < nums.length; i++) countUp(nums[i]);
  }

  function visible(el) {
    var rect = el.getBoundingClientRect();
    return rect.top < window.innerHeight * 0.92 && rect.bottom > 0;
  }

  function start() {
    var nodes = document.querySelectorAll(".arrive");
    if (!nodes.length) return;

    if (reduceMotion || !("IntersectionObserver" in window)) {
      for (var i = 0; i < nodes.length; i++) activate(nodes[i]);
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      var arriving = [];
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) arriving.push(entries[i]);
      }
      arriving.sort(function (a, b) {
        var relation = a.target.compareDocumentPosition(b.target);
        return (relation & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1;
      });
      for (var n = 0; n < arriving.length; n++) {
        (function (el, delay) {
          observer.unobserve(el);
          setTimeout(function () { activate(el); }, delay);
        })(arriving[n].target, n * 70);
      }
    }, { threshold: 0.2, rootMargin: "0px 0px -6% 0px" });

    for (var j = 0; j < nodes.length; j++) observer.observe(nodes[j]);

    // If the observer never fires, anything already on screen still appears.
    // Anything below the fold stays put until it is actually scrolled to.
    setTimeout(function () {
      var pending = document.querySelectorAll(".arrive:not(.in)");
      for (var k = 0; k < pending.length; k++) {
        if (visible(pending[k])) activate(pending[k]);
      }
    }, 1200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
