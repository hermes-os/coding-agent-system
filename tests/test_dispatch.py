from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


DISPATCH = Path(__file__).parents[1] / "hooks" / "dispatch.py"


class DispatchTests(unittest.TestCase):
    def repo_with_blocking_hook(self, root: Path) -> None:
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        hook = skill / "block.py"
        hook.write_text(
            "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'decision':'block','reason':'retry this'}))\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        (skill / "hooks.json").write_text(
            json.dumps({"events": {"PreToolUse": [{"command": ["block.py"]}], "Stop": [{"command": ["block.py"]}]}}),
            encoding="utf-8",
        )

    def run_dispatch(
        self,
        root: Path,
        host: str,
        event: str,
        home: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(DISPATCH), "--host", host, event],
            input=json.dumps({"cwd": str(root)}),
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(home)} if home else None,
            check=False,
        )

    def test_claude_uses_block_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo_with_blocking_hook(root)
            result = self.run_dispatch(root, "claude", "PreToolUse")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_cursor_pretool_blocks_with_exit_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo_with_blocking_hook(root)
            result = self.run_dispatch(root, "cursor", "preToolUse")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["permission"], "deny")

    def test_cursor_stop_requests_followup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo_with_blocking_hook(root)
            result = self.run_dispatch(root, "cursor", "stop")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["followup_message"], "retry this")

    def test_global_skill_hooks_are_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            self.repo_with_blocking_hook(home)
            result = self.run_dispatch(root, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
