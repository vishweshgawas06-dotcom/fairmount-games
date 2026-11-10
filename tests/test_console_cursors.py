"""History cursors are bounded ordering positions, never authorization tokens."""

import base64
import json
import unittest
import uuid
from datetime import UTC, datetime

from fairmount_api.console_reads import decode_cursor, encode_cursor


class ConsoleCursorTests(unittest.TestCase):
    def test_canonical_timezone_aware_round_trip(self):
        when, key = datetime(2026, 11, 7, 10, 20, 30, 123, UTC), uuid.uuid4()
        self.assertEqual(decode_cursor(encode_cursor(when, key)), (when, key))

    def test_malformed_tampered_shape_and_unbounded_values_fail(self):
        for value in ("", "x" * 161, "not_a_cursor!", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_cursor(value)
        for obj in (
            [],
            {},
            [[], 1],
            ["2026-11-07", str(uuid.uuid4())],
            ["2026-11-07T10:00:00+00:00", 42],
            ["bad", "bad"],
        ):
            value = base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
            with self.subTest(obj=obj), self.assertRaises(ValueError):
                decode_cursor(value)
