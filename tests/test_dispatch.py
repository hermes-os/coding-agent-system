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
        (skill / "SKILL.md").write_text(
            "---\nname: example\ndescription: Example hook.\n---\n\n# Example\n",
            encoding="utf-8",
        )
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

    def test_hooks_only_and_nested_skill_layouts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hooks_only = root / ".agents" / "skills" / "hooks-only"
            hooks_only.mkdir(parents=True)
            (hooks_only / "hooks.json").write_text(
                json.dumps({"version": 1, "events": {"Stop": [{"command": ["hook.py"]}]}}),
                encoding="utf-8",
            )
            result = self.run_dispatch(root, "claude", "Stop")
            self.assertIn("adjacent SKILL.md", json.loads(result.stdout)["reason"])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / ".agents" / "skills" / "group" / "nested"
            nested.mkdir(parents=True)
            (nested / "SKILL.md").write_text(
                "---\nname: nested\ndescription: Nested fixture.\n---\n",
                encoding="utf-8",
            )
            result = self.run_dispatch(root, "claude", "Stop")
            self.assertIn("direct children", json.loads(result.stdout)["reason"])

    def test_aggregate_event_budget_fails_before_any_hook_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo_with_blocking_hook(root)
            first_manifest = root / ".agents" / "skills" / "example" / "hooks.json"
            first = json.loads(first_manifest.read_text(encoding="utf-8"))
            first["events"]["Stop"][0]["timeoutSeconds"] = 300
            first_manifest.write_text(json.dumps(first), encoding="utf-8")

            second = root / ".agents" / "skills" / "second"
            second.mkdir(parents=True)
            (second / "SKILL.md").write_text(
                "---\nname: second\ndescription: Second fixture.\n---\n",
                encoding="utf-8",
            )
            hook = second / "pass.py"
            hook.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            hook.chmod(0o755)
            (second / "hooks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "events": {
                            "Stop": [{"command": ["pass.py"], "timeoutSeconds": 40}]
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_dispatch(root, "claude", "Stop")
            response = json.loads(result.stdout)
            self.assertEqual(response["decision"], "block")
            self.assertIn("declares 340 seconds", response["reason"])


if __name__ == "__main__":
    unittest.main()
