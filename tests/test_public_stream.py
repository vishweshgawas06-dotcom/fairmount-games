"""Public reveal-only event stream: framing, de-duplication, bounds and privacy."""

import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fairmount_api.main import app
from fairmount_api.roulette import public_stream
from fairmount_api.roulette.public_snapshot import RevealedRound, RoundSnapshot
from fastapi.testclient import TestClient

URL = "/api/v1/roulette/stream"
PRIVATE_MARKERS = ("bet", "stake", "account", "wallet", "balance", "player", "token", "csrf")


def collect(*, read, seconds=0.35, poll=0.01, heartbeat=0.05):
    """Run the real generator for a bounded wall-clock slice and keep its frames."""

    async def runner():
        chunks = []

        async def consume():
            async for chunk in public_stream.event_stream(
                poll_seconds=poll, heartbeat_seconds=heartbeat, max_seconds=seconds, read=read
            ):
                chunks.append(chunk)

        await asyncio.wait_for(consume(), timeout=5)
        return chunks

    return asyncio.run(runner())


def snapshot(phase="SPINNING", number=None, round_id=None):
    import uuid
    from datetime import UTC, datetime

    now = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
    return RoundSnapshot(
        now,
        round_id or uuid.UUID("11111111-1111-4111-8111-111111111111"),
        phase,
        now,
        now,
        number,
        (RevealedRound(uuid.UUID("22222222-2222-4222-8222-222222222222"), "SETTLED", 7),),
    )


def encoded(snap):
    from fairmount_api.roulette.public_payload import encode_snapshot

    payload = encode_snapshot(snap)
    fingerprint = json.dumps(
        {"round": payload["round"], "recent": payload["recent"]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return fingerprint, json.dumps(payload, separators=(",", ":"), sort_keys=True)


class PublicStreamFramingTests(unittest.TestCase):
    def test_stream_emits_retry_then_one_snapshot_and_a_bound_close(self):
        frames = collect(read=lambda: encoded(snapshot()))
        self.assertEqual(frames[0], f"retry: {public_stream.RETRY_MILLISECONDS}\n\n")
        snapshots = [f for f in frames if "event: snapshot" in f]
        self.assertEqual(len(snapshots), 1)  # unchanged polls emit nothing
        self.assertIn("id: 1", snapshots[0])
        self.assertTrue(any("event: close" in f for f in frames))
        self.assertEqual(frames[-1], 'event: close\ndata: {"reason":"reconnect"}\n\n')
        self.assertIn('{"reason":"reconnect"}', frames[-1])

    def test_a_changed_payload_emits_a_new_event_without_duplicating_the_old(self):
        states = iter(
            [
                encoded(snapshot("BETTING")),
                encoded(snapshot("BETTING")),
                encoded(snapshot("SPINNING")),
                encoded(snapshot("RESULT", 17)),
            ]
        )
        last = {"value": None}

        def read():
            candidate = next(states, None)
            if candidate is not None:
                last["value"] = candidate
            return last["value"]  # hold the final value once the script runs out

        frames = collect(read=read)
        snapshots = [f for f in frames if "event: snapshot" in f]
        self.assertEqual(len(snapshots), 3)
        self.assertEqual([f.split("id: ")[1].split("\n")[0] for f in snapshots], ["1", "2", "3"])
        self.assertIn('"phase":"BETTING"', snapshots[0])
        self.assertIn('"phase":"RESULT"', snapshots[2])
        self.assertIn('"winning_number":17', snapshots[2])

    def test_unavailable_reads_emit_one_generic_event_and_never_invent_state(self):
        frames = collect(read=lambda: None)
        unavailable = [f for f in frames if "event: unavailable" in f]
        self.assertEqual(len(unavailable), 1)
        self.assertIn('{"status":"unavailable"}', unavailable[0])
        self.assertFalse(any("event: snapshot" in f for f in frames))

    def test_stream_frames_contain_no_private_marker(self):
        frames = collect(read=lambda: encoded(snapshot("RESULT", 17)))
        body = "".join(frames).lower()
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker, body)
        self.assertIn("winning_number", body)  # the public field is present

    def test_heartbeats_are_comments_not_events(self):
        frames = collect(read=lambda: None, heartbeat=0.02, seconds=0.3)
        heartbeats = [f for f in frames if f == ": keep-alive\n\n"]
        self.assertGreaterEqual(len(heartbeats), 1)

    def test_invalid_timing_configuration_fails_closed(self):
        for options in (
            {"poll_seconds": 0},
            {"heartbeat_seconds": -1},
            {"max_seconds": 0},
            {"poll_seconds": "1"},
            {"poll_seconds": 5, "max_seconds": 1},
            {"heartbeat_seconds": 5, "max_seconds": 1},
        ):
            with self.subTest(options=options):
                defaults = {
                    "poll_seconds": 0.01,
                    "heartbeat_seconds": 0.05,
                    "max_seconds": 0.1,
                    "read": lambda: None,
                }
                with self.assertRaises(ValueError):
                    asyncio.run(asyncio.wait_for(_drain({**defaults, **options}), timeout=5))


async def _drain(options):
    async for _ in public_stream.event_stream(**options):
        pass


class PublicStreamCapacityTests(unittest.TestCase):
    def setUp(self):
        public_stream.capacity.limit = 1
        public_stream.capacity.active = 0

    def tearDown(self):
        public_stream.capacity.limit = public_stream.MAX_STREAMS
        public_stream.capacity.active = 0

    def test_capacity_rejects_rather_than_queueing(self):
        public_stream.capacity.enter()
        with self.assertRaises(public_stream.StreamCapacityExceeded):
            public_stream.capacity.enter()
        public_stream.capacity.leave()
        public_stream.capacity.enter()  # a released slot is reusable
        public_stream.capacity.leave()

    def test_guarded_stream_always_releases_its_slot(self):
        public_stream.capacity.enter()
        self.assertEqual(public_stream.capacity.active, 1)

        async def run():
            async for _ in public_stream.guarded_stream(
                poll_seconds=0.01,
                heartbeat_seconds=0.05,
                max_seconds=0.15,
                read=lambda: None,
            ):
                pass

        asyncio.run(run())
        self.assertEqual(public_stream.capacity.active, 0)


class PublicStreamHTTPTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_stream_fails_closed_without_a_database(self):
        with patch("fairmount_api.roulette.public_api._configured_engine", return_value=None):
            response = self.client.get(URL)
        self.assertEqual((response.status_code, response.json()), (503, {"status": "unavailable"}))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_stream_rejects_when_capacity_is_exhausted(self):
        public_stream.capacity.limit = 0
        try:
            with (
                patch(
                    "fairmount_api.roulette.public_api._configured_engine",
                    return_value=MagicMock(),
                ),
                patch("fairmount_api.roulette.public_api.schema_ready", return_value=True),
            ):
                response = self.client.get(URL)
        finally:
            public_stream.capacity.limit = public_stream.MAX_STREAMS
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_http_stream_has_event_stream_headers_and_no_private_fields(self):
        with (
            patch(
                "fairmount_api.roulette.public_api._configured_engine",
                return_value=MagicMock(),
            ),
            patch("fairmount_api.roulette.public_api.schema_ready", return_value=True),
            patch(
                "fairmount_api.roulette.public_stream._snapshot_payload",
                return_value=encoded(snapshot("RESULT", 17)),
            ),
            patch.multiple(
                public_stream,
                POLL_SECONDS=0.01,
                HEARTBEAT_SECONDS=0.05,
                MAX_SECONDS=0.2,
            ),
        ):
            with self.client.stream("GET", URL) as response:
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
                self.assertEqual(response.headers["x-accel-buffering"], "no")
                self.assertEqual(response.headers["cache-control"], "no-store")
                body = ""
                for chunk in response.iter_text():
                    body += chunk
                    if "event: close" in body:
                        break
        self.assertIn("event: snapshot", body)
        self.assertIn('"winning_number":17', body)
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker, body.lower())


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class PublicStreamDatabaseTests(unittest.TestCase):
    """The real reader hides an unrevealed result and shows it after reveal."""

    def test_reader_is_reveal_gated_against_postgresql(self):
        from fairmount_api.roulette.public_snapshot import read_public_round_snapshot
        from sqlalchemy import create_engine, text

        from infrastructure.local_db_url import local_database_url

        engine = create_engine(local_database_url(test=True))
        connection = engine.connect()
        transaction = connection.begin()
        try:
            if True:
                # Two real rows: an older round already past reveal, and the newest
                # round CLOSED with a persisted number whose reveal is still ahead.
                # The table enforces closes = opens + 50s, reveal = opens + 60s and
                # its trigger forbids rewriting a stored timeline, so this fixture
                # only inserts; each round's own clock position does the work.
                connection.execute(
                    text(
                        "WITH t AS (SELECT clock_timestamp() AS now)"
                        " INSERT INTO roulette_rounds"
                        " (state, opens_at, closes_at, reveal_at, winning_number, result_set_at)"
                        " SELECT 'SETTLED', now - interval '120 seconds',"
                        " now - interval '70 seconds', now - interval '60 seconds', 7,"
                        " now - interval '70 seconds' FROM t"
                    )
                )
                connection.execute(
                    text(
                        "WITH t AS (SELECT clock_timestamp() AS now)"
                        " INSERT INTO roulette_rounds"
                        " (state, opens_at, closes_at, reveal_at, winning_number, result_set_at)"
                        " SELECT 'CLOSED', now - interval '55 seconds',"
                        " now - interval '5 seconds', now + interval '5 seconds', 23,"
                        " now - interval '5 seconds' FROM t"
                    )
                )
                # uuid has no max(); the newest round is the one with the latest
                # opens_at, which is exactly what the public projection selects.
                newest = connection.scalar(
                    text("SELECT id FROM roulette_rounds ORDER BY opens_at DESC, id DESC LIMIT 1")
                )
                snapshot = read_public_round_snapshot(connection)

            # The newest round has a persisted result, but the public projection
            # must not reveal it before reveal_at — and must not call it a void.
            self.assertEqual(snapshot.round_id, newest)
            self.assertEqual((snapshot.phase, snapshot.winning_number), ("SPINNING", None))
            # Only already-revealed rounds appear in history; the fresh row is in
            # the future and must never be included. Membership assertions keep
            # this robust to rows other modules committed earlier.
            revealed = [(item.state, item.winning_number) for item in snapshot.recent]
            self.assertIn(("SETTLED", 7), revealed)
            self.assertNotIn(23, [number for _state, number in revealed])
        finally:
            # Rollback-isolated: this module must not leave rows that change the
            # next run's public snapshot.
            transaction.rollback()
            connection.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
