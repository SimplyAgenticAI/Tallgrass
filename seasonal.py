"""Seasonal color for the accent, the button glow, and the mark.

The page stays the one it is. Three things take a season, and only while the
date says so: the highlighted word, the glow under a primary button, and a
small symbol on the logo. The meadow, the copy, and the Black Friday card are
not part of this.

Windows are America/New_York, recomputed every year:

  halloween      15 October through 31 October
  thanksgiving   1 November through Cyber Monday, the fourth Thursday in
                 November plus four days. That Monday can fall in December.
  winter         the day after Cyber Monday through 1 January. Frost only:
                 no holiday and no religious mark.
  default        every other day

SEASONAL_THEME selects a mode:

  auto           follow the date. This is the default when the variable is unset.
  off            kill switch. Always default, and a ?theme= preview is ignored.
  <theme>        force that theme until the variable changes.

?theme=halloween|thanksgiving|winter|default previews that one request. It
does not stick, and it does not override the kill switch.
"""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

THEMES = ("halloween", "thanksgiving", "winter", "default")


def _nth_weekday(year, month, weekday, n):
    """The nth weekday in a month. weekday matches date.weekday, Monday 0."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def cyber_monday(year):
    """The Monday four days after the fourth Thursday in November."""
    return _nth_weekday(year, 11, 3, 4) + timedelta(days=4)


def theme_for_date(day):
    """The theme for a calendar date already in Eastern Time."""
    if day.month == 10 and 15 <= day.day <= 31:
        return "halloween"
    # 1 January is the last day of the winter that started after the previous
    # Cyber Monday, so it is decided before this year's November window.
    if (day.month, day.day) == (1, 1):
        return "winter"
    monday = cyber_monday(day.year)
    if date(day.year, 11, 1) <= day <= monday:
        return "thanksgiving"
    # The day after Cyber Monday through the end of December. 1 January of the
    # next year is handled above.
    if monday + timedelta(days=1) <= day <= date(day.year, 12, 31):
        return "winter"
    return "default"


def _as_et(now):
    if now is None:
        return datetime.now(ET)
    if now.tzinfo is None:
        return now.replace(tzinfo=ET)
    return now.astimezone(ET)


def current_theme(now=None, preview=None, environ=None):
    """The theme for this request.

    now is a datetime. A naive one is read as Eastern. preview is the raw
    ?theme= value. environ defaults to the process environment so a test can
    pass a dict and a running server reads SEASONAL_THEME on each request.
    """
    env = os.environ if environ is None else environ
    mode = str(env.get("SEASONAL_THEME") or "auto").strip().lower()
    if mode == "off":
        return "default"
    choice = str(preview or "").strip().lower()
    if choice in THEMES:
        return choice
    if mode in THEMES:
        return mode
    return theme_for_date(_as_et(now).date())
