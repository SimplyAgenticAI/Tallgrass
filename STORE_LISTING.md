# Chrome Web Store submission — Tallgrass

## ✅ LIVE — approved 6 September 2026

- **Listing:** https://chromewebstore.google.com/detail/tallgrass-%E2%80%94-by-macrandle/mjnnjgcfknpjddiglapjjgpkhpogccgg
- **Extension ID:** `mjnnjgcfknpjddiglapjjgpkhpogccgg`
- **Approved package:** v22.9

The URL lives in code at `app.py` → `EXTENSION_STORE_URL`, which is where the
Capture page and both onboarding emails read it from. Change it there and
nowhere else if the listing is ever re-published under a new slug.

**The approved package points `DEFAULT_ENDPOINT` at `http://localhost:5050`,
and that is correct — do not "fix" it.** A store build is generic and cannot
know which dashboard it belongs to. `connect.js` runs on `tallgrassapp.com`
and writes the real origin plus a freshly minted key into extension storage
the first time somebody opens the dashboard signed in, so the localhost
literal only ever applies to an extension that has never seen a dashboard.

Re-uploading a build stamped with a hardcoded production URL would break
every self-hosted and local install for no gain.

---

## Which changes need the store at all?

**Almost none of them.** Fourteen of the fifteen releases before V23.7 touched
no extension code whatsoever. The rule, readable straight off a diff:

| You changed | What to do |
|---|---|
| `app.py`, `templates/`, `static/`, `outreach.py` … | Bump `APP_VERSION`, `git push`. Live in ~2 min. |
| Anything inside `extension/` | Bump the **manifest** version too → owes a store upload |

`APP_VERSION` (in `app.py`) moves on every commit. The manifest version moves
**only** when `extension/` moves — that bump is the signal, and it is the only
signal, that a store submission is owed.

To check before pushing:

```
git diff --name-only HEAD | grep ^extension/
```

Nothing printed means nothing to submit.

### Three version numbers, and why

| Constant | Means | Bump when |
|---|---|---|
| `APP_VERSION` (`app.py`) | The dashboard | Every commit |
| `version` (`extension/manifest.json`) | The extension in this repo | `extension/` changes |
| `EXTENSION_STORE_VERSION` (`app.py`) | What the store has **approved** | A submission goes live |

`/api/ping` reports `EXTENSION_STORE_VERSION` to hosted browsers, because that
is the newest version a real user can actually install. Reporting the repo's
manifest instead is what once told every store user to sideload an update that
did not exist. Locally it reports the repo's manifest, which is correct there —
an unpacked extension adopts the folder on reload.

**So: after a store submission goes live, bump `EXTENSION_STORE_VERSION`.**
Forgetting it is harmless — nobody is nagged — it just means the popup won't
mention an update that Chrome is already installing silently anyway.

---

## Re-publishing an update

Package to upload: **`tallgrass-extension-vX.Y.zip`** — built from `extension/`
**unstamped**, manifest at the zip root. Do not upload the zip that
`/extension/download` serves: that one is stamped with the origin that served
it, which is right for a hand-loaded copy and wrong for the store.

Upload page: **https://chrome.google.com/webstore/devconsole/**
(the one-time $5 developer fee is already paid).

Expect another in-depth review on any update that touches permissions — broad
host permissions plus a Facebook content script is what made the first review
take three weeks.

---

## Store listing fields (copy-paste)

**Item name**
```
Tallgrass — by MacRandle Acres
```

> **The manifest's own `description` is also capped at 132 characters**, and
> the store rejects the whole upload if it is longer — "There was a problem
> uploading your file" plus a character count, before any listing field is
> even reached. `tests/run.sh` now checks this on every run. Keep it identical
> to the summary below.

**Summary** (short description, max 132 chars)
```
Ranks the Facebook group and profile posts you browse against each group's own median, so the real outliers stand out.
```

**Detailed description**
```
Tallgrass turns the Facebook groups and profiles you already read into a ranked feed of what actually broke out.

As you scroll a group, Tallgrass captures each post you pass — its author, text, reactions, comments, shares, and image — and sends it to your own Tallgrass dashboard. There, every post is scored against the median for the group it came from, so a post with 3,000 reactions in a big group and one with 300 in a small one are judged on the same footing: how far past normal, for that group, did this land?

What you get:
• A single feed of the genuine outliers across every group you follow
• Each post scored against its own group's baseline, not a global one
• Reactions, comments, and shares captured as shown — never guessed
• A one-click way to find any captured post back in its group

Tallgrass reads only the pages you are already viewing while signed in to your own Facebook account. It does not log in for you, does not touch groups you are not a member of, and sends captured posts only to your own dashboard — never to us, never to advertisers.

Tallgrass is a product of MacRandle Acres. It is not affiliated with, endorsed by, or sponsored by Meta or Facebook.
```

**Category:** Productivity
**Language:** English

**Single purpose** (required statement)
```
Tallgrass captures posts from the Facebook groups and profiles the user is viewing and ranks each one against the median engagement of its own group, in the user's private dashboard.
```

---

## Permission justifications (review form)

| Permission | Justification to paste |
|---|---|
| `storage` | Stores the user's dashboard address and account key locally so they aren't re-entered on every use. |
| `activeTab` | Reads the Facebook tab the user is actively viewing, only while capturing. |
| `alarms` | Schedules periodic retry of undelivered captures and a background version check. |
| Host: `*.facebook.com` | The content script reads post content (author, text, engagement, image) from the Facebook pages the user is already viewing, which is the only way this data can be captured — there is no Facebook API for group post engagement. |
| Host: `tallgrassapp.com`, `*.onrender.com`, `localhost`, `127.0.0.1` | Sends captured posts to the user's own Tallgrass dashboard — the hosted service at tallgrassapp.com, a Render deployment, or a local instance. |
| Optional host: `https://*/*`, `http://*/*` | **Requested at runtime only, with an explicit user click,** when a user connects a self-hosted dashboard on a custom domain. Never requested or used otherwise. The default flow uses only the scoped hosts above. |

---

## Privacy practices (data disclosure tab)

- **What is collected:** the content of Facebook posts the user actively browses past — author name, post text, reaction/comment/share counts, image URLs, timestamps — plus the user's own account key.
- **Chrome data-type checkboxes to select:** **"Website content."** (Author names are public post content, not user-provided PII.)
- **Where it goes:** only the user's own Tallgrass dashboard server. Nothing is sent to MacRandle Acres or any third party.
- **Not** sold, **not** used for advertising or creditworthiness, **not** transferred except to the user's own dashboard.
- Attest to all three required certifications (no sale of data, no use beyond single purpose, no creditworthiness use).

**Privacy policy URL** (required):
```
https://tallgrassapp.com/privacy
```

---

## Screenshots (you supply — at least 1, up to 5; 1280×800 or 640×400 PNG/JPG)

Capture these from the live dashboard, ideally at 1280×800:
1. The main **feed** showing several ranked posts with their multiples/badges.
2. A **post detail** page (score bar + engagement).
3. The **Capture** page / extension popup connected to the dashboard.
4. (Optional) A group page showing the median "meadow."

Tip: a clean browser window at 1280×800 with a few real captured posts reads best. No promo tiles are required to publish.

---

## Build the upload package

From the repo root, zip the extension contents (NOT the folder itself — `manifest.json` must sit at the zip root):

```bash
cd extension && zip -r ../tallgrass-extension.zip . -x '*.DS_Store'
```

Or on Windows PowerShell:

```powershell
Compress-Archive -Path extension\* -DestinationPath tallgrass-extension.zip -Force
```

Verify the zip has `manifest.json` at its top level and includes the `icons/` folder.

---

## Submit checklist

- [ ] $5 developer account registered
- [ ] `tallgrass-extension-vX.Y.zip` uploaded (manifest at root, icons included)
- [ ] Name, summary, detailed description filled from above
- [ ] Category = Productivity, Language = English
- [ ] Single-purpose statement pasted
- [ ] Each permission justified from the table above
- [ ] Privacy policy URL set; "Website content" disclosed; 3 certifications attested
- [ ] ≥1 screenshot at 1280×800 uploaded
- [ ] Submit for review (first review typically a few business days)
