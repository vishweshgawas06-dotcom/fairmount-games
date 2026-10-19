"""Smoke tests for the initial API foundation."""

import unittest

from fairmount_api.main import app
from fastapi.testclient import TestClient


class ApiHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_liveness_returns_service_status(self) -> None:
        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "fairmount-api"},
        )

    def test_gameplay_routes_are_not_claimed_as_implemented(self) -> None:
        response = self.client.get("/health/live")

        self.assertNotIn("database", response.json())
        self.assertNotIn("round", response.json())


if __name__ == "__main__":
    unittest.main()
