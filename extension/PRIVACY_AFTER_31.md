# Privacy policy draft for after extension 31.0 is approved

Do not publish this while the Chrome Web Store listing is still 30.1.
That build still saves comments and reads Messenger, and the live policy
has to describe it. `/privacy` stays on the current text until you flip
the switch below.

## Switch

In `app.py`:

1. Set `PRIVACY_EXTENSION_31 = True`.
2. Leave `LEGAL_UPDATED` where it is unless the terms change too.
   The privacy page then shows `PRIVACY_31_UPDATED` (`13 November 2026`).
   Change that constant first if approval lands on a different day.

The replacement body is `templates/_privacy_31.html`. With the flag off,
that file is not rendered. With the flag on, it replaces the Messenger
section, the comment-saving section, and the sentences that point at them.

## What the draft removes

- "Comments on your posts" (the Save comments button).
- The Messenger section: unanswered chats, suggest a message, AI sorting.
- Dashboard storage of Messenger chats and of saved comments.
- AI wording for Suggest reply, Suggest a message, and comment sorting.

## What the draft says instead

The extension collects a post's text, author, reaction, comment and share
counts, link, type, timestamp, image address, and the group, page or
profile on screen, and only while a scan is running.

It does not collect private messages. It does not run on Messenger. It
does not read comment text. A scan reads the comment count only. It never
posts, comments, likes, or sends a message.

Remix and Sage send captured posts to Anthropic or OpenAI when you use
them. They use your own Claude or OpenAI key unless the server is
configured with one. If you never use them, captured posts are not sent
to an AI provider.

Payments, cookies, deletion, and the rest of the policy are unchanged.
