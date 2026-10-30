"""Gameplay-write envelope tests; no gameplay write route is exposed.

The probe application below is test-only. It proves the contract denies unsafe
shapes before a future handler sees them, and that a passing envelope still has
to be resolved against PostgreSQL before it means anything.
"""

import asyncio
import os
import secrets
import unittest
import uuid

from fairmount_api.db.models import Account, AccountCredential, PrivateIdentity
from fairmount_api.identity.credentials import hash_password
from fairmount_api.identity.http_boundary import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    RequestBoundaryUnavailable,
)
from fairmount_api.identity.session_logout import revoke_presented_session
from fairmount_api.identity.session_validation import resolve_session
from fairmount_api.identity.write_boundary import (
    MAX_WRITE_BYTES,
    GameplayWriteUnavailable,
    require_gameplay_write,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, text

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"
PROBE = FastAPI()


@PROBE.post("/probe/write")
async def probe_write(request: Request) -> JSONResponse:
    """Test-only sink: never mounted by fairmount_api.main."""
    try:
        write = await require_gameplay_write(request, public_origin=ORIGIN)
    except RequestBoundaryUnavailable:
        return JSONResponse({"status": "unavailable"}, status_code=400)
    return JSONResponse(
        {
            "keys": sorted(write.body),
            "idempotency_key": str(write.idempotency_key),
            "csrf_echoed": False,
        },
        headers={"Cache-Control": "no-store"},
    )


def _receive(chunks):
    """One bounded ASGI body stream; never yields more than the test provides."""
    pending = list(chunks)

    async def receive():
        if pending:
            return {"type": "http.request", "body": pending.pop(0), "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    return receive


def envelope(
    *,
    method="POST",
    body=b'{"stake": 10}',
    chunks=None,
    declared_length=None,
    content_type="application/json",
    idempotency=None,
    extra_headers=(),
    query_string=b"",
    token=None,
    csrf=None,
):
    token = token or secrets.token_urlsafe(32)
    csrf = csrf or secrets.token_urlsafe(32)
    declared = len(body) if declared_length is None else declared_length
    headers = [
        (b"host", b"game.example"),
        (b"origin", ORIGIN.encode()),
        (b"cookie", f"{SESSION_COOKIE}={token}; {CSRF_COOKIE}={csrf}".encode()),
        (CSRF_HEADER.encode(), csrf.encode()),
        (b"content-type", content_type.encode()),
        (b"content-length", str(declared).encode()),
        (b"idempotency-key", (idempotency or str(uuid.uuid4())).encode()),
    ]
    headers.extend((name.encode(), value.encode()) for name, value in extra_headers)
    scope = {
        "type": "http",
        "method": method,
        "headers": headers,
        "path": "/probe/write",
        "query_string": query_string,
        "scheme": "https",
        "server": ("127.0.0.1", 8000),
        "client": ("203.0.113.9", 5000),
    }
    return Request(scope, _receive([body] if chunks is None else chunks))


def guarded(request):
    return asyncio.run(require_gameplay_write(request, public_origin=ORIGIN))


class GameplayWriteContractTests(unittest.TestCase):
    def test_valid_write_returns_envelope_without_authority(self):
        request = envelope(extra_headers=(("sec-fetch-site", "same-origin"),))
        write = guarded(request)
        self.assertEqual(write.body, {"stake": 10})
        self.assertIsInstance(write.idempotency_key, uuid.UUID)
        self.assertNotIn(write.session_token, repr(write))  # token never rendered

    def test_json_media_type_variants(self):
        for content_type in (
            "application/json",
            "Application/JSON",
            "application/json; charset=utf-8",
            'application/json;charset="UTF-8"',
        ):
            with self.subTest(content_type=content_type):
                self.assertEqual(guarded(envelope(content_type=content_type)).body, {"stake": 10})
        for content_type in (
            "application/json; charset=latin-1",
            "application/json; boundary=x",
            "application/json-patch+json",
            "text/plain",
            "application/x-www-form-urlencoded",
            "multipart/form-data; boundary=x",
        ):
            with self.subTest(content_type=content_type), self.assertRaises(
                GameplayWriteUnavailable
            ):
                guarded(envelope(content_type=content_type))

    def test_ambiguous_or_missing_headers_are_denied(self):
        cases = (
            {"query_string": b"stake=10"},
            {"method": "GET"},
            {"method": "PUT"},
            {"idempotency": "not-a-uuid"},
            {"idempotency": "00000000-0000-0000-0000-000000000000"},
            {"extra_headers": (("transfer-encoding", "chunked"),)},
            {"extra_headers": (("content-encoding", "gzip"),)},
            {"extra_headers": (("sec-fetch-site", "cross-site"),)},
            {"extra_headers": (("sec-fetch-site", "same-site"),)},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(GameplayWriteUnavailable):
                guarded(envelope(**case))

    def test_duplicate_headers_are_denied(self):
        for name, value in (
            ("content-type", "application/json"),
            ("content-length", "13"),
            ("idempotency-key", str(uuid.uuid4())),
            ("sec-fetch-site", "same-origin"),
        ):
            request = envelope(extra_headers=((name, value),))
            request.scope["headers"].append((name.encode(), value.encode()))
            with self.subTest(header=name), self.assertRaises(GameplayWriteUnavailable):
                guarded(request)

    def test_idempotency_key_spellings_normalize_to_one_key(self):
        canonical = uuid.uuid4()
        for spelling in (
            str(canonical),
            str(canonical).upper(),
            canonical.hex,
            "{" + str(canonical) + "}",
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(guarded(envelope(idempotency=spelling)).idempotency_key, canonical)

    def test_body_must_be_one_bounded_json_object(self):
        for body in (
            b"[1, 2]",
            b'"text"',
            b"null",
            b"{",
            b'{"a": 1} {"b": 2}',
            b'{"a": 1, "a": 2}',
            b'{"a": NaN}',
            b'{"a": Infinity}',
            b"\xff\xfe",
            b"",
        ):
            with self.subTest(body=body), self.assertRaises(GameplayWriteUnavailable):
                guarded(envelope(body=body))

    def test_declared_length_must_match_streamed_bytes(self):
        request = envelope(body=b'{"stake": 10}', chunks=[b'{"stake": 10, "extra": 1}'])
        with self.assertRaises(GameplayWriteUnavailable):
            guarded(request)

    def test_oversized_declared_or_streamed_body_is_denied(self):
        oversized = b'{"pad": "' + b"a" * MAX_WRITE_BYTES + b'"}'
        with self.assertRaises(GameplayWriteUnavailable):
            guarded(envelope(body=oversized))
        # A truthful-looking Content-Length cannot hide a larger streamed body.
        streamed = [b"x" * MAX_WRITE_BYTES, b"x"]
        with self.assertRaises(GameplayWriteUnavailable):
            guarded(envelope(body=b"", chunks=streamed, declared_length=64))

    def test_invalid_limit_configuration_fails_closed(self):
        for limit in (0, -1, MAX_WRITE_BYTES + 1, True, "4096"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                asyncio.run(
                    require_gameplay_write(envelope(), public_origin=ORIGIN, max_bytes=limit)
                )


class GameplayWriteHTTPTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.client = TestClient(
            PROBE,
            base_url=ORIGIN,
            cookies={SESSION_COOKIE: self.token, CSRF_COOKIE: self.csrf},
        )

    def headers(self, **extra):
        """Browser-shaped request headers: exact origin plus the CSRF echo."""
        return {"origin": ORIGIN, CSRF_HEADER: self.csrf, **extra}

    def test_probe_accepts_one_same_origin_json_write(self):
        response = self.client.post(
            "/probe/write",
            json={"stake": 10, "selection": "RED"},
            headers=self.headers(**{"idempotency-key": str(uuid.uuid4())}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["keys"], ["selection", "stake"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_probe_denies_cross_site_form_and_missing_csrf(self):
        key = str(uuid.uuid4())
        cases = (
            ("form", {"data": {"stake": "10"}, "headers": self.headers()}, 400),
            ("text", {"content": b"stake=10", "headers": self.headers(
                **{"content-type": "text/plain", "idempotency-key": key})}, 400),
            ("csrf", {"json": {"stake": 10}, "headers": {"origin": ORIGIN,
                                                         "idempotency-key": key}}, 400),
            ("origin", {"json": {"stake": 10}, "headers": self.headers(
                **{"idempotency-key": key, "origin": "https://evil.example"})}, 400),
        )
        for name, kwargs, status in cases:
            with self.subTest(name=name):
                self.assertEqual(self.client.post("/probe/write", **kwargs).status_code, status)

    def test_denials_leak_no_request_detail(self):
        response = self.client.post(
            "/probe/write",
            json={"stake": 10},
            headers={"origin": "https://evil.example", CSRF_HEADER: self.csrf},
        )
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotIn(self.token, response.text)
        self.assertNotIn(self.csrf, response.text)


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class GameplayWriteDatabaseTests(unittest.TestCase):
    """An envelope is not authority: PostgreSQL still decides the actor."""

    PASSWORD = "a long private gameplay passphrase"

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()

    def tearDown(self):
        self.transaction.rollback()
        self.connection.close()

    def player(self, username="writer_01"):
        account_id = self.connection.execute(
            insert(Account.__table__).values(role="PLAYER").returning(Account.id)
        ).scalar_one()
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=account_id, login_kind="PLAYER", login_identifier=username
            )
        )
        self.connection.execute(
            insert(AccountCredential.__table__).values(
                account_id=account_id,
                initial_secret_issued_at=func.now() - text("interval '1 hour'"),
                initial_secret_consumed_at=func.now(),
                password_hash=hash_password(self.PASSWORD),
                password_changed_at=func.now(),
            )
        )
        return account_id

    def test_envelope_still_requires_postgresql_authorization(self):
        from fairmount_api.identity.member_login import issue_member_session

        account_id = self.player()
        issued = issue_member_session(self.connection, "PLAYER", "writer_01", self.PASSWORD)
        write = asyncio.run(
            require_gameplay_write(
                envelope(token=issued.token, body=b'{"stake": 10}'), public_origin=ORIGIN
            )
        )
        verified = resolve_session(self.connection, write.session_token)
        self.assertEqual((verified.account_id, verified.role), (account_id, "PLAYER"))

        # Revocation after the envelope passes must still deny the write downstream.
        self.assertTrue(revoke_presented_session(self.connection, write.session_token))
        self.assertIsNone(resolve_session(self.connection, write.session_token))

    def test_unknown_or_forged_session_tokens_never_authorize(self):
        write = asyncio.run(require_gameplay_write(envelope(), public_origin=ORIGIN))
        forged = write.session_token[:-1] + ("A" if write.session_token[-1] != "A" else "B")
        self.assertIsNone(resolve_session(self.connection, forged))
        self.assertFalse(revoke_presented_session(self.connection, forged))


if __name__ == "__main__":
    unittest.main()
