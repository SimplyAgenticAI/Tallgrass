"""Read finished items out of JSON that is still being written.

Both writing features ask the model for one JSON object — a lead sentence plus
an array of variants. Streaming its raw tokens to a browser shows somebody
their post arriving as `{"why_it_worked": "Th`, which is worse than a spinner.

But the array is written in order, so the first variant is complete long
before the last one starts. This scans the text as it accumulates and hands
back each item the moment its closing brace arrives, which is what lets the
page fill in one finished post at a time instead of all at once at the end.

Nothing here is a JSON parser. It finds the boundaries of each element and
gives them to json.loads, so anything malformed is rejected by the real
parser rather than half-understood by this one.
"""

import json


class ArrayScanner:
    """Yields complete objects from inside one named array as text arrives.

    Feed it whatever the stream produced; call take() for whatever finished.
    """

    def __init__(self, key):
        self.key = key
        self._buffer = ""
        self._cursor = None      # where the array's contents begin
        self._ready = []

    def feed(self, chunk):
        self._buffer += chunk or ""
        if self._cursor is None:
            self._locate_array()
        if self._cursor is not None:
            self._scan()
        return self

    def take(self):
        """Everything completed since the last call. Never repeats an item."""
        done, self._ready = self._ready, []
        return done

    # ------------------------------------------------------------ internals

    def _locate_array(self):
        marker = '"%s"' % self.key
        at = self._buffer.find(marker)
        if at == -1:
            return
        opening = self._buffer.find("[", at + len(marker))
        if opening == -1:
            return
        self._cursor = opening + 1

    def _scan(self):
        """Pull out every balanced {...} from the cursor onward.

        Braces inside strings do not count, and a brace escaped inside a
        string does not close anything — which is the whole reason this cannot
        be done by counting characters alone. Post copy is full of both.
        """
        i = self._cursor
        depth = 0
        start = None
        in_string = False
        escaped = False
        text = self._buffer

        while i < len(text):
            ch = text[i]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    piece = text[start:i + 1]
                    try:
                        self._ready.append(json.loads(piece))
                    except ValueError:
                        # Not usable yet or not usable at all. Either way the
                        # complete response is parsed again at the end, so a
                        # miss here costs nothing but an early preview.
                        pass
                    start = None
                    # Only advance past what has been consumed, so a partial
                    # object at the tail is rescanned when more text arrives.
                    self._cursor = i + 1
            elif ch == "]" and depth == 0:
                # The array closed; nothing further belongs to it.
                self._cursor = i
                return

            i += 1


def leading_string(text, key):
    """The value of a top-level string field, as soon as it is complete.

    The lead sentence is written before the array, so it can be shown while
    the posts themselves are still arriving.
    """
    marker = '"%s"' % key
    at = text.find(marker)
    if at == -1:
        return None

    opening = text.find('"', at + len(marker))
    if opening == -1:
        return None

    i = opening + 1
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            try:
                return json.loads(text[opening:i + 1])
            except ValueError:
                return None
        i += 1
    return None
