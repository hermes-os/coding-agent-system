from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
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

    def test_hooks_only_skill_layout_fails_closed(self):
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

    def test_repository_symlinked_roots_owners_and_executables_fail_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            external = base / "external"
            root.mkdir()
            external.mkdir()
            self.repo_with_blocking_hook(external)
            (root / ".agents").symlink_to(external / ".agents", target_is_directory=True)
            result = self.run_dispatch(root, "claude", "Stop")
            reason = json.loads(result.stdout)["reason"]
            self.assertIn("repository skill path must not be a symlink", reason)
            self.assertNotIn("retry this", reason)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            external = base / "external"
            root.mkdir()
            self.repo_with_blocking_hook(external)
            skill_root = root / ".agents" / "skills"
            skill_root.mkdir(parents=True)
            (skill_root / "example").symlink_to(
                external / ".agents" / "skills" / "example",
                target_is_directory=True,
            )
            result = self.run_dispatch(root, "claude", "Stop")
            reason = json.loads(result.stdout)["reason"]
            self.assertIn("repository skill owner must not be a symlink", reason)
            self.assertNotIn("retry this", reason)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.repo_with_blocking_hook(root)
            skill = root / ".agents" / "skills" / "example"
            external = base / "external.py"
            external.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            external.chmod(0o755)
            (skill / "block.py").unlink()
            (skill / "block.py").symlink_to(external)
            result = self.run_dispatch(root, "claude", "Stop")
            reason = json.loads(result.stdout)["reason"]
            self.assertIn("executable path must not be a symlink", reason)

    def test_discovery_time_counts_against_the_event_deadline(self):
        functions = runpy.run_path(str(DISPATCH))
        schedule = functions["scheduled_hooks"]
        globals_ = schedule.__globals__
        original = globals_["hook_manifests"]

        def delayed_discovery(_root: Path):
            time.sleep(0.03)
            return []

        globals_["hook_manifests"] = delayed_discovery
        try:
            with self.assertRaisesRegex(TimeoutError, "skill discovery"):
                schedule(
                    Path.cwd(),
                    "Stop",
                    {"Stop"},
                    {"Stop": 1},
                    time.monotonic() + 0.01,
                )
        finally:
            globals_["hook_manifests"] = original

    def test_timeout_terminates_forked_hook_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / ".agents" / "skills" / "forking"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: forking\ndescription: Forking hook fixture.\n---\n",
                encoding="utf-8",
            )
            hook = skill / "fork.py"
            hook.write_text(
                "#!/usr/bin/env python3\n"
                "import os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                "marker = Path(os.environ['AGENT_PROJECT_DIR']) / 'descendant-wrote'\n"
                "code = \"import sys,time; from pathlib import Path; time.sleep(1.4); Path(sys.argv[1]).write_text('leaked')\"\n"
                "subprocess.Popen([sys.executable, '-c', code, str(marker)])\n"
                "time.sleep(10)\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "events": {
                            "Stop": [{"command": ["fork.py"], "timeoutSeconds": 1}]
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_dispatch(root, "claude", "Stop")
            response = json.loads(result.stdout)
            self.assertIn("runtime budget", response["reason"])
            time.sleep(0.7)
            self.assertFalse((root / "descendant-wrote").exists())

    def test_hook_output_is_bounded_and_flooding_process_is_terminated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / ".agents" / "skills" / "flood"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: flood\ndescription: Output flood fixture.\n---\n",
                encoding="utf-8",
            )
            hook = skill / "flood.py"
            hook.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "chunk = b'x' * 65536\n"
                "while True:\n"
                "    os.write(1, chunk)\n"
                "    os.write(2, chunk)\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "events": {
                            "Stop": [{"command": ["flood.py"], "timeoutSeconds": 20}]
                        },
                    }
                ),
                encoding="utf-8",
            )
            started = time.monotonic()
            result = self.run_dispatch(root, "claude", "Stop")
            elapsed = time.monotonic() - started
            response = json.loads(result.stdout)
            self.assertIn("hook output exceeds", response["reason"])
            self.assertLess(elapsed, 10)

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
