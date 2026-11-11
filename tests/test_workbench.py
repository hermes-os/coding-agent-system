"""The commands the workbench image puts ahead of the system's own (workbench/bin/)."""

from pathlib import Path
import subprocess
import unittest


BIN = Path(__file__).resolve().parents[1] / "workbench/bin"


@unittest.skipUnless(Path("/usr/bin/setpriv").exists(), "this host has no setpriv; the image always has it")
class BashTest(unittest.TestCase):
    def run_bash(self, *args, path):
        return subprocess.run([str(BIN / "bash"), *args], env={"PATH": path}, text=True, capture_output=True)

    def test_a_caller_whose_path_holds_only_its_own_tools_still_gets_a_shell(self):
        result = self.run_bash("-c", "echo $1", "shell", "ok", path="/nowhere")
        self.assertEqual((result.returncode, result.stdout), (0, "ok\n"), result.stderr)

    def test_the_shell_holds_no_capability_it_could_pass_on(self):
        result = self.run_bash("-c", "grep -E '^Cap(Inh|Amb)' /proc/self/status", path="/usr/bin")
        self.assertEqual(result.stdout.split(), ["CapInh:", "0000000000000000", "CapAmb:", "0000000000000000"])


if __name__ == "__main__":
    unittest.main()
