"""Pure request-edge cookie/CSRF contract; no public auth route exists."""

import secrets
import unittest

from fairmount_api.identity.http_boundary import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    RequestBoundaryUnavailable,
    clear_session_cookies,
    require_same_origin_session,
    set_session_cookies,
)
from starlette.requests import Request
from starlette.responses import Response

PUBLIC_ORIGIN = "https://game.example"


def request(
    *, method="POST", host="game.example", origin=PUBLIC_ORIGIN, cookie_headers=(), csrf_headers=()
):
    headers = [(b"host", host.encode()), (b"origin", origin.encode())]
    headers.extend((b"cookie", value.encode()) for value in cookie_headers)
    headers.extend((CSRF_HEADER.encode(), value.encode()) for value in csrf_headers)
    return Request(
        {
            "type": "http",
            "method": method,
            "headers": headers,
            "path": "/private",
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
        }
    )


class HttpSessionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.cookies = f"{SESSION_COOKIE}={self.token}; {CSRF_COOKIE}={self.csrf}"

    def guarded(self, **changes):
        inputs = {"cookie_headers": (self.cookies,), "csrf_headers": (self.csrf,)}
        inputs.update(changes)
        return require_same_origin_session(request(**inputs), public_origin=PUBLIC_ORIGIN)

    def test_same_origin_post_returns_untrusted_token_only(self):
        self.assertEqual(self.guarded(), self.token)
        self.assertEqual(self.guarded(method="DELETE"), self.token)

    def test_all_cross_site_missing_or_ambiguous_headers_are_denied(self):
        cases = (
            {"origin": "https://evil.example"},
            {"origin": ""},
            {"origin": "null"},
            {"host": "evil.example"},
            {"host": "game.example:8000"},
            {"csrf_headers": ()},
            {"csrf_headers": (self.csrf, self.csrf)},
            {"csrf_headers": (secrets.token_urlsafe(32),)},
            {"cookie_headers": ()},
            {"cookie_headers": (self.cookies, self.cookies)},
            {"cookie_headers": (self.cookies + f"; {SESSION_COOKIE}={self.token}",)},
            {"cookie_headers": (self.cookies + f"; {CSRF_COOKIE}={self.csrf}",)},
            {"method": "GET"},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(RequestBoundaryUnavailable):
                self.guarded(**case)

    def test_duplicate_origin_or_host_header_is_denied(self):
        for header in (b"origin", b"host"):
            edge_request = request(cookie_headers=(self.cookies,), csrf_headers=(self.csrf,))
            edge_request.scope["headers"].append((header, b"game.example"))
            with self.subTest(header=header), self.assertRaises(RequestBoundaryUnavailable):
                require_same_origin_session(edge_request, public_origin=PUBLIC_ORIGIN)

    def test_malformed_cookies_and_public_origin_fail_closed(self):
        with self.assertRaises(RequestBoundaryUnavailable):
            self.guarded(cookie_headers=(f"{SESSION_COOKIE}=invalid; {CSRF_COOKIE}={self.csrf}",))
        with self.assertRaises(RequestBoundaryUnavailable):
            self.guarded(cookie_headers=(self.cookies + "x" * 8192,))
        for origin in (
            "http://game.example",
            "https://game.example/",
            "https://u:pw@game.example",
            "https://game.example?q=1",
            "https://game.example:invalid",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                require_same_origin_session(
                    request(cookie_headers=(self.cookies,), csrf_headers=(self.csrf,)),
                    public_origin=origin,
                )

    def test_cookie_issue_is_host_only_secure_strict_and_csrf_readable(self):
        response = Response()
        csrf = set_session_cookies(response, self.token, role="OWNER")
        self.assertEqual(len(csrf), 43)
        session_header, csrf_header = response.headers.getlist("set-cookie")
        self.assertIn(f"{SESSION_COOKIE}={self.token}", session_header)
        self.assertIn("Max-Age=28800", session_header)
        self.assertIn("httponly", session_header.lower())
        self.assertIn("secure", session_header.lower())
        self.assertIn("samesite=strict", session_header.lower())
        self.assertIn("Path=/", session_header)
        self.assertNotIn("domain=", session_header.lower())
        self.assertIn(f"{CSRF_COOKIE}={csrf}", csrf_header)
        self.assertNotIn("httponly", csrf_header.lower())
        self.assertIn("secure", csrf_header.lower())
        self.assertEqual(
            require_same_origin_session(
                request(
                    cookie_headers=(f"{SESSION_COOKIE}={self.token}; {CSRF_COOKIE}={csrf}",),
                    csrf_headers=(csrf,),
                ),
                public_origin=PUBLIC_ORIGIN,
            ),
            self.token,
        )
        clear = Response()
        clear_session_cookies(clear)
        self.assertEqual(len(clear.headers.getlist("set-cookie")), 2)
        self.assertTrue(all("Max-Age=0" in entry for entry in clear.headers.getlist("set-cookie")))

    def test_reject_invalid_session_issue_and_bound_role_ages(self):
        for role, seconds in (("AGENT", 43200), ("PLAYER", 86400)):
            response = Response()
            set_session_cookies(response, self.token, role=role)
            self.assertIn(f"Max-Age={seconds}", response.headers.getlist("set-cookie")[0])
        with self.assertRaises(ValueError):
            set_session_cookies(Response(), "invalid", role="OWNER")
        with self.assertRaises(ValueError):
            set_session_cookies(Response(), self.token, role="ADMIN")


if __name__ == "__main__":
    unittest.main()
