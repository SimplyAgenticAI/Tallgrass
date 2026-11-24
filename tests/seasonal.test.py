"""The season follows the Eastern date, and a switch can override it.

Halloween is 15-31 October. Thanksgiving runs from 1 November through Cyber
Monday, the fourth Thursday plus four days, which is 30 November in 2026 and
29 November in 2027. Winter is the next morning through 1 January. Every
other day is the ordinary theme.

SEASONAL_THEME=off is a kill switch. A theme name forces that theme. ?theme=
previews one request and does not override the kill switch.

Run: python tests/seasonal.test.py
"""
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import seasonal  # noqa: E402

FAILURES = []


def check(name, got, want=True):
    ok = got == want
    print(("  ok   " if ok else " FAIL  ") + name +
          ("" if ok else "   got %r, want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def main():
    print("the windows, by the Eastern calendar")
    cases = (
        (date(2026, 10, 14), "default"),
        (date(2026, 10, 15), "halloween"),
        (date(2026, 10, 31), "halloween"),
        (date(2026, 11, 1), "thanksgiving"),
        (date(2026, 11, 26), "thanksgiving"),
        (date(2026, 11, 30), "thanksgiving"),
        (date(2026, 12, 1), "winter"),
        (date(2026, 12, 31), "winter"),
        (date(2027, 1, 1), "winter"),
        (date(2027, 1, 2), "default"),
        (date(2027, 6, 15), "default"),
        (date(2027, 10, 14), "default"),
        (date(2027, 10, 15), "halloween"),
        (date(2027, 11, 1), "thanksgiving"),
        (date(2027, 11, 25), "thanksgiving"),
        (date(2027, 11, 29), "thanksgiving"),
        (date(2027, 11, 30), "winter"),
        (date(2027, 12, 25), "winter"),
        (date(2028, 1, 1), "winter"),
        (date(2028, 1, 2), "default"),
        # Cyber Monday can land in December. 2024's fourth Thursday is the 28th.
        (date(2024, 12, 2), "thanksgiving"),
        (date(2024, 12, 3), "winter"),
    )
    for day, want in cases:
        check("%s is %s" % (day.isoformat(), want), seasonal.theme_for_date(day), want)

    print()
    print("the clock is Eastern, including across midnight UTC")
    utc = timezone.utc
    # 03:30 UTC on 1 Nov 2026 is still 23:30 the previous evening in New York.
    check("just before midnight ET is still halloween",
          seasonal.current_theme(now=datetime(2026, 11, 1, 3, 30, tzinfo=utc),
                                  environ={}),
          "halloween")
    check("midnight ET on 1 Nov is thanksgiving",
          seasonal.current_theme(now=datetime(2026, 11, 1, 4, 0, tzinfo=utc),
                                  environ={}),
          "thanksgiving")
    check("23:59 ET on 1 Jan is still winter",
          seasonal.current_theme(now=datetime(2027, 1, 2, 4, 59, tzinfo=utc),
                                  environ={}),
          "winter")
    check("midnight ET on 2 Jan is default",
          seasonal.current_theme(now=datetime(2027, 1, 2, 5, 0, tzinfo=utc),
                                  environ={}),
          "default")
    check("a naive datetime is read as Eastern",
          seasonal.current_theme(now=datetime(2026, 10, 15, 0, 30), environ={}),
          "halloween")

    print()
    print("overrides: kill switch, force, and a one-request preview")
    halloween = datetime(2026, 10, 31, 12, 0, tzinfo=utc)
    check("unset follows the date",
          seasonal.current_theme(now=halloween, environ={}), "halloween")
    check("auto follows the date",
          seasonal.current_theme(now=halloween, environ={"SEASONAL_THEME": "auto"}),
          "halloween")
    check("an unknown mode follows the date",
          seasonal.current_theme(now=halloween, environ={"SEASONAL_THEME": "party"}),
          "halloween")
    check("off is default in season",
          seasonal.current_theme(now=halloween, environ={"SEASONAL_THEME": "off"}),
          "default")
    check("off ignores a preview",
          seasonal.current_theme(now=halloween, preview="winter",
                                  environ={"SEASONAL_THEME": "OFF"}),
          "default")
    check("a theme name forces it",
          seasonal.current_theme(now=halloween, environ={"SEASONAL_THEME": " Winter "}),
          "winter")
    check("forcing default stays default in season",
          seasonal.current_theme(now=halloween, environ={"SEASONAL_THEME": "default"}),
          "default")
    check("a preview beats the date",
          seasonal.current_theme(now=halloween, preview="thanksgiving", environ={}),
          "thanksgiving")
    check("a preview beats a forced theme",
          seasonal.current_theme(now=halloween, preview="Default",
                                  environ={"SEASONAL_THEME": "winter"}),
          "default")
    check("an unknown preview is ignored",
          seasonal.current_theme(now=halloween, preview="christmas", environ={}),
          "halloween")
    check("a blank preview is ignored",
          seasonal.current_theme(now=halloween, preview="  ",
                                  environ={"SEASONAL_THEME": "winter"}),
          "winter")

    print()
    print("the sheet only tints the accent, the glow, and the card edge")
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "static", "css", "seasonal.css")
    css = open(css_path, encoding="utf-8").read()
    for token in ("#f59e42", "rgba(245, 158, 66, 0.42)",
                  "#e3b65c", "rgba(227, 182, 92, 0.40)",
                  "#a7f3d0", "rgba(186, 230, 253, 0.38)",
                  "#e0a84f", "#e0f2fe"):
        check("names %s" % token, token in css, True)
    check("the promo edge stays gold", "rgba(217, 180, 95, 0.62)" in css, True)
    check("the promo glow stays gold", "rgba(217, 180, 95, 0.32)" in css, True)
    check("it never sets a fill", "background" not in css.lower(), True)
    for word in ("meadow", "canvas", "particle", "field.js"):
        check("it does not mention %s" % word, word not in css, True)

    print()
    print("a page renders the theme, and only that request's preview")
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["APP_SECRET"] = "seasonal-test-secret"
    os.environ.pop("SEASONAL_THEME", None)
    import app as appmod  # noqa: E402

    client = appmod.app.test_client()

    def page(path):
        return client.get(path).get_data(as_text=True)

    home = page("/?theme=halloween")
    check("the document element carries the preview",
          '<html lang="en" data-theme="halloween">' in home, True)
    check("seasonal.css is linked after the base sheet",
          home.find("outlier.css") != -1 and home.find("outlier.css") < home.find("seasonal.css"),
          True)
    check("the pumpkin is on the mark", "season-pumpkin" in home, True)
    check("the other charms are not", "season-leaf" not in home and "season-flake" not in home, True)
    check("the headline word is unchanged", "broke out" in home, True)

    plain = page("/?theme=default")
    check("default is an explicit theme", '<html lang="en" data-theme="default">' in plain, True)
    check("default adds no charm", "season-symbol" not in plain, True)

    os.environ["SEASONAL_THEME"] = "winter"
    forced = page("/")
    check("a forced theme is what the page renders",
          '<html lang="en" data-theme="winter">' in forced, True)
    check("and its snowflake", "season-flake" in forced, True)
    preview = page("/?theme=halloween")
    check("the query wins for that request",
          '<html lang="en" data-theme="halloween">' in preview, True)

    os.environ["SEASONAL_THEME"] = "off"
    killed = page("/?theme=winter")
    check("off stays default even with a query",
          '<html lang="en" data-theme="default">' in killed, True)
    check("and draws no charm", "season-symbol" not in killed, True)

    os.environ.pop("SEASONAL_THEME", None)
    login = page("/login?theme=thanksgiving")
    check("a standalone page carries it too",
          '<html lang="en" data-theme="thanksgiving">' in login, True)
    check("including the leaf", "season-leaf" in login, True)

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("the season changes with the date, and only then")
    return 0


if __name__ == "__main__":
    sys.exit(main())
