/* The connect script only trusts a real dashboard.
 *
 * connect.js takes an API key from the page it runs on and stores that page's
 * OWN origin as the endpoint every capture is sent to. That is fine on the
 * dashboard and catastrophic anywhere else — and the manifest matched
 * `https://*.onrender.com/*`, a domain anybody can deploy a free site on. Any
 * Render-hosted page could have re-pointed the extension at itself and
 * received every post the user scanned from then on.
 *
 * Two things are pinned here: the manifest does not match a whole shared
 * domain, and the script refuses to run on an origin that is not a dashboard
 * even if the matches are widened again.
 *
 * Run: node tests/connect.test.js
 */
var fs = require("fs");
var path = require("path");

var SRC = path.join(__dirname, "..", "extension", "connect.js");
var MANIFEST = path.join(__dirname, "..", "extension", "manifest.json");

var failures = [];

function check(name, got, want) {
  var ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? "  ok   " : " FAIL  ") + name +
              (ok ? "" : "   got " + JSON.stringify(got) + ", want " + JSON.stringify(want)));
  if (!ok) failures.push(name);
}

/* Load connect.js against a fake page and a fake chrome, and report what it
 * did: whether it announced itself, and what it stored. */
function runOn(href) {
  var stored = null;
  var announced = [];
  var listeners = {};
  var url = new URL(href);

  var sandbox = {
    window: {
      location: {
        href: href, origin: url.origin, protocol: url.protocol,
        hostname: url.hostname, host: url.host
      },
      addEventListener: function (name, fn) { listeners[name] = fn; },
      dispatchEvent: function (event) { announced.push(event); }
    },
    CustomEvent: function (type, init) {
      this.type = type;
      this.detail = (init || {}).detail;
    },
    chrome: {
      runtime: {
        lastError: null,
        getManifest: function () { return { version: "0.0.0" }; },
        sendMessage: function () {}
      },
      storage: {
        local: {
          get: function (keys, cb) { cb({}); },
          set: function (values, cb) { stored = values; cb(); }
        }
      }
    }
  };
  sandbox.window.CustomEvent = sandbox.CustomEvent;

  var vm = require("vm");
  var context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf8"), context);

  return {
    announced: announced,
    listeners: listeners,
    stored: function () { return stored; },
    // What a hostile page would do: dispatch the connect event itself.
    connect: function (key) {
      if (!listeners["outlier:connect"]) return "no listener";
      listeners["outlier:connect"]({ detail: { apiKey: key } });
      return stored;
    }
  };
}

console.log("the manifest does not trust a whole shared domain");
var manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
var hosts = (manifest.host_permissions || []).concat(
  (manifest.content_scripts || []).reduce(function (all, entry) {
    return all.concat(entry.matches || []);
  }, []));
var shared = hosts.filter(function (h) {
  // A wildcard in front of a domain nobody here controls.
  return /^https?:\/\/\*\.(onrender|herokuapp|vercel|netlify|github|pages)\b/.test(h);
});
check("no wildcard on a domain anybody can deploy to", shared, []);
check("the real Render host is still allowed",
      hosts.indexOf("https://outlier-q7ie.onrender.com/*") !== -1, true);

console.log("");
console.log("on the dashboard it works");
var good = runOn("https://tallgrassapp.com/feed");
check("it announces itself", good.announced.length > 0, true);
check("  as present", good.announced[0].type, "outlier:extension-present");
check("a key from the page is stored",
      (good.connect("tg-key-123") || {}).apiKey, "tg-key-123");
check("  with the dashboard as the endpoint",
      (good.stored() || {}).endpoint, "https://tallgrassapp.com");

console.log("");
console.log("on localhost it works too, because that is how it is developed");
var local = runOn("http://localhost:5000/feed");
check("it announces itself", local.announced.length > 0, true);
check("and stores", (local.connect("dev-key") || {}).apiKey, "dev-key");

console.log("");
console.log("on somebody else's site it does nothing at all");
["https://evil.onrender.com/page",
 "https://tallgrassapp.com.evil.com/",
 "https://evil-tallgrassapp.com/",
 "http://tallgrassapp.com/",          // plain http, not the real dashboard
 "https://www.facebook.com/groups/1"].forEach(function (href) {
  var bad = runOn(href);
  check("  " + href + " is not announced to", bad.announced.length, 0);
  check("    and cannot push a key", bad.connect("stolen-key"), "no listener");
  check("    so nothing is stored", bad.stored(), null);
});

console.log("");
if (failures.length) {
  console.log(failures.length + " FAILURES: " + failures.join(", "));
  process.exit(1);
}
console.log("only a real dashboard can point the extension anywhere");
