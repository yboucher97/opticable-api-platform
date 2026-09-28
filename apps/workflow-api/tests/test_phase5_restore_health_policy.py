import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]

spec = importlib.util.spec_from_file_location(
    "phase4_isolated_health_policy",
    ROOT / "ops/phase4/isolated_drill.py",
)
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


class IsolatedRestoreHealthPolicyTests(unittest.TestCase):
    def test_default_policy_remains_strict(self):
        self.assertTrue(
            drill.health_alerts_safe({
                "status": "ok",
                "alerts": [],
            })
        )

        self.assertFalse(
            drill.health_alerts_safe({
                "status": "warning",
                "alerts": [{
                    "code": "native_subscription_degraded",
                    "severity": "warning",
                }],
            })
        )

    def test_phase5_allows_only_reviewed_native_warning(self):
        allowed = {
            "native_subscription_degraded",
        }

        self.assertTrue(
            drill.health_alerts_safe(
                {
                    "status": "warning",
                    "alerts": [{
                        "code": "native_subscription_degraded",
                        "severity": "warning",
                    }],
                },
                allowed,
            )
        )

        self.assertFalse(
            drill.health_alerts_safe(
                {
                    "status": "warning",
                    "alerts": [
                        {
                            "code": "native_subscription_degraded",
                            "severity": "warning",
                        },
                        {
                            "code": "delta_sync_stopped",
                            "severity": "warning",
                        },
                    ],
                },
                allowed,
            )
        )

        self.assertFalse(
            drill.health_alerts_safe(
                {
                    "status": "critical",
                    "alerts": [{
                        "code": "native_subscription_degraded",
                        "severity": "critical",
                    }],
                },
                allowed,
            )
        )


if __name__ == "__main__":
    unittest.main()
