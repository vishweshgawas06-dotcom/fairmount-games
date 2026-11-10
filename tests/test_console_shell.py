"""Real HTTP shell/header proof; no privileged access is enabled for previews."""

import os
import unittest
from unittest.mock import patch

from fairmount_api.main import app
from fastapi.testclient import TestClient


class ConsoleShellTests(unittest.TestCase):
    def test_preview_shell_is_embeddable_without_enabling_private_api(self):
        with (
            patch.dict(os.environ, {"FAIRMOUNT_AUTH_EDGE_MODE": "disabled"}),
            TestClient(app) as client,
        ):
            response = client.get("/console/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])
            self.assertNotIn("frame-ancestors", response.headers["content-security-policy"])
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertIn('method="dialog"', response.text)
            for endpoint in ("context", "members", "history"):
                self.assertEqual(client.get("/api/v1/console/" + endpoint).status_code, 503)
            script = client.get("/console/app.mjs")
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.headers["content-type"])
            self.assertEqual(script.headers["x-content-type-options"], "nosniff")

    def test_direct_tls_configuration_disallows_framing_operator_pages(self):
        with (
            patch.dict(os.environ, {"FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls"}),
            TestClient(app) as client,
        ):
            response = client.get("/console/")
            self.assertIn("frame-ancestors 'self'", response.headers["content-security-policy"])
