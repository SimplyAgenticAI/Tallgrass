"""The palette, measured rather than admired.

The app was reported as dark and muted, and the obvious reading — the text is
too dim — was wrong: every text colour passed WCAG AA comfortably (body 16:1,
secondary 9:1, fine print 6:1). What was muted was the SURFACES. A card
flattened to a luminance of 0.011 against a page at 0.007, so it was 1.5x
brighter than the thing it sat on and read as part of it.

Lifting a surface is the fix and also the risk: it eats contrast from every bit
of text on it. This file does the arithmetic so nobody has to trust an eye.

  lift      a card must be clearly brighter than the page, or it is not a card
  legible   every text colour on every surface stays at or above AA
  sharp     the surfaces that were frosted stay unfrosted: a blur across a
            sticky bar or a card costs a GPU pass per scroll frame and softens
            the very content being read

Run: python tests/contrast.test.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSS = os.path.join(HERE, "..", "static", "css", "outlier.css")

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def srgb(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(colour):
    r, g, b = colour
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)


def ratio(front, back):
    a, b = luminance(front), luminance(back)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def rgb(value):
    """#rrggbb or rgba(r, g, b, a) — the alpha is reported separately."""
    value = value.strip()
    hexmatch = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if hexmatch:
        h = hexmatch.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)), 1.0
    rgba = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
    if rgba:
        parts = [int(rgba.group(i)) for i in (1, 2, 3)]
        return tuple(parts), float(rgba.group(4) or 1)
    return None, None


def flatten(front, alpha, back):
    return tuple(round(front[i] * alpha + back[i] * (1 - alpha)) for i in range(3))


def tokens(css):
    """The :root custom properties, as {name: raw value}."""
    root = css[css.index(":root"):css.index("}", css.index(":root"))]
    found = {}
    for name, value in re.findall(r"(--[a-z-]+)\s*:\s*([^;]+);", root):
        found[name] = value.strip()
    return found


def main():
    css = open(CSS, encoding="utf-8").read()
    t = tokens(css)

    # The page itself: the mid stop of the ambient gradient is what most of a
    # long page actually sits on.
    page, _ = rgb("#061810")

    print("the surfaces lift off the page")
    for token, name, least in (("--glass", "a card", 2.5),
                               ("--glass-solid", "a floating surface", 2.5)):
        colour, alpha = rgb(t[token])
        check("%s is a flat value, not a guess" % token, colour is not None, True)
        if colour is None:
            continue
        surface = colour if alpha >= 0.999 else flatten(colour, alpha, page)
        lift = luminance(surface) / luminance(page)
        check("  %s is at least %.1fx the page (%.1fx)" % (name, least, lift),
              lift >= least, True)

    card, card_alpha = rgb(t["--glass"])
    card = card if card_alpha >= 0.999 else flatten(card, card_alpha, page)
    float_surface, float_alpha = rgb(t["--glass-solid"])
    float_surface = (float_surface if float_alpha >= 0.999
                     else flatten(float_surface, float_alpha, page))
    check("a floating surface is brighter than a card, not darker",
          luminance(float_surface) >= luminance(card), True)

    print()
    print("and every colour on them is still legible")
    # The sticky bars are their own value, not a token: read it off .topbar.
    # The LAST matching rule, not the first: the bar's colour is set in the
    # layout block and then overridden further down the file, so reading the
    # first one measured a value the browser never uses.
    bar_rules = re.findall(r"\.topbar\s*\{[^}]*?background:\s*([^;]+);", css)
    bar, bar_alpha = rgb(bar_rules[-1]) if bar_rules else (None, None)
    surfaces = [("a card", card), ("a modal or toast", float_surface)]
    if bar is not None:
        surfaces.append(("the top bar",
                         bar if bar_alpha >= 0.999 else flatten(bar, bar_alpha, page)))

    text_tokens = ["--text", "--text-muted", "--text-faint",
                   "--emerald-bright", "--emerald", "--gold", "--ember"]
    worst = (99, "", "")
    for where, surface in surfaces:
        for token in text_tokens:
            colour, alpha = rgb(t[token])
            if colour is None:
                continue
            front = colour if alpha >= 0.999 else flatten(colour, alpha, surface)
            r = ratio(front, surface)
            if r < worst[0]:
                worst = (r, token, where)
            check("  %s on %s (%.2f:1)" % (token, where, r), r >= 4.5, True)
    print("  worst pair anywhere: %s on %s at %.2f:1" % (worst[1], worst[2], worst[0]))

    print()
    print("what sits ON a card is a well, not a hole")
    # The badge disc, the score groove and the illustration chips were all tuned
    # against a near-black card. Lifting the card turned each of them into a gap
    # punched through it. They have to be DARKER than the card (so they read as
    # recessed) and brighter than the page (so they do not read as a hole).
    sunken = {
        ".post-badge": r"\.post-badge\s*\{[^}]*?radial-gradient\(circle at 50% 45%,\s*([^,]+),",
        ".scale-track": r"\.scale-track\s*\{[^}]*?background:\s*([^;]+);",
    }
    for selector, pattern in sunken.items():
        found = re.search(pattern, css)
        check("  %s has a flat value" % selector, found is not None, True)
        if not found:
            continue
        colour, alpha = rgb(found.group(1))
        if colour is None:
            check("  %s parses" % selector, False, True)
            continue
        well = colour if alpha >= 0.999 else flatten(colour, alpha, card)
        check("  %s is recessed below the card" % selector,
              luminance(well) < luminance(card), True)
        check("    but still above the page" % (), luminance(well) > luminance(page), True)

    print()
    print("the things that were frosted stay unfrosted")
    # Blur across a sticky bar or a card costs a GPU pass on every scroll frame
    # and softens the content being scrolled. A true overlay may blur again one
    # day; these three may not.
    for selector in (".topbar", ".post-card", ".glass"):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        body = block.group(1) if block else ""
        check("  %s does not blur" % selector, "backdrop-filter" in body, False)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("lifted surfaces, legible text, no blur where it costs the most")
    return 0


if __name__ == "__main__":
    sys.exit(main())
