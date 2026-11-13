# Chrome Web Store listing for extension 31.0

Paste these into the dashboard when uploading `tallgrass-extension-v31.0.zip`.
The live listing is still 30.1. Do not change `EXTENSION_STORE_VERSION` in
`app.py` until this package is approved. `/api/ping` must keep reporting 30.1
until then.

Build the zip from the repo root:

```sh
sh extension/package_store_zip.sh
```

`manifest.json` is at the archive root. The zip is not stamped with a
dashboard origin. Do not upload the file from `/extension/download`.

The manifest `description` and the short description below are the same
string (98 characters, store limit 132).

## Short description

```
Ranks Facebook posts against each group's own median, then helps you remix and write the next one.
```

## Full description

```
Tallgrass ranks the Facebook posts you already see against the median of each group, page, or profile. A quiet group's runaway hit stops hiding behind a big group's ordinary day. Then it helps you remix that winner and write the next post.

What you get:
- One feed of the posts that actually broke out, across the groups you follow
- Each post scored against its own group's median, not a global one
- Remix drafts that reuse the mechanic that made a winner work
- Sage, for questions answered from the posts you captured

Tallgrass reads only what you can already see, while you are signed in to your own Facebook account. It does not log in for you, it does not reach a group you are not in, and it never posts, comments, likes, or sends a message for you.

Remix and Sage use your own Claude or OpenAI key.

Tallgrass is a product of MacRandle Acres. It is not affiliated with, endorsed by, or sponsored by Meta or Facebook.
```

## Single purpose

```
Tallgrass reads Facebook posts the user is already viewing and ranks each one against the median of its own group, in the user's private dashboard. Remix and Sage draft from those posts with the user's own AI key. It never posts for the user.
```

## What this package is

Version 31.0. No Messenger content script (facebook.com/messages is excluded).
No comment-saving button and no reply-drafting UI. Permissions are unchanged
from the live package: storage, activeTab, alarms, and the same host list.
The permission justifications in the repo-root `STORE_LISTING.md` still apply.

Category: Productivity. Language: English.

Privacy policy URL, unchanged until you switch the draft on:

```
https://tallgrassapp.com/privacy
```

After 31.0 is approved, follow `extension/PRIVACY_AFTER_31.md` before you
point the listing at a policy that no longer mentions Messenger.
