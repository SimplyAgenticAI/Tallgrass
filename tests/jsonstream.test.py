"""Reading finished posts out of JSON that is still arriving.

The scanner exists so the Write page can show one finished post at a time
instead of a spinner. That only works if it is exactly right about where an
item ends — and post copy is full of the things that break naive brace
counting: quotes, braces inside strings, escaped quotes, newlines.

An item shown twice, or shown half-written, is worse than showing nothing.

Run: python tests/jsonstream.test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import jsonstream

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def drip(text, size=7):
    """The stream as the network actually delivers it: arbitrary fragments."""
    scanner = jsonstream.ArrayScanner("variants")
    out = []
    for i in range(0, len(text), size):
        out.extend(scanner.feed(text[i:i + size]).take())
    return out


def main():
    print("items appear one at a time, in order")
    doc = ('{"why_it_worked": "It named a number.", "variants": ['
           '{"angle": "one", "body": "first"},'
           '{"angle": "two", "body": "second"},'
           '{"angle": "three", "body": "third"}]}')
    items = drip(doc)
    check("all three found", len(items), 3)
    check("in the order written",
          [i["angle"] for i in items], ["one", "two", "three"])
    check("with their copy intact", items[1]["body"], "second")

    print()
    print("an item is handed over exactly once")
    scanner = jsonstream.ArrayScanner("variants")
    scanner.feed('{"variants": [{"angle": "one", "body": "first"}')
    first = scanner.take()
    check("the finished one is returned", len(first), 1)
    check("and taking again returns nothing", scanner.take(), [])
    scanner.feed(', {"angle": "two", "body": "second"}]}')
    second = scanner.take()
    check("only the new one arrives", len(second), 1)
    check("  and it is the right one", second[0]["angle"], "two")

    print()
    print("a half-written item is not handed over early")
    scanner = jsonstream.ArrayScanner("variants")
    scanner.feed('{"variants": [{"angle": "one", "bo')
    check("nothing yet", scanner.take(), [])
    scanner.feed('dy": "the whole post"}')
    done = scanner.take()
    check("only once it closes", len(done), 1)
    check("  and it is complete", done[0]["body"], "the whole post")

    print()
    print("braces inside post copy do not end an item")
    # Real copy contains all of this. Counting braces without tracking strings
    # would cut the first post in half and emit it as two.
    doc = ('{"variants": ['
           '{"angle": "one", "body": "Use {curly braces} in your CTA }} like this"},'
           '{"angle": "two", "body": "plain"}]}')
    items = drip(doc, size=3)
    check("two items, not four", len(items), 2)
    check("the braces survive in the copy",
          items[0]["body"], "Use {curly braces} in your CTA }} like this")

    print()
    print("escaped quotes do not end a string")
    doc = ('{"variants": ['
           '{"angle": "one", "body": "She said \\"do the work\\" and left"},'
           '{"angle": "two", "body": "plain"}]}')
    items = drip(doc, size=5)
    check("both items found", len(items), 2)
    check("the quotes are preserved",
          items[0]["body"], 'She said "do the work" and left')

    print()
    print("newlines in copy are fine")
    doc = ('{"variants": [{"angle": "one", "body": "Line one.\\n\\nLine two."}]}')
    items = drip(doc, size=4)
    check("one item", len(items), 1)
    check("the break survives", items[0]["body"], "Line one.\n\nLine two.")

    print()
    print("a different array is not mistaken for this one")
    doc = ('{"other": [{"nope": 1}], "variants": [{"angle": "real"}]}')
    items = drip(doc, size=6)
    check("only the named array is read", len(items), 1)
    check("  and it is the right one", items[0]["angle"], "real")

    print()
    print("the ideas endpoint uses a different key")
    doc = '{"read": "what wins", "ideas": [{"hook": "h", "body": "b"}]}'
    scanner = jsonstream.ArrayScanner("ideas")
    got = scanner.feed(doc).take()
    check("it reads that one instead", len(got), 1)
    check("  correctly", got[0]["hook"], "h")

    print()
    print("nothing is invented from junk")
    scanner = jsonstream.ArrayScanner("variants")
    check("no array, no items", scanner.feed("total nonsense").take(), [])
    scanner = jsonstream.ArrayScanner("variants")
    check("an empty array yields nothing",
          scanner.feed('{"variants": []}').take(), [])

    print()
    print("the lead sentence is readable before the posts are")
    partial = '{"why_it_worked": "It opened with a real number.", "variants": [{"an'
    check("it is found once closed",
          jsonstream.leading_string(partial, "why_it_worked"),
          "It opened with a real number.")
    check("but not while still being written",
          jsonstream.leading_string('{"why_it_worked": "It opened wi',
                                    "why_it_worked"), None)
    check("an escaped quote inside it is handled",
          jsonstream.leading_string('{"read": "the \\"why\\" matters", "ideas": [',
                                    "read"),
          'the "why" matters')
    check("a missing key is None",
          jsonstream.leading_string('{"variants": []}', "why_it_worked"), None)

    print()
    print("whatever the chunk size, the result is the same")
    doc = ('{"why_it_worked": "x", "variants": ['
           '{"angle": "a", "body": "one"},{"angle": "b", "body": "two"},'
           '{"angle": "c", "body": "three"}]}')
    for size in (1, 2, 3, 11, 50, 5000):
        items = drip(doc, size=size)
        check("chunked at %d" % size,
              [i["angle"] for i in items], ["a", "b", "c"])

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("finished posts arrive whole, once, in order")
    return 0


if __name__ == "__main__":
    sys.exit(main())
