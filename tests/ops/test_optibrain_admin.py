import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).parents[2] / "ops/admin/optibrain-admin.py"
spec = importlib.util.spec_from_file_location("optibrain_admin", PATH)
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class RequestValidationTests(unittest.TestCase):
    def test_fixed_operations(self):
        self.assertEqual(admin.parse_request(["backup"]), ("backup",))
        self.assertEqual(admin.parse_request(["service-status", "opticable-workflow-api.service"]),
                         ("service-status", "opticable-workflow-api.service"))

    def test_rejects_shell_and_arbitrary_paths(self):
        for args in (["sh"], ["bash", "-c", "id"], ["run", "/etc/shadow"],
                     ["service-restart", "ssh.service"],
                     ["service-status", "opticable-workflow-api.service;id"],
                     ["timer-status", "arbitrary.timer"], ["backup", "--output-dir", "/tmp"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                admin.parse_request(args)


if __name__ == "__main__":
    unittest.main()
