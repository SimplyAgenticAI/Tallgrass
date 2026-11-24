/* The visiting dragonfly.
 *
 * Heading stays on the velocity. A right-side approach faces left with
 * scaleX, it does not spin the body through 180 degrees. At rest the feet
 * sit on the card's top edge and the sprite does not cover the copy above it.
 *
 * When Chrome is available, the same checks run against the live landing
 * page at 1440 and 390.
 *
 * Run: node tests/visitor.test.js
 */
var fs = require("fs");
var path = require("path");
var math = require(path.join(__dirname, "..", "static", "js", "visitor.js"));

var FAILURES = [];

function check(name, got, want) {
  if (arguments.length === 2) want = true;
  var ok = got === want;
  console.log((ok ? "  ok   " : " FAIL  ") + name +
    (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) FAILURES.push(name);
}

function visual(pose) {
  var base = pose.facing < 0 ? 180 : 0;
  return math.normDeg(base + pose.pitch);
}

console.log("heading matches velocity, including a right-side approach");
var samples = [
  [120, 0], [120, 30], [120, -20],
  [-120, 0], [-120, 25], [-120, -15],
  [-80, 40], [40, 80], [-4, 60], [0.2, -40]
];
samples.forEach(function (v) {
  var pose = math.poseForVelocity(v[0], v[1]);
  var err = Math.abs(math.normDeg(visual(pose) - pose.heading));
  check("vx " + v[0] + " vy " + v[1] + " is within 20 deg", err < 20, true);
});

var fromRight = math.poseForVelocity(-140, 8);
check("arriving from the right faces left", fromRight.facing, -1);
check("and the pitch stays a tilt, not a half turn", Math.abs(fromRight.pitch) < 20, true);
var restAfterRight = { facing: -1, pitch: 0 };
check("rest keeps that facing", restAfterRight.facing, fromRight.facing);
check("rest does not spin away from it",
  Math.abs(math.normDeg(visual(restAfterRight) - visual(fromRight))) < 20, true);

console.log();
console.log("feet on the rim, clear of the copy above the card");
var cardTop = 476;
var h = 32;
var w = 54;
var cy = math.restCenterY(cardTop, h);
var box = math.spriteBox(720, cy, w, h);
check("the bottom of the sprite is the card edge", box.bottom, cardTop);
check("the body is above the card", box.top < cardTop, true);
var lede = { left: 400, top: 380, right: 1040, bottom: cardTop - 40 };
var kicker = { left: 640, top: cardTop + 12, right: 800, bottom: cardTop + 28 };
check("rest misses the paragraph", math.boxesIntersect(box, lede), false);
check("rest misses the label inside the card", math.boxesIntersect(box, kicker), false);

console.log();
console.log("a moved perch lifts off, and the exit does not dart");
var darted = math.capStep(70, 0, 16);
check("a 70px exit step shrinks to a glide", Math.hypot(darted.x, darted.y) < 16.1, true);
check("the glide keeps the exit direction", darted.x > 15 && Math.abs(darted.y) < 0.01, true);
var smallStep = math.capStep(4, -2, 16);
check("a short step is left alone", Math.hypot(smallStep.x, smallStep.y) < 5, true);
var lift = math.liftGeometry(640, 480, -1);
var rise = lift.control.y - lift.start.y;
var slide = lift.control.x - lift.start.x;
check("a disturbed rest lifts up", rise < 0, true);
check("up wins over sideways", Math.abs(rise) > Math.abs(slide), true);
check("and it still heads outward", slide < 0, true);
check("the lift leaves the top of the page", lift.end.y < 0, true);
check("a shifted perch counts", math.perchShifted({ x: 10, y: 20 }, { x: 10, y: 28 }, 3), true);
check("a still perch does not", math.perchShifted({ x: 10, y: 20 }, { x: 11.5, y: 21 }, 3), false);

function chromePath() {
  var candidates = ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"];
  for (var i = 0; i < candidates.length; i++) {
    if (fs.existsSync(candidates[i])) return candidates[i];
  }
  return null;
}

function puppeteerPath() {
  var local = "/tmp/pup/node_modules/puppeteer-core";
  if (fs.existsSync(local)) return local;
  return null;
}

function runPage(done) {
  var chrome = chromePath();
  var pup = puppeteerPath();
  if (!chrome || !pup) {
    console.log();
    console.log("headless page check skipped (no chrome or puppeteer-core)");
    done();
    return;
  }
  var puppeteer = require(pup);
  var viewports = [
    { w: 1440, h: 900, name: "desktop", entry: "right", wantFacing: -1 },
    { w: 390, h: 844, name: "phone", entry: "left", wantFacing: 1 }
  ];

  function readPose(page) {
    return page.evaluate(function () {
      var v = document.querySelector(".visitor");
      if (!v) return null;
      var tr = v.style.transform || "";
      var moved = tr.match(/translate3d\(([-\d.]+)px,\s*([-\d.]+)px/);
      var rot = tr.match(/rotate\(([-\d.]+)deg\)/);
      var sc = tr.match(/scaleX\((-?[\d.]+)\)/);
      return {
        x: moved ? +moved[1] : 0,
        y: moved ? +moved[2] : 0,
        pitch: rot ? +rot[1] : 0,
        facing: sc ? +sc[1] : 1,
        resting: v.getAttribute("class").indexOf("is-resting") !== -1,
        op: parseFloat(v.style.opacity || "0")
      };
    });
  }

  function pause(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }
  puppeteer.launch({
    executablePath: chrome,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"]
  }).then(function (browser) {
    var chain = Promise.resolve();
    viewports.forEach(function (vp) {
      chain = chain.then(function () {
        return browser.newPage().then(function (page) {
          return page.setViewport({ width: vp.w, height: vp.h }).then(function () {
            return page.goto(
              "http://127.0.0.1:5050/?theme=default&entry=" + vp.entry,
              { waitUntil: "networkidle0", timeout: 20000 }
            );
          }).then(function () {
            var prev = null;
            var worst = 0;
            var deadline = Date.now() + 14000;
            function step() {
              return readPose(page).then(function (s) {
                if (prev && s && s.op > 0.45 && !s.resting && !prev.resting) {
                  var dx = s.x - prev.x;
                  var dy = s.y - prev.y;
                  if (Math.hypot(dx, dy) > 2) {
                    var heading = Math.atan2(dy, dx) * 180 / Math.PI;
                    var base = s.facing < 0 ? 180 : 0;
                    var err = Math.abs(math.normDeg((base + s.pitch) - heading));
                    if (err > worst) worst = err;
                  }
                }
                prev = s;
                if (s && s.resting) return { worst: worst, facing: s.facing, pitch: s.pitch };
                if (Date.now() > deadline) return { worst: worst, facing: 0, pitch: 90 };
                return pause(40).then(step);
              });
            }
            return step();
          }).then(function (sample) {
            check(vp.name + " heading stays within 20 deg of velocity", sample.worst < 20, true);
            check(vp.name + " rests facing the way it arrived", sample.facing, vp.wantFacing);
            check(vp.name + " rest pitch stays level", Math.abs(sample.pitch) < 8, true);
          }).then(function () {
            return page.evaluate(function () {
              var v = document.querySelector(".visitor").getBoundingClientRect();
              var card = document.querySelector(".lp-promo").getBoundingClientRect();
              var nodes = document.querySelectorAll("h1, h2, h3, p, a, span, li");
              var hits = [];
              for (var i = 0; i < nodes.length; i++) {
                var t = (nodes[i].innerText || "").trim();
                if (!t) continue;
                var range = document.createRange();
                range.selectNodeContents(nodes[i]);
                var rects = range.getClientRects();
                for (var k = 0; k < rects.length; k++) {
                  var r = rects[k];
                  if (r.width < 2 || r.height < 2) continue;
                  var overlap = v.left < r.right && v.right > r.left &&
                    v.top < r.bottom && v.bottom > r.top;
                  if (overlap) hits.push(t.slice(0, 40));
                }
              }
              return {
                top: v.top, bottom: v.bottom, cardTop: card.top,
                hits: hits
              };
            });
          }).then(function (info) {
            check(vp.name + " feet are on the rim", info.bottom <= info.cardTop + 0.75, true);
            check(vp.name + " body is above the card", info.top < info.cardTop, true);
            check(vp.name + " rest misses every text node", info.hits.length, 0);
            if (info.hits.length) console.log("    overlapped: " + info.hits.join(" | "));
          }).then(function () {
            var restY = null;
            var deadline = Date.now() + 7000;
            var leftAt = 0;
            var prev = null;
            var fastest = 0;
            function watchHop() {
              return readPose(page).then(function (s) {
                if (!s) return;
                if (restY === null) restY = s.y;
                if (!s.resting) {
                  if (!leftAt) {
                    leftAt = Date.now();
                    check(vp.name + " takeoff does not hop", Math.abs(s.y - restY) < 1.5, true);
                  } else if (prev && s.op > 0.2) {
                    var dist = Math.hypot(s.x - prev.x, s.y - prev.y);
                    var dt = Math.max(16, Date.now() - prev.at);
                    var speed = dist / dt;
                    if (speed > fastest) fastest = speed;
                  }
                  prev = { x: s.x, y: s.y, at: Date.now() };
                  if (vp.entry === "right" && Date.now() - leftAt > 2200) {
                    check(vp.name + " exit glides", fastest < 1.25, true);
                    return;
                  }
                  if (vp.entry !== "right") return;
                }
                if (Date.now() > deadline && !leftAt) {
                  check(vp.name + " takeoff does not hop", false, true);
                  return;
                }
                if (leftAt && Date.now() - leftAt > 4000) return;
                return pause(30).then(watchHop);
              });
            }
            return watchHop();
          }).then(function () {
            return page.close();
          });
        });
      });
    });
    chain = chain.then(function () {
      return browser.newPage().then(function (page) {
        return page.setViewport({ width: 1440, height: 900 }).then(function () {
          return page.goto("http://127.0.0.1:5050/?theme=default&entry=left", {
            waitUntil: "networkidle0", timeout: 20000
          });
        }).then(function () {
          var prev = null;
          var dir = 0;
          var scrolled = false;
          var movedAfter = 0;
          var reversed = false;
          var worst = 0;
          var deadline = Date.now() + 12000;
          function step() {
            return readPose(page).then(function (s) {
              var flying = s && s.op > 0.5 && !s.resting;
              if (flying && prev && prev.op > 0.5 && !prev.resting) {
                var dx = s.x - prev.x;
                var dy = s.y - prev.y;
                var dist = Math.hypot(dx, dy);
                if (dist > 2) {
                  var heading = Math.atan2(dy, dx) * 180 / Math.PI;
                  var base = s.facing < 0 ? 180 : 0;
                  var err = Math.abs(math.normDeg((base + s.pitch) - heading));
                  if (err > worst) worst = err;
                  if (!scrolled && Math.abs(dx) > 4) dir = dx > 0 ? 1 : -1;
                  if (scrolled) {
                    movedAfter += dist;
                    if (dir && dx * dir < -12) reversed = true;
                  }
                }
              }
              prev = s;
              if (flying && dir && !scrolled) {
                scrolled = true;
                return page.evaluate(function () { window.scrollBy(0, 900); }).then(function () {
                  return pause(40).then(step);
                });
              }
              if (scrolled && movedAfter > 80) {
                return { worst: worst, reversed: reversed, movedAfter: movedAfter, scrolled: true };
              }
              if (Date.now() > deadline) {
                return { worst: worst, reversed: reversed, movedAfter: movedAfter, scrolled: scrolled };
              }
              return pause(40).then(step);
            });
          }
          return step();
        }).then(function (result) {
          check("scroll keeps the visitor moving", result.scrolled && result.movedAfter > 80, true);
          check("scroll does not turn it around", result.reversed, false);
          check("scroll keeps heading on the velocity", result.worst < 20, true);
          return page.close();
        });
      });
    });
    chain = chain.then(function () {
      return browser.newPage().then(function (page) {
        return page.setViewport({ width: 1440, height: 900 }).then(function () {
          return page.goto("http://127.0.0.1:5050/?theme=default&entry=left", {
            waitUntil: "networkidle0", timeout: 20000
          });
        }).then(function () {
          var deadline = Date.now() + 14000;
          function waitRest() {
            return readPose(page).then(function (s) {
              if (s && s.resting) return s;
              if (Date.now() > deadline) return null;
              return pause(40).then(waitRest);
            });
          }
          return waitRest();
        }).then(function (rest) {
          if (!rest) {
            check("scroll during rest finds the perch", false, true);
            return page.close();
          }
          var t0 = Date.now();
          return page.evaluate(function () { window.scrollBy(0, 280); }).then(function () {
            var leftAt = 0;
            var prev = rest;
            var worst = 0;
            var last = rest;
            function step() {
              return readPose(page).then(function (s) {
                if (!s) return;
                if (!s.resting && !leftAt) leftAt = Date.now();
                if (prev && !s.resting && s.op > 0.12) {
                  var dx = s.x - prev.x;
                  var dy = s.y - prev.y;
                  if (Math.hypot(dx, dy) > 2) {
                    var heading = Math.atan2(dy, dx) * 180 / Math.PI;
                    var base = s.facing < 0 ? 180 : 0;
                    var err = Math.abs(math.normDeg((base + s.pitch) - heading));
                    if (err > worst) worst = err;
                  }
                }
                prev = s;
                last = s;
                if (Date.now() - t0 > 800) {
                  return { leftAt: leftAt, worst: worst, last: last };
                }
                return pause(40).then(step);
              });
            }
            return step();
          }).then(function (result) {
            var waited = result.leftAt ? result.leftAt - t0 : 9999;
            var rise = rest.y - result.last.y;
            var slide = Math.abs(result.last.x - rest.x);
            check("scroll during rest takes off immediately", waited < 220, true);
            check("the takeoff lifts up off the copy", rise > 24, true);
            check("up wins over a sideways drift", rise > slide, true);
            check("the takeoff fades as it leaves", result.last.op < 0.7, true);
            check("the takeoff heading stays on the velocity", result.worst < 20, true);
            return page.close();
          });
        });
      });
    });
    return chain.then(function () { return browser.close(); }).then(done);
  }).catch(function (err) {
    console.log("  FAIL  headless page check   " + err.message);
    FAILURES.push("headless page check");
    done();
  });
}

runPage(function () {
  console.log();
  if (FAILURES.length) {
    console.log(FAILURES.length + " FAILURES");
    process.exit(1);
  }
  console.log("the visitor heads the way it flies, and rests above the copy");
});
