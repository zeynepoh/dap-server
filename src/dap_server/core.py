"""Core SSE parsing logic.

The parser is a pull-style decoder: you feed it chunks of text and pull
dispatched events out one at a time. It deliberately owns no network or
I/O code so it can be driven from any transport.

The grammar implemented is the subset of the HTML spec\'s *Server-Sent
Events* algorithm that real-world servers rely on:

* Lines are split on ``\n``, with an optional trailing ``\r``.
* A blank line dispatches the event currently being accumulated.
* ``field: value`` strips exactly one leading space from *value*.
* ``field:value`` keeps *value* verbatim.
* ``data`` lines are concatenated with ``\n`` between them.
* ``event`` sets the event name; the last one before dispatch wins.
* ``id`` sets the last event ID.
* ``retry`` is parsed as a base-10 integer of milliseconds.
* Comment lines (``:…``) and unknown fields are silently ignored.
* A UTF-8 U+FEFF BOM at the very start of the stream is consumed once.

Trade-off: we do not surface a streaming *byte* interface. Callers must
already have decoded the transport to ``str``. This keeps the parser free
of buffering concerns and lets ``str.splitlines`` do the heavy lifting,
at the cost of one decode step upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class SSEEvent:
    """A fully-decoded SSE event ready for dispatch."""

    event: str = "message"
    data: str = ""
    id: Optional[str] = None
    retry: Optional[int] = None


@dataclass
class _Accumulator:
    """Per-event buffer used while lines stream in.

    Kept separate from :class:`SSEEvent` so that the public type never
    exposes half-built state.
    """

    event: Optional[str] = None
    data_lines: list[str] = field(default_factory=list)
    id: Optional[str] = None
    retry: Optional[int] = None
    has_data: bool = False

    def reset(self) -> None:
        self.event = None
        self.data_lines = []
        self.id = None
        self.retry = None
        self.has_data = False

    def to_event(self) -> SSEEvent:
        # The spec says the event type defaults to "message" when absent.
        name = self.event if self.event is not None else "message"
        # Multiple data lines are joined with a single newline, preserving
        # the exact content of each line — including the empty string that
        # a bare ``data:`` line contributes.
        data = "\n".join(self.data_lines)
        return SSEEvent(event=name, data=data, id=self.id, retry=self.retry)


class SSEParser:
    """Incremental parser for a ``text/event-stream`` string stream.

    Example::

        p = SSEParser()
        p.feed("data: hello\\n\\n")
        for ev in p.events():
            print(ev.event, ev.data)   # message hello

    Call :meth:`feed` with each chunk as it arrives from the transport,
    then drain :meth:`events` to collect fully-formed events. Any partial
    trailing line is retained internally until the next feed completes it.
    """

    def __init__(self) -> None:
        self._buffer: str = ""
        self._acc: _Accumulator = _Accumulator()
        self._dispatched: list[SSEEvent] = []
        self._first_chunk: bool = True

    def feed(self, chunk: str) -> None:
        """Append a decoded text chunk to the internal buffer.

        Feeding an empty string is a no-op, which lets callers forward
        keep-alive writes without special-casing.
        """
        if not chunk:
            return
        if self._first_chunk:
            # A BOM at the very start of the stream is legal and must be
            # consumed exactly once; a BOM in the middle of the stream is
            # not stripped and is treated as ordinary text.
            if chunk.startswith("\ufeff"):
                chunk = chunk[1:]
            self._first_chunk = False
        self._buffer += chunk
        self._process_lines()

    def _process_lines(self) -> None:
        while True:
            nl = self._buffer.find("\n")
            if nl == -1:
                break
            raw = self._buffer[:nl]
            self._buffer = self._buffer[nl + 1:]
            # Normalise CRLF to LF by dropping a trailing CR. We only strip
            # one so that an over-padded ``\r\r\n`` still leaves one CR in
            # the line content, matching the spec\'s single-step strip.
            if raw.endswith("\r"):
                raw = raw[:-1]
            self._handle_line(raw)

    def _handle_line(self, line: str) -> None:
        # A completely empty line is the event terminator per the spec.
        if line == "":
            # Only dispatch if we accumulated *something*. An event with no
            # data and no explicit fields is dropped, which is what servers
            # expect when they send blank lines for keep-alive.
            if (
                self._acc.event is not None
                or self._acc.has_data
                or self._acc.id is not None
                or self._acc.retry is not None
            ):
                self._dispatched.append(self._acc.to_event())
            self._acc.reset()
            return

        # Comments start with a colon and are ignored entirely.
        if line.startswith(":"):
            return

        colon = line.find(":")
        if colon == -1:
            # A line with no colon is still a valid field with an empty value.
            field_name = line
            value = ""
        else:
            field_name = line[:colon]
            rest = line[colon + 1:]
            # Strip exactly one leading space (not a U+FEFF, not other
            # whitespace) so that ``data:  two spaces`` keeps one space.
            if rest.startswith(" "):
                value = rest[1:]
            else:
                value = rest

        if field_name == "event":
            # The spec says the last event line wins, so we overwrite rather
            # than append.
            self._acc.event = value
        elif field_name == "data":
            self._acc.data_lines.append(value)
            self._acc.has_data = True
        elif field_name == "id":
            # An empty id explicitly clears the accumulated id. We keep the
            # empty string rather than None so a subsequent dispatch sees
            # the clear as "set to nothing".
            self._acc.id = value
        elif field_name == "retry":
            # Retry must be a non-negative base-10 integer of milliseconds.
            # Malformed values are ignored per the spec rather than raising.
            parsed = _parse_non_neg_int(value)
            if parsed is not None:
                self._acc.retry = parsed
        # Unknown fields are ignored silently.

    def events(self) -> list[SSEEvent]:
        """Return and clear all events dispatched since the last call."""
        out = self._dispatched
        self._dispatched = []
        return out

    def __iter__(self) -> Iterator[SSEEvent]:
        # Convenience alias so callers can write ``for ev in parser:`` in a
        # single-threaded feed-then-iterate loop.
        return iter(self.events())


def _parse_non_neg_int(value: str) -> Optional[int]:
    """Parse a non-negative base-10 integer, returning None on failure.

    ``int()`` would accept ``+5`` and surrounding whitespace, both of which
    the SSE spec rejects. We therefore validate character-by-character.
    """
    if value == "":
        return None
    result = 0
    for ch in value:
        if ch < "0" or ch > "9":
            return None
        result = result * 10 + (ord(ch) - ord("0"))
    return result
