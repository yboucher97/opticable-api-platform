"""Run the shipped dependency-free session client tests in the existing suite."""
from pathlib import Path
import subprocess
import unittest


class SessionClientTests(unittest.TestCase):
    def test_browser_session_state_machine(self):
        result=subprocess.run(['node','--test',str(Path(__file__).with_name('command_center_session_checks.cjs'))],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
