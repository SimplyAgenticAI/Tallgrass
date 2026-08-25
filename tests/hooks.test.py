"""Hooks must come from evidence, or say that they don't.

The whole point of extracting hooks from the operator's own winning posts is
that the number behind them is real. That only holds if a hook without a
number can never look like one with a number — so these tests care most about
the boundary: what gets in, what stays out, and what happens when a group has
taught us nothing.

Run: python tests/hooks.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import hooks

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def scored(body, multiple=5.0, has_baseline=True, pid=1, from_image=0):
    return {
        "id": pid, "body": body, "outlier_multiple": multiple,
        "has_baseline": has_baseline, "body_from_image": from_image,
        "source_name": "A Group",
    }


def main():
    print("the opening line is the first thing a reader sees")
    check("a short first line is the hook itself",
          hooks.opening_line("Nobody talks about this part.\n\nSo here it is."),
          "Nobody talks about this part.")
    check("prose is cut at the first sentence",
          hooks.opening_line("I stopped chasing referrals last year. Then this happened."),
          "I stopped chasing referrals last year.")
    check("a post with no body has no hook", hooks.opening_line(""), None)
    check("  nor does whitespace", hooks.opening_line("   \n  "), None)
    check("a fragment is not an opening", hooks.opening_line("Wow"), None)
    # A body that survived caption cleaning could still be a bare token.
    check("a token is not an opening",
          hooks.opening_line("madgz4okPuJ2eku32l0HaoXRzutZH"), None)

    print()
    print("only posts that actually beat their group get copied")
    check("a typical post contributes nothing",
          hooks.from_posts([scored("This is a perfectly ordinary opening line.",
                                   multiple=1.0)]), [])
    check("nor does one just under the floor",
          hooks.from_posts([scored("This is a perfectly ordinary opening line.",
                                   multiple=1.4)]), [])
    check("one above it does",
          len(hooks.from_posts([scored("This is a perfectly ordinary opening line.",
                                       multiple=1.5)])), 1)

    print()
    print("a hook with no number behind it never gets in")
    # An unscored post has no multiple, so its opening line is evidence of
    # nothing — which is the whole thing this module refuses to fake.
    unscored = scored("An opening line from a post nobody could score.",
                      multiple=None, has_baseline=False)
    check("an unscored post is skipped", hooks.from_posts([unscored]), [])
    check("even when it has a multiple attached by accident",
          hooks.from_posts([scored("An opening line with a stale multiple.",
                                   multiple=40.0, has_baseline=False)]), [])

    print()
    print("words read out of a graphic are not an opening anyone typed")
    check("a hook from an image is skipped",
          hooks.from_posts([scored("Text that was baked into a picture.",
                                   from_image=1)]), [])

    print()
    print("the best performer leads")
    ranked = hooks.from_posts([
        scored("The third best opening line in this group.", multiple=2.0, pid=1),
        scored("The very best opening line in this group.", multiple=12.4, pid=2),
        scored("The second best opening line in this group.", multiple=6.0, pid=3),
    ])
    check("three hooks", len(ranked), 3)
    check("highest multiple first", ranked[0]["multiple"], 12.4)
    check("  and it carries the post it came from", ranked[0]["post_id"], 2)
    check("descending", [h["multiple"] for h in ranked], [12.4, 6.0, 2.0])

    print()
    print("the same opening twice is one hook")
    same = hooks.from_posts([
        scored("The identical opening line, posted twice.", multiple=9.0, pid=1),
        scored("the identical opening line, posted twice.", multiple=3.0, pid=2),
    ])
    check("deduplicated regardless of case", len(same), 1)
    check("  keeping the better performer", same[0]["multiple"], 9.0)

    print()
    print("shapes are named only when they are obvious")
    def shape(text):
        return hooks.from_posts([scored(text, multiple=5.0)])[0]["shape"]

    check("a question", shape("Have you ever wondered why this happens?"), "question")
    check("a how-to", shape("How I stopped losing deals at the last minute."), "how-to")
    check("a list", shape("3 things I stopped doing to win more work."), "list")
    check("a warning", shape("Before you sign anything, read this part."), "warning")
    check("a story", shape("Three years ago I almost closed the business."),
          "story")
    check("contrarian", shape("Everyone repeats this advice and it is wrong."),
          "contrarian")
    check("anything else is just an opening",
          shape("We finished the roof on the north barn today."), "opening")

    print()
    print("a group that has taught us nothing says so")
    fallback = hooks.for_source([])
    check("it is marked generic", fallback["generic"], True)
    check("hooks are still offered", len(fallback["hooks"]) > 0, True)
    check("every one is flagged",
          all(h["generic"] for h in fallback["hooks"]), True)
    check("and none of them claims a multiple",
          all(h["multiple"] is None for h in fallback["hooks"]), True)

    print()
    print("evidence and archetypes are never mixed")
    # A list that is half real and half invented invites the reader to treat
    # the invented half as measured too.
    real = hooks.for_source([scored("A genuinely strong opening line here.",
                                    multiple=8.0)])
    check("real hooks are not marked generic", real["generic"], False)
    check("no archetype is appended",
          any(h["generic"] for h in real["hooks"]), False)
    check("and every hook carries its number",
          all(h["multiple"] is not None for h in real["hooks"]), True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("every hook shown is either measured or marked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
