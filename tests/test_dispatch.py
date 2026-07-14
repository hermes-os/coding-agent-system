from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import unittest
from unittest import mock


DISPATCH = Path(__file__).parents[1] / "hooks" / "dispatch.py"
GIT_DISCOVERY_ENVIRONMENT = (
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_PREFIX",
    "GIT_WORK_TREE",
)


class DispatchTests(unittest.TestCase):
    def clean_git_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for name in GIT_DISCOVERY_ENVIRONMENT:
            environment.pop(name, None)
        return environment

    def init_repository(self, root: Path) -> None:
        subprocess.run(
            ["git", "init", "--quiet", str(root)],
            text=True,
            capture_output=True,
            env=self.clean_git_environment(),
            check=True,
        )

    def assert_non_repository(self, root: Path) -> None:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            env=self.clean_git_environment(),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, f"fixture unexpectedly belongs to {result.stdout}")

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
        repository: bool | None = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if repository is True:
            self.init_repository(root)
        elif repository is False:
            self.assert_non_repository(root)
        effective_home = home or root / "home"
        effective_home.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "HOME": str(effective_home)}
        environment.pop("AGENTS_HOME", None)
        environment.update(extra_env or {})
        return subprocess.run(
            [str(DISPATCH), "--host", host, event],
            input=json.dumps({"cwd": str(root)}),
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def install_managed_global_skill(self, home: Path, name: str) -> None:
        source = DISPATCH.parents[1] / "skills" / name
        destination = home / ".agents" / "skills" / name
        destination.parent.mkdir(parents=True)
        destination.symlink_to(source, target_is_directory=True)
        (home / ".agents" / "managed-install.json").write_text(
            json.dumps(
                {
                    "paths": {
                        str(destination): {
                            "kind": "symlink",
                            "target": str(source),
                        }
                    }
                }
            ),
            encoding="utf-8",
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
            result = self.run_dispatch(
                root,
                "claude",
                "PreToolUse",
                home=home,
                repository=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_non_repository_home_does_not_rediscover_global_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir()
            self.install_managed_global_skill(home, "behavior-validator")
            result = self.run_dispatch(
                home,
                "claude",
                "PreToolUse",
                home=home,
                repository=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_home_workspace_does_not_rediscover_global_skills_as_repository_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir()
            self.install_managed_global_skill(home, "behavior-validator")
            result = self.run_dispatch(home, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_symlinked_global_agents_home_is_not_rediscovered_as_repository_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            agents_home = base / "global-agents"
            home.mkdir()
            agents_home.mkdir()
            (home / ".agents").symlink_to(agents_home, target_is_directory=True)
            self.install_managed_global_skill(home, "behavior-validator")
            result = self.run_dispatch(home, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_non_repository_workspace_ignores_repository_skill_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "workspace"
            external = base / "external"
            root.mkdir()
            external.mkdir()
            self.repo_with_blocking_hook(external)
            (root / ".agents").symlink_to(external / ".agents", target_is_directory=True)
            result = self.run_dispatch(
                root,
                "claude",
                "PreToolUse",
                repository=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_broken_git_repository_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".git").mkdir()
            result = self.run_dispatch(
                root,
                "claude",
                "PreToolUse",
                repository=False,
            )
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertIn("cannot resolve Git repository", response["reason"])

    def test_inaccessible_git_repository_marker_fails_closed(self):
        functions = runpy.run_path(str(DISPATCH))
        marker = functions["git_repository_marker"]
        with mock.patch.object(Path, "stat", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "cannot inspect hook working directory"):
                marker(Path("/workspace"))

        real_stat = Path.stat

        def permitted_directory(path: Path, *args, **kwargs):
            return real_stat(path, *args, **kwargs)

        with mock.patch.object(Path, "stat", new=permitted_directory):
            with mock.patch.object(Path, "lstat", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(ValueError, "cannot inspect Git repository marker"):
                    marker(Path.cwd())

    def test_git_repository_marker_scan_stops_at_filesystem_boundary(self):
        functions = runpy.run_path(str(DISPATCH))
        marker = functions["git_repository_marker"]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            mount = base / "mount"
            root = mount / "workspace"
            root.mkdir(parents=True)
            (base / ".git").mkdir()
            real_stat = Path.stat

            def device_stat(path: Path, *args, **kwargs):
                if path in (root, mount):
                    return mock.Mock(st_dev=2)
                if path == base:
                    return mock.Mock(st_dev=1)
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(Path, "stat", new=device_stat):
                self.assertIsNone(marker(root))

    def test_git_environment_cannot_redirect_non_repository_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repository = base / "repository"
            scratch = base / "scratch"
            repository.mkdir()
            scratch.mkdir()
            self.repo_with_blocking_hook(repository)
            self.init_repository(repository)
            result = self.run_dispatch(
                scratch,
                "claude",
                "PreToolUse",
                repository=False,
                extra_env={
                    "GIT_DIR": str(repository / ".git"),
                    "GIT_WORK_TREE": str(repository),
                },
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_hook_git_commands_share_sanitized_repository_context(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repository = base / "repository"
            redirected = base / "redirected"
            repository.mkdir()
            redirected.mkdir()
            self.repo_with_blocking_hook(repository)
            self.init_repository(redirected)
            hook = repository / ".agents" / "skills" / "example" / "block.py"
            hook.write_text(
                "#!/usr/bin/env python3\n"
                "import json, subprocess\n"
                "root = subprocess.run(\n"
                "    ['git', 'rev-parse', '--show-toplevel'],\n"
                "    check=True, capture_output=True, text=True,\n"
                ").stdout.strip()\n"
                "print(json.dumps({'decision': 'block', 'reason': root}))\n",
                encoding="utf-8",
            )
            result = self.run_dispatch(
                repository,
                "claude",
                "PreToolUse",
                extra_env={
                    "GIT_DIR": str(redirected / ".git"),
                    "GIT_WORK_TREE": str(redirected),
                },
            )
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertEqual(response["reason"], str(repository.resolve()))

    def test_git_config_cannot_redirect_repository_hooks_outside_working_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            metadata = base / "metadata"
            external = base / "external"
            metadata.mkdir()
            external.mkdir()
            self.init_repository(metadata)
            self.repo_with_blocking_hook(external)
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(metadata / ".git"),
                    "config",
                    "core.worktree",
                    str(external),
                ],
                text=True,
                capture_output=True,
                env=self.clean_git_environment(),
                check=True,
            )
            result = self.run_dispatch(
                metadata,
                "claude",
                "PreToolUse",
                repository=None,
            )
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertIn("does not contain working directory", response["reason"])
        self.assertNotIn("retry this", response["reason"])

    def test_home_workspace_case_alias_does_not_rediscover_global_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir()
            alias = home.with_name(home.name.upper())
            try:
                same_directory = alias.samefile(home)
            except OSError:
                same_directory = False
            if not same_directory:
                self.skipTest("requires a case-insensitive filesystem")
            self.install_managed_global_skill(home, "behavior-validator")
            result = self.run_dispatch(alias, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_symlinked_agents_home_case_alias_is_not_rediscovered(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            agents_home = base / "global-agents"
            home.mkdir()
            agents_home.mkdir()
            alias = home.with_name(home.name.upper())
            try:
                same_directory = alias.samefile(home)
            except OSError:
                same_directory = False
            if not same_directory:
                self.skipTest("requires a case-insensitive filesystem")
            (home / ".agents").symlink_to(agents_home, target_is_directory=True)
            self.install_managed_global_skill(home, "behavior-validator")
            result = self.run_dispatch(alias, "claude", "PreToolUse", home=home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

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

        def delayed_discovery(_repository_root: Path | None):
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
