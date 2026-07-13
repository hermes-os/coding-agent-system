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
            json.dumps(
                {
                    "version": 1,
                    "events": {
                        "PreToolUse": [{"command": ["block.py"]}],
                        "Stop": [{"command": ["block.py"]}],
                    },
                }
            ),
            encoding="utf-8",
        )

    def run_dispatch(
        self,
        root: Path,
        host: str,
        event: str,
        home: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        effective_home = home or root / "home"
        effective_home.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            [str(DISPATCH), "--host", host, event],
            input=json.dumps({"cwd": str(root)}),
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(effective_home)},
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

    def test_duplicate_hook_skill_names_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            self.repo_with_blocking_hook(root)
            self.repo_with_blocking_hook(home)
            result = self.run_dispatch(root, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertIn("duplicate hook skill name", response["reason"])

    def test_invalid_inactive_event_entry_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo_with_blocking_hook(root)
            manifest = root / ".agents" / "skills" / "example" / "hooks.json"
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["events"]["Stop"][0]["unexpected"] = True
            manifest.write_text(json.dumps(value), encoding="utf-8")
            result = self.run_dispatch(root, "claude", "PreToolUse")
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unknown keys", response["reason"])


if __name__ == "__main__":
    unittest.main()
