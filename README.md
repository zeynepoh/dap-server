# dap-server

A focused, zero-dependency parser for Server-Sent Events (`text/event-stream`) streams. Feed it decoded text chunks as they arrive; pull out fully-formed events with their `event`, `data`, `id`, and `retry` fields decoded.

## Usage

```python
from dap_server import SSEParser

parser = SSEParser()
parser.feed("event: update\n")
parser.feed("data: {\"v\": 1}\n")
parser.feed("retry: 3000\n")
parser.feed("\n")  # blank line dispatches

for ev in parser.events():
    print(ev.event, ev.data, ev.id, ev.retry)
    # update {"v": 1} None 3000
```

The parser exposes two names:

- `SSEParser` — call `feed(str)` with each chunk, then `events()` to drain dispatched `SSEEvent` objects.
- `SSEEvent` — a dataclass with `event: str`, `data: str`, `id: str | None`, `retry: int | None`.

## Why this exists

The SSE wire format is line-oriented but arrives over transports that deliver arbitrary byte boundaries. This parser owns the reassembly of partial lines and the field-level decoding, and nothing else — no sockets, no reconnection logic, no HTTP framing. Pair it with whatever transport you already have.

The trade-off: the parser consumes `str`, not `bytes`. You decode upstream. This keeps the core free of buffering and lets a single, well-tested code path handle all chunk boundaries.

## The awkward edge

A blank line dispatches the current event **only if at least one field was accumulated**. Servers commonly send blank lines as keep-alive padding; naively dispatching on every blank line produces spurious empty events. If you send `"\n"` with no preceding fields, `events()` returns nothing.

A second edge: the `retry` field is only accepted as a non-negative base-10 integer. `retry: -1` and `retry: +5` are silently ignored, matching the SSE specification rather than Python's liberal `int()`.
