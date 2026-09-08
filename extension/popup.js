/* Popup — start/stop capture, endpoint config, live status.
 *
 * Every control reports what happened. A button that silently no-ops is
 * indistinguishable from a broken extension.
 */

const el = (id) => document.getElementById(id);

const capturedEl = el("captured");
const totalEl = el("total");
const startBtn = el("start-btn");
const scanBtn = el("scan-btn");
const toggleEl = el("toggle");
const dotEl = el("dot");
const statusEl = el("status-text");
const endpointEl = el("endpoint");
const apiKeyEl = el("api-key");
const msgEl = el("msg");
const openLink = el("open-dashboard");

let scrolling = false;
let activeTabId = null;
let onFacebook = false;

function say(text, kind) {
  msgEl.textContent = text;
  msgEl.className = "msg" + (kind ? " " + kind : "");
}

/* Is `offered` actually newer than `running`?
 *
 * Tuples of integers, never a float compare: 23.10 as a number is SMALLER
 * than 23.6, so the first two-digit patch in a line would read as a
 * downgrade. And never a plain !== : a hand-loaded copy that is AHEAD of the
 * dashboard it points at would otherwise be offered an older build as an
 * update, which is how you talk somebody into reinstalling backwards.
 *
 * Duplicated in background.js on purpose. The popup and the service worker
 * are separate contexts with no shared module, and six lines in two places
 * beats a build step in an extension that deliberately has none.
 */
function isNewer(offered, running) {
  const parts = (value) => String(value || "").split(".").map((chunk) => {
    const n = parseInt(chunk, 10);
    return isNaN(n) ? 0 : n;
  });
  const a = parts(offered);
  const b = parts(running);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}

/* ---------------------------------------------------------- content script */

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

// The content script only exists on Facebook tabs, so a failed message means
// "wrong page", not "extension broken" — say so rather than failing silently.
function askContentScript(type) {
  return new Promise((resolve) => {
    if (activeTabId === null) return resolve(null);
    chrome.tabs.sendMessage(activeTabId, { type }, (response) => {
      if (chrome.runtime.lastError) return resolve(null);
      resolve(response);
    });
  });
}

/* ------------------------------------------------- what this page is
 *
 * Named before anybody commits to a scan. The popup used to show counts,
 * buttons and a version and never once say which page it was pointed at — you
 * pressed Start and found out afterwards, which is the same silence this
 * file's opening line argues against.
 *
 * It matters most on a search, where the entire question is whether the
 * extension read the words you typed. Seeing them here answers that before
 * the scroll starts rather than after it has finished.
 */
const KIND_WORDS = {
  search: "Search", group: "Group", page: "Page",
  profile: "Profile", feed: "Home feed"
};

function showTarget(target) {
  const kindEl = el("target-kind");
  const nameEl = el("target-name");
  const box = el("target");
  if (!box) return;

  if (!target) {
    box.className = "target is-none";
    kindEl.textContent = "no source";
    // Says what WOULD work rather than only that this does not.
    nameEl.textContent = "Open a group, profile or search";
    return;
  }

  box.className = "target" + (target.isSearch ? " is-search" : "");
  kindEl.textContent = KIND_WORDS[target.kind] || target.kind;
  nameEl.textContent = target.name || "";

  // The search box mirrors the search you are already on, so the field is
  // both the launcher and the proof the query was understood.
  const findEl = el("find-q");
  if (target.isSearch && findEl && !findEl.value.trim()) {
    findEl.value = target.query || target.name || "";
  }
  if (target.isSearch) rememberSearch(target.query || target.name || "");
}

async function refreshFromPage() {
  const response = await askContentScript("OUTLIER_STATS");
  if (!response || !response.ok) {
    onFacebook = false;
    startBtn.disabled = true;
    scanBtn.disabled = true;
    capturedEl.textContent = "—";
    showTarget(null);
    say("Open a Facebook group or search, then press Start.", "warn");
    return;
  }

  onFacebook = true;
  startBtn.disabled = false;
  scanBtn.disabled = false;
  scrolling = response.scrolling;
  capturedEl.textContent = response.stats.sent || 0;
  showTarget(response.target);

  startBtn.textContent = scrolling ? "Stop auto-scroll" : "Start auto-scroll";
  startBtn.className = scrolling ? "btn stop" : "btn";

  if (response.stats.lastError) say(response.stats.lastError, "warn");
  else if (response.stats.articles > 0 && response.stats.candidates === 0) {
    say("Posts detected but none readable — selectors may need updating.", "warn");
  } else if (scrolling) say("Scrolling and capturing…", "ok");
  else say("");
}

/* ---------------------------------------------------------- dashboard */

function checkConnection() {
  statusEl.textContent = "checking…";
  dotEl.className = "dot";

  const running = chrome.runtime.getManifest().version;

  chrome.runtime.sendMessage({ type: "OUTLIER_PING" }, (response) => {
    if (chrome.runtime.lastError || !response || !response.ok) {
      dotEl.className = "dot off";
      // "offline" describes the dashboard as if it were down, when what has
      // actually happened is that this extension has not been handed an
      // account yet. Say the thing the user can act on.
      statusEl.textContent = "not connected";
      say("Open your dashboard once while signed in — it connects itself.");
      el("ext-version").textContent = "v" + running;
      return;
    }
    dotEl.className = "dot on";
    statusEl.textContent = "v" + response.version;

    /* A store copy updates itself, so it is never told about an update.
     *
     * update_url is present in the manifest of an installed store extension
     * and absent from an unpacked one. Reading it needs no permission, which
     * matters: chrome.management would have answered the same question and
     * cost a permission, and a new permission is what turns a routine review
     * into a three-week one.
     *
     * Without this the popup nagged every store user permanently. The
     * dashboard advertises the version in this repo; the store is however
     * many review cycles behind; the two can never agree, so the notice never
     * cleared — and it told them to sideload, which is the exact thing the
     * store listing exists to delete. The dashboard stopped reporting the
     * repo version to hosted browsers in V23.7, which fixed it from the other
     * end; this is the half that lives in the extension, so a store copy
     * pointed at any dashboard stays quiet.
     */
    const fromStore = Boolean(chrome.runtime.getManifest().update_url);

    // A mismatch only self-heals when the extension folder is the live
    // project. Loaded from a zip, or pointed at a hosted dashboard, no
    // amount of reloading changes the files — so say what to actually do.
    const latest = response.extension_version;
    if (!fromStore && latest && latest !== running && isNewer(latest, running)) {
      // Built with textContent, not innerHTML: `latest` comes off the network
      // (the dashboard's reported version), and nothing off the network should
      // ever be parsed as markup, however benign a version string looks.
      var vspan = document.createElement("span");
      vspan.style.color = "#d9b45f";
      vspan.textContent = "v" + running + " → v" + latest;
      var vhost = el("ext-version");
      vhost.textContent = "";
      vhost.appendChild(vspan);

      chrome.storage.local.get(["updateStuck"], (state) => {
        if (state.updateStuck === latest) {
          say("v" + latest + " available. Download it from the dashboard's " +
              "Capture page, unzip over this folder, then hit reload here.", "warn");
        } else {
          say("Update available. Reloading shortly…", "warn");
        }
      });
    } else {
      el("ext-version").textContent = "v" + running + " (current)";
    }
  });
}

/* ---------------------------------------------------------- wiring */

startBtn.addEventListener("click", async () => {
  const response = await askContentScript(scrolling ? "OUTLIER_STOP" : "OUTLIER_START");
  if (!response) {
    say("Couldn't reach the page — reload the Facebook tab.", "err");
    return;
  }
  scrolling = !scrolling;
  startBtn.textContent = scrolling ? "Stop auto-scroll" : "Start auto-scroll";
  startBtn.className = scrolling ? "btn stop" : "btn";
  // Worth saying once, here, where somebody is deciding whether they have to
  // sit and watch it. It used to stop when the tab went to the background,
  // so "you can leave" is new information and not reassurance for its own
  // sake — leave the tab OPEN is the part that still matters.
  say(scrolling
    ? "Scrolling and capturing… you can switch tabs, just leave this one open."
    : "Stopped.", "ok");
});

scanBtn.addEventListener("click", async () => {
  say("Scanning…");
  const response = await askContentScript("OUTLIER_SCAN");
  if (!response) {
    say("Couldn't reach the page — reload the Facebook tab.", "err");
    return;
  }
  setTimeout(refreshFromPage, 700);
});

/* ------------------------------------------------------- finding posts
 *
 * Goes to the POSTS tab, deliberately. Facebook's default search lands on Top,
 * which mixes people and pages in with posts and ranks by popularity — the
 * opposite of useful here, since the request nobody has answered yet is the
 * one worth answering.
 *
 * Recent is NOT built into this URL, and that is a decision rather than an
 * omission. Facebook's Recent toggle is an undocumented base64 filters blob;
 * pasting today's value in would work until it quietly stopped, and the
 * failure would be silent — Top results captured, mediocre scores, nothing
 * saying why. The hint below the field asks for the one click instead, and
 * the dashboard notices afterwards if the results look popular rather than
 * fresh.
 */
const RECENT_KEY = "recentSearches";
const RECENT_MAX = 6;

function searchUrl(query) {
  return "https://www.facebook.com/search/posts/?q=" + encodeURIComponent(query);
}

async function rememberSearch(query) {
  query = (query || "").trim();
  if (!query) return;
  const stored = await chrome.storage.local.get([RECENT_KEY]);
  const list = (stored[RECENT_KEY] || []).filter(
    (q) => q.toLowerCase() !== query.toLowerCase());
  list.unshift(query);
  await chrome.storage.local.set({ [RECENT_KEY]: list.slice(0, RECENT_MAX) });
  renderRecent(list.slice(0, RECENT_MAX));
}

function renderRecent(list) {
  const host = el("recent-searches");
  if (!host) return;
  host.textContent = "";
  (list || []).forEach((query) => {
    // textContent, never innerHTML: these are the user's own words coming
    // back out of storage, and a search someone typed is not markup.
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "recent-search";
    chip.textContent = query;
    chip.addEventListener("click", () => runSearch(query));
    host.appendChild(chip);
  });
}

async function runSearch(query) {
  query = (query || "").trim();
  if (!query) {
    say("Type what you're looking for first.", "warn");
    return;
  }
  await rememberSearch(query);
  const findEl = el("find-q");
  if (findEl) findEl.value = query;

  // The tab the popup is attached to, so this replaces where you are rather
  // than piling up windows across a morning of checking.
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) { say("No tab to search in.", "err"); return; }
  await chrome.tabs.update(tab.id, { url: searchUrl(query) });
  say("Searching… set Recent, then press Start.", "ok");
}

const findGo = el("find-go");
if (findGo) {
  findGo.addEventListener("click", () => runSearch(el("find-q").value));
}
const findInput = el("find-q");
if (findInput) {
  findInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") runSearch(findInput.value);
  });
}
chrome.storage.local.get([RECENT_KEY], (stored) => {
  renderRecent(stored[RECENT_KEY] || []);
});

toggleEl.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: toggleEl.checked });
  say(toggleEl.checked ? "Capture on." : "Capture paused.", "ok");
});

// Chrome blocks the service worker from fetching any origin the extension
// lacks host permission for. The manifest can't list every dashboard someone
// might host, so permission for a custom one is requested at save time —
// otherwise saving "succeeds" and every capture then fails silently.
function ensureHostPermission(url) {
  return new Promise((resolve) => {
    let origin;
    try {
      origin = new URL(url).origin + "/*";
    } catch (error) {
      return resolve(false);
    }
    chrome.permissions.contains({ origins: [origin] }, (has) => {
      if (has) return resolve(true);
      // Must be called from a user gesture, which the click handler is.
      chrome.permissions.request({ origins: [origin] }, (granted) => resolve(!!granted));
    });
  });
}

el("save-endpoint").addEventListener("click", async () => {
  // Accept a pasted page URL and keep only its origin — the paths people
  // copy from the address bar ("/pricing", "/account") are not the API root.
  var raw = endpointEl.value.trim();
  var value;
  try {
    value = new URL(raw).origin;
  } catch (error) {
    value = raw.replace(/\/+$/, "");
  }
  if (!value) {
    say("Enter a dashboard URL first.", "err");
    return;
  }
  if (!/^https?:\/\//.test(value)) {
    say("URL must start with http:// or https://", "err");
    return;
  }

  say("Checking access…");
  const allowed = await ensureHostPermission(value);
  if (!allowed) {
    say("Chrome blocked access to that address. Approve the permission prompt, " +
        "then press Save & test again.", "err");
    return;
  }

  await chrome.storage.local.set({ endpoint: value });
  const key = apiKeyEl.value.trim();
  if (key) await chrome.storage.local.set({ apiKey: key });
  openLink.href = value;
  say("Saved. Testing…");

  chrome.runtime.sendMessage({ type: "OUTLIER_PING" }, (response) => {
    if (chrome.runtime.lastError || !response || !response.ok) {
      dotEl.className = "dot off";
      statusEl.textContent = "not connected";
      const detail = (response && response.error) ? " " + response.error : "";
      say("Saved, but nothing answered there." + detail, "err");
      return;
    }
    dotEl.className = "dot on";
    statusEl.textContent = "v" + response.version;
    say("Connected to " + new URL(value).hostname + " (v" + response.version + ")", "ok");
  });
});

/* ---------------------------------------------------------- init */

/* ---------------------------------------------------------- scan limit */

// Guidance rather than a bare number: the useful range is bounded at both
// ends. Too few posts and there is no median to compare against; too many and
// you are scoring year-old posts against this month's, which is not a fair
// comparison and takes a long time to collect.
const maxPostsEl = el("max-posts");
const limitValEl = el("limit-val");
const limitHintEl = el("limit-hint");

function limitHint(n) {
  if (n <= 75)  return "Quick look. Enough for a baseline, but thin — expect roughly 1–2 min.";
  if (n <= 150) return "Good for a smaller or quieter group. Roughly 2–4 min.";
  if (n <= 250) return "The sweet spot for most groups: a solid baseline from recent posts. Roughly 4–7 min.";
  if (n <= 375) return "Deep scan. Reaches further back, so older posts get compared against newer ones. 7–12 min.";
  return "Very deep. Mostly useful for slow groups where 200 posts spans years. 12+ min.";
}

function renderLimit(n) {
  limitValEl.textContent = n + " posts";
  limitHintEl.textContent = limitHint(n);
}

maxPostsEl.addEventListener("input", () => {
  renderLimit(parseInt(maxPostsEl.value, 10));
});
maxPostsEl.addEventListener("change", () => {
  const n = parseInt(maxPostsEl.value, 10);
  // Scale the time ceiling with the post target so a big scan isn't cut short
  // by a limit sized for a small one.
  chrome.storage.local.set({ maxPosts: n, maxMinutes: Math.max(5, Math.round(n / 20)) });
  say("Scans will stop at " + n + " posts.", "ok");
});

const autoUpdateEl = el("auto-update");
autoUpdateEl.addEventListener("change", () => {
  chrome.storage.local.set({ autoUpdate: autoUpdateEl.checked });
  say(autoUpdateEl.checked
    ? "Auto-update on — picks up changes within a minute."
    : "Auto-update off.", "ok");
});

(async function init() {
  const tab = await getActiveTab();
  activeTabId = tab ? tab.id : null;

  const state = await chrome.storage.local.get([
    "enabled", "endpoint", "totalCaptured", "autoUpdate", "apiKey",
    "lastUpdateFrom", "lastUpdateTo", "maxPosts"
  ]);
  totalEl.textContent = state.totalCaptured || 0;
  toggleEl.checked = state.enabled !== false;
  autoUpdateEl.checked = state.autoUpdate !== false;

  const limit = state.maxPosts || 200;
  maxPostsEl.value = limit;
  renderLimit(limit);
  endpointEl.value = state.endpoint || "";
  // Never re-display the stored key; show only that one is present.
  apiKeyEl.placeholder = state.apiKey
    ? "Key saved — paste a new one to replace it"
    : "olk_… from the Account page";
  openLink.href = endpointEl.value || "#";
  openLink.style.display = endpointEl.value ? "" : "none";

  // Report a completed self-update once, then clear the marker.
  if (state.lastUpdateTo && state.lastUpdateTo === chrome.runtime.getManifest().version) {
    say("Updated to v" + state.lastUpdateTo + ". Reload any open Facebook tabs.", "ok");
    chrome.storage.local.remove(["lastUpdateFrom", "lastUpdateTo"]);
  }

  checkConnection();
  refreshFromPage();
  setInterval(refreshFromPage, 1500);   // keep counts live while scrolling
})();
