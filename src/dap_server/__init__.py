"""dap-server: a focused Server-Sent Events stream parser.

This package exposes a single class, :class:`SSEParser`, that turns a
chunked text stream (as delivered by ``text/event-stream``) into discrete
events with their fields decoded.
"""

from .core import SSEParser, SSEEvent

__all__ = ["SSEParser", "SSEEvent"]
