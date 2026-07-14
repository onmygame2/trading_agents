import unittest

from dashboard.app import app


class DashboardContractTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_aggregated_apis_return_json(self):
        for path in (
            "/api/dashboard/workspace",
            "/api/dashboard/strategy_center",
            "/api/dashboard/memory_center",
            "/api/memory/health",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertLess(response.status_code, 500)
                self.assertIsInstance(response.get_json(), dict)

    def test_workspace_separates_recommendations_and_actions(self):
        payload = self.client.get("/api/dashboard/workspace").get_json()
        picks = payload.get("picks") or {}
        self.assertIn("picks", picks)
        self.assertIn("buy_actions", picks)
        self.assertIn("execution_status", picks)
        if picks.get("execution_status") == "preview_only":
            self.assertEqual(picks.get("buy_actions"), [])


if __name__ == "__main__":
    unittest.main()
