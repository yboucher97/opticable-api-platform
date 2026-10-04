"""Release identity checks use the same handlers as local/public production health."""
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from workflow import api


class Phase6ReleaseVersionTests(unittest.TestCase):
    def test_health_aliases_and_openapi_report_contract_version(self):
        client = TestClient(api.app)
        for path in ("/health", "/v1/system/health"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["version"], "1.20.0")
                self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(api.app.version, "1.20.0")

    def test_version_matches_current_architecture_contract(self):
        contract = Path(__file__).resolve().parents[3] / "docs/OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md"
        self.assertIn("Current API contract: `" + api.API_VERSION + "`", contract.read_text())
