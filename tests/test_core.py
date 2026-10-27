from __future__ import annotations

import unittest

from dap_server.core import SSEParser, SSEEvent


class TestBasicDispatch(unittest.TestCase):
    def test_single_data_line(self) -> None:
        p = SSEParser()
        p.feed("data: hello\n\n")
        events = p.events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event, "message")
        self.assertEqual(ev.data, "hello")
        self.assertIsNone(ev.id)
        self.assertIsNone(ev.retry)

    def test_default_event_name_is_message(self) -> None:
        p = SSEParser()
        p.feed("data: x\n\n")
        self.assertEqual(p.events()[0].event, "message")

    def test_explicit_event_name(self) -> None:
        p = SSEParser()
        p.feed("event: ping\ndata: 1\n\n")
        ev = p.events()[0]
        self.assertEqual(ev.event, "ping")
        self.assertEqual(ev.data, "1")

    def test_event_name_empty_string(self) -> None:
        p = SSEParser()
        p.feed("event:\ndata: x\n\n")
        # An explicit empty event name is a real name, not the default.
        self.assertEqual(p.events()[0].event, "")


class TestDataField(unittest.TestCase):
    def test_data_no_space_after_colon(self) -> None:
        p = SSEParser()
        p.feed("data:hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_data_one_space_stripped(self) -> None:
        p = SSEParser()
        p.feed("data: hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_data_two_spaces_one_kept(self) -> None:
        p = SSEParser()
        p.feed("data:  two spaces\n\n")
        self.assertEqual(p.events()[0].data, " two spaces")

    def test_data_empty_value(self) -> None:
        p = SSEParser()
        p.feed("data:\n\n")
        self.assertEqual(p.events()[0].data, "")

    def test_data_empty_with_space(self) -> None:
        p = SSEParser()
        p.feed("data: \n\n")
        self.assertEqual(p.events()[0].data, "")

    def test_multiple_data_lines_joined_by_newline(self) -> None:
        p = SSEParser()
        p.feed("data: line1\ndata: line2\ndata: line3\n\n")
        self.assertEqual(p.events()[0].data, "line1\nline2\nline3")

    def test_multiple_data_lines_with_empty(self) -> None:
        # An empty data line still contributes an entry to the join.
        p = SSEParser()
        p.feed("data: a\ndata:\ndata: b\n\n")
        self.assertEqual(p.events()[0].data, "a\n\nb")


class TestIdField(unittest.TestCase):
    def test_id_set(self) -> None:
        p = SSEParser()
        p.feed("id: 42\ndata: x\n\n")
        self.assertEqual(p.events()[0].id, "42")

    def test_id_no_space(self) -> None:
        p = SSEParser()
        p.feed("id:42\ndata: x\n\n")
        self.assertEqual(p.events()[0].id, "42")

    def test_id_empty_string(self) -> None:
        p = SSEParser()
        p.feed("id:\ndata: x\n\n")
        # An empty id is the explicit empty string, not None.
        self.assertEqual(p.events()[0].id, "")

    def test_id_overwrite(self) -> None:
        p = SSEParser()
        p.feed("id: 1\nid: 2\ndata: x\n\n")
        self.assertEqual(p.events()[0].id, "2")


class TestRetryField(unittest.TestCase):
    def test_retry_valid(self) -> None:
        p = SSEParser()
        p.feed("retry: 3000\ndata: x\n\n")
        self.assertEqual(p.events()[0].retry, 3000)

    def test_retry_no_space(self) -> None:
        p = SSEParser()
        p.feed("retry:5000\ndata: x\n\n")
        self.assertEqual(p.events()[0].retry, 5000)

    def test_retry_zero(self) -> None:
        p = SSEParser()
        p.feed("retry: 0\ndata: x\n\n")
        self.assertEqual(p.events()[0].retry, 0)

    def test_retry_negative_ignored(self) -> None:
        p = SSEParser()
        p.feed("retry: -1\ndata: x\n\n")
        self.assertIsNone(p.events()[0].retry)

    def test_retry_non_numeric_ignored(self) -> None:
        p = SSEParser()
        p.feed("retry: abc\ndata: x\n\n")
        self.assertIsNone(p.events()[0].retry)

    def test_retry_with_plus_sign_ignored(self) -> None:
        p = SSEParser()
        p.feed("retry: +5\ndata: x\n\n")
        self.assertIsNone(p.events()[0].retry)

    def test_retry_empty_ignored(self) -> None:
        p = SSEParser()
        p.feed("retry:\ndata: x\n\n")
        self.assertIsNone(p.events()[0].retry)


class TestCommentsAndUnknown(unittest.TestCase):
    def test_comment_line_ignored(self) -> None:
        p = SSEParser()
        p.feed(": this is a comment\ndata: x\n\n")
        ev = p.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].data, "x")

    def test_comment_no_space_after_colon(self) -> None:
        p = SSEParser()
        p.feed(":comment\ndata: x\n\n")
        self.assertEqual(p.events()[0].data, "x")

    def test_unknown_field_ignored(self) -> None:
        p = SSEParser()
        p.feed("foo: bar\ndata: x\n\n")
        ev = p.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].data, "x")

    def test_field_no_colon(self) -> None:
        # A line with no colon is a field name with an empty value.
        # "somedata" is unknown and ignored, so no event is dispatched.
        p = SSEParser()
        p.feed("somedata\n\n")
        self.assertEqual(p.events(), [])


class TestLineEndingAndChunking(unittest.TestCase):
    def test_crlf_line_endings(self) -> None:
        p = SSEParser()
        p.feed("data: hello\r\n\r\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_lf_only(self) -> None:
        p = SSEParser()
        p.feed("data: hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_chunked_single_line(self) -> None:
        p = SSEParser()
        p.feed("da")
        p.feed("ta: he")
        p.feed("llo\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_chunked_across_blank_line(self) -> None:
        p = SSEParser()
        p.feed("data: hello\n")
        self.assertEqual(p.events(), [])
        p.feed("\n")
        self.assertEqual(len(p.events()), 1)

    def test_multiple_events_one_feed(self) -> None:
        p = SSEParser()
        p.feed("data: a\n\ndata: b\n\n")
        evs = p.events()
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0].data, "a")
        self.assertEqual(evs[1].data, "b")

    def test_trailing_partial_line_retained(self) -> None:
        p = SSEParser()
        p.feed("data: a\n\ndata: b")
        # Only the first event is complete.
        self.assertEqual(len(p.events()), 1)
        p.feed("\n\n")
        self.assertEqual(len(p.events()), 1)


class TestBlankLineBehaviour(unittest.TestCase):
    def test_blank_line_no_fields_no_dispatch(self) -> None:
        p = SSEParser()
        p.feed("\n")
        self.assertEqual(p.events(), [])

    def test_blank_line_after_comment_no_dispatch(self) -> None:
        p = SSEParser()
        p.feed(": comment\n\n")
        self.assertEqual(p.events(), [])

    def test_consecutive_blank_lines_one_dispatch(self) -> None:
        # After the first blank line dispatches and resets, subsequent
        # blanks have no accumulated fields and do not produce spurious events.
        p = SSEParser()
        p.feed("data: x\n\n\n\n")
        self.assertEqual(len(p.events()), 1)

    def test_blank_line_after_unknown_field_no_dispatch(self) -> None:
        p = SSEParser()
        p.feed("foo: bar\n\n")
        self.assertEqual(p.events(), [])


class TestBOM(unittest.TestCase):
    def test_bom_at_start_stripped(self) -> None:
        p = SSEParser()
        p.feed("\ufeffdata: hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_bom_split_across_chunks(self) -> None:
        p = SSEParser()
        p.feed("\ufeff")
        p.feed("data: hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")

    def test_bom_not_stripped_mid_stream(self) -> None:
        # After the first real content, a BOM is ordinary text. A BOM
        # prefixing a field name makes that field name unknown, so the
        # line is ignored and no event is dispatched for it.
        p = SSEParser()
        p.feed("data: a\n\n")
        p.feed("\ufeffdata: b\n\n")
        evs = p.events()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].data, "a")

    def test_no_bom_first_chunk_normal(self) -> None:
        p = SSEParser()
        p.feed("data: hello\n\n")
        self.assertEqual(p.events()[0].data, "hello")


class TestNoDataOnlyFields(unittest.TestCase):
    def test_event_without_data_dispatches(self) -> None:
        # If any field was set, the event is dispatched even with no data.
        p = SSEParser()
        p.feed("event: ping\n\n")
        ev = p.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event, "ping")
        self.assertEqual(ev[0].data, "")

    def test_id_without_data_dispatches(self) -> None:
        p = SSEParser()
        p.feed("id: 99\n\n")
        ev = p.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].id, "99")
        self.assertEqual(ev[0].data, "")

    def test_retry_without_data_dispatches(self) -> None:
        p = SSEParser()
        p.feed("retry: 1000\n\n")
        ev = p.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].retry, 1000)


class TestEventsClear(unittest.TestCase):
    def test_events_clears_buffer(self) -> None:
        p = SSEParser()
        p.feed("data: a\n\n")
        self.assertEqual(len(p.events()), 1)
        self.assertEqual(p.events(), [])

    def test_iter_alias(self) -> None:
        p = SSEParser()
        p.feed("data: a\n\ndata: b\n\n")
        collected = list(p)
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0].data, "a")
        self.assertEqual(collected[1].data, "b")


class TestFullEvent(unittest.TestCase):
    def test_all_fields_together(self) -> None:
        p = SSEParser()
        p.feed(
            "id: 100\n"
            "event: update\n"
            "retry: 2000\n"
            "data: first\n"
            "data: second\n"
            "\n"
        )
        ev = p.events()[0]
        self.assertEqual(ev.id, "100")
        self.assertEqual(ev.event, "update")
        self.assertEqual(ev.retry, 2000)
        self.assertEqual(ev.data, "first\nsecond")

    def test_empty_feed_noop(self) -> None:
        p = SSEParser()
        p.feed("")
        self.assertEqual(p.events(), [])

    def test_data_with_colon_in_value(self) -> None:
        # Only the first colon separates field from value; later colons are
        # literal content.
        p = SSEParser()
        p.feed("data: a: b: c\n\n")
        self.assertEqual(p.events()[0].data, "a: b: c")

    def test_last_event_wins(self) -> None:
        p = SSEParser()
        p.feed("event: a\nevent: b\nevent: c\ndata: x\n\n")
        self.assertEqual(p.events()[0].event, "c")


class TestTypeShape(unittest.TestCase):
    def test_event_is_sseevent(self) -> None:
        p = SSEParser()
        p.feed("data: x\n\n")
        self.assertIsInstance(p.events()[0], SSEEvent)

    def test_retry_is_int_or_none(self) -> None:
        p = SSEParser()
        p.feed("retry: 500\ndata: x\n\n")
        self.assertIsInstance(p.events()[0].retry, int)

    def test_id_is_str_or_none(self) -> None:
        p = SSEParser()
        p.feed("id: 1\ndata: x\n\n")
        self.assertIsInstance(p.events()[0].id, str)


if __name__ == "__main__":
    unittest.main()
