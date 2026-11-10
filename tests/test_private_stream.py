"""Private stream wire/termination/capacity tests; DB scope tested separately."""

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from fairmount_api import private_stream
from fairmount_api.main import app
from fairmount_api.resource_reads import ResourceUnavailable
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


def collect(read, **options):
    async def run():
        return [
            frame
            async for frame in private_stream.events(
                read,
                **{"poll_seconds": 0.005, "heartbeat_seconds": 0.02, "max_seconds": 0.2, **options},
            )
        ]

    return asyncio.run(asyncio.wait_for(run(), timeout=5))


def snapshot(value="10", observed="time"):
    return {"account_id": "opaque", "balance": value, "observed_at": observed}


class PrivateStreamTests(unittest.TestCase):
    def test_changed_only_ordered_snapshot_and_bounded_reconnect(self):
        calls = 0

        def read():
            nonlocal calls
            calls += 1
            return snapshot("10" if calls < 3 else "11", str(calls))

        frames = collect(read)
        snapshots = [f for f in frames if "event: snapshot" in f]
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(snapshots[0].startswith("id: 1\nevent: snapshot\n"))
        self.assertTrue(snapshots[1].startswith("id: 2\nevent: snapshot\n"))
        self.assertEqual(frames[0], "retry: 3000\n\n")
        self.assertIn("event: close", frames[-1])
        self.assertIn(": keep-alive\n\n", frames)

    def test_denial_or_database_failure_terminates_without_replaying_private_state(self):
        for error in (ResourceUnavailable("private reason"), SQLAlchemyError("private SQL")):
            calls = 0

            def read(error=error):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return snapshot()
                raise error

            frames = collect(read)
            self.assertEqual(sum("event: snapshot" in f for f in frames), 1)
            self.assertEqual(frames[-1], 'event: unavailable\ndata: {"status":"unavailable"}\n\n')
            self.assertNotIn("private reason", "".join(frames))
            self.assertNotIn("private SQL", "".join(frames))
            self.assertEqual(calls, 2)

    def test_no_first_private_frame_when_already_denied(self):
        def denied():
            raise ResourceUnavailable("reason")

        self.assertFalse(any("event: snapshot" in f for f in collect(denied)))

    def test_timing_rejects_nonfinite_boolean_and_invalid_values(self):
        async def run(value):
            return [f async for f in private_stream.events(lambda: snapshot(), max_seconds=value)]

        for value in (True, 0, -1, "1", float("nan"), float("inf"), 0.01):
            with self.subTest(value=value), self.assertRaises(ValueError):
                asyncio.run(run(value))

    def test_json_framing_escapes_newlines_and_does_not_inject_events(self):
        frames = collect(lambda: snapshot("value\nevent: forged"))
        frame = next(f for f in frames if "event: snapshot" in f)
        self.assertEqual(sum(line.startswith("event:") for line in frame.splitlines()), 1)
        data = frame.split("data: ")[1].strip()
        self.assertEqual(json.loads(data)["balance"], "value\nevent: forged")

    def test_slow_poll_does_not_emit_private_state_after_stream_lifetime(self):
        import time

        def read():
            time.sleep(0.1)
            return snapshot()

        frames = collect(read, max_seconds=0.06)
        self.assertFalse(any("event: snapshot" in f for f in frames))
        self.assertIn("event: close", frames[-1])

    def test_process_and_session_caps_do_not_queue_or_retain_released_digests(self):
        limiter = private_stream.Capacity(total=3, per_session=2)
        limiter.enter("a")
        limiter.enter("a")
        with self.assertRaises(private_stream.PrivateCapacityUnavailable):
            limiter.enter("a")
        limiter.enter("b")
        with self.assertRaises(private_stream.PrivateCapacityUnavailable):
            limiter.enter("c")
        limiter.leave("a")
        limiter.enter("c")
        limiter.leave("a")
        limiter.leave("b")
        limiter.leave("c")
        self.assertEqual(limiter.sessions, {})

    def test_cancel_and_read_error_release_reserved_stream_slot(self):
        async def run(read):
            private_stream.capacity.enter("digest")
            stream = private_stream.guarded_events(
                "digest", read, poll_seconds=0.005, heartbeat_seconds=0.01, max_seconds=0.02
            )
            await anext(stream)  # retry frame; generator started
            try:
                await anext(stream)
            finally:
                await stream.aclose()

        asyncio.run(run(lambda: snapshot()))
        self.assertNotIn("digest", private_stream.capacity.sessions)

        def bad():
            raise RuntimeError("unexpected bug")

        with self.assertRaises(RuntimeError):
            asyncio.run(run(bad))
        self.assertNotIn("digest", private_stream.capacity.sessions)

    def test_preview_handshake_is_not_an_authentication_bypass(self):
        with patch.dict(os.environ, {"FAIRMOUNT_AUTH_EDGE_MODE": "disabled"}), TestClient(app) as c:
            for url in (
                "/api/v1/me/stream",
                "/api/v1/players/00000000-0000-4000-8000-000000000001/stream",
            ):
                response = c.get(url)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertNotIn("snapshot", response.text)

    def test_configured_direct_tls_without_database_is_backend_not_session_denial(self):
        from fairmount_api.identity.http_boundary import SESSION_COOKIE

        with (
            patch.dict(
                os.environ,
                {
                    "FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls",
                    "FAIRMOUNT_PUBLIC_ORIGIN": "https://stream.example",
                },
            ),
            patch.object(private_stream, "_configured_engine", return_value=None),
            TestClient(
                app,
                base_url="https://stream.example",
                client=("203.0.113.80", 51000),
                cookies={SESSION_COOKIE: "A" * 43},
            ) as c,
        ):
            response = c.get("/api/v1/me/stream")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
