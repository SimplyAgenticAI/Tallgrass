"""What the dragonfly is allowed to say.

It is a friendly thing in the corner of every page, which makes it the easiest
place in the app to start lying — a cheerful hint about "your best post" to
somebody who has captured nothing, or a number that came from nowhere. Same rule
as hooks.py and patterns.py: a claim about their data only when the data is
there.

  where they are  somebody with nothing captured is told how to capture, not
                  how to pick between winners
  real numbers    a multiple is only mentioned when the meadow has one, and it
                  is the one the meadow is drawn from
  the page        a tip about the page they are on comes before general advice
  cheap           this runs on every page load, so the facts it uses are ones
                  the page already had
  no repeats      the same sentence never appears twice in one list

Run: python tests/tips.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import outliers  # noqa: E402
import tips      # noqa: E402

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


SOMEBODY = {"id": 1}


def main():
    print("nobody signed in")
    out = tips.for_page("feed", [], None)
    check("there is still something to say", len(out) > 1, True)
    check("  and none of it claims to know them",
          any("your" in t.lower() for t in out), False)

    print()
    print("signed in, nothing captured")
    out = tips.for_page("feed", [], SOMEBODY, {"posts": 0})
    check("the first thing said is how to capture",
          "press Start" in out[0], True)
    check("  not how to choose between winners",
          any("28×" in t for t in out[:1]), False)
    check("  and no multiple is invented",
          any("× the median of its group" in t for t in out), False)

    print()
    print("captured, but nothing scoreable yet")
    out = tips.for_page("groups", [], SOMEBODY, {"posts": 40})
    check("it explains what a baseline needs", str(outliers.MIN_SAMPLE) in out[0], True)
    check("  and still no multiple", any("its group" in t for t in out[:1]), False)

    print()
    print("scores exist, so it may talk about them")
    out = tips.for_page("feed", [2.1, 14.63, 3.4], SOMEBODY, {"posts": 300})
    check("it leads with their own best", "14.6×" in out[0], True)
    check("  rounded, not raw", "14.63" in out[0], False)

    # A meadow of ordinary posts is not a brag.
    out = tips.for_page("feed", [1.1, 0.9, 1.0], SOMEBODY, {"posts": 300})
    check("a best of 1.1× is not announced as a win",
          any("did 1.1×" in t for t in out), False)
    check("  but there is still advice", len(out) > 2, True)

    print()
    print("people waiting on a reply come before craft")
    out = tips.for_page("feed", [9.0, 2.0], SOMEBODY, {"posts": 300, "waiting": 3})
    check("it mentions them", any("3 people are waiting" in t for t in out), True)
    check("  before the general advice",
          [i for i, t in enumerate(out) if "waiting" in t][0] <
          [i for i, t in enumerate(out) if "plausibly" in t][0], True)
    one = tips.for_page("feed", [9.0], SOMEBODY, {"posts": 300, "waiting": 1})
    check("and one person is singular", any("1 person is waiting" in t for t in one), True)

    print()
    print("the page they are on gets a word in")
    for page, must in (("groups", "Needs more data"), ("today", "ever sent for you"),
                       ("write", "opening line"), ("results", "same medians")):
        out = tips.for_page(page, [9.0], SOMEBODY, {"posts": 300})
        check("  %s" % page, any(must in t for t in out), True)
    out = tips.for_page("nowhere-in-particular", [9.0], SOMEBODY, {"posts": 300})
    check("an unknown page still gets craft advice", len(out) > 2, True)

    print()
    print("the list itself")
    out = tips.for_page("feed", [9.0, 2.0], SOMEBODY, {"posts": 300, "waiting": 2})
    check("nothing repeats", len(out), len(set(out)))
    check("it is capped", len(out) <= 8, True)
    # A count may legitimately open a line ("3 people are waiting on a reply").
    check("every line is a real sentence",
          all(len(t) > 20 and (t[0].isupper() or t[0].isdigit()) and t.endswith(".")
              for t in out), True)
    check("nothing arrives with broken whitespace",
          all("  " not in t and "\\n" not in t for t in out), True)

    print()
    print("missing counts are not guessed at")
    # The page failed to get a count; that must not read as "zero posts".
    out = tips.for_page("feed", [9.0, 2.0], SOMEBODY, {})
    check("no 'nothing captured' claim without knowing",
          any("press Start" in t for t in out), False)
    check("  and the score it can see is still used", "9.0×" in out[0], True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("it only says what is true of the person reading it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
