import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
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


class AgentSystemTests(unittest.TestCase):
    def test_skill_catalog_is_small_and_valid(self):
        catalog = json.loads((SYSTEM_ROOT / "system.json").read_text(encoding="utf-8"))
        skills = sorted(path for path in (SYSTEM_ROOT / "skills").iterdir() if path.is_dir())
        self.assertEqual(
            [path.name for path in skills],
            [
                "behavior-validator",
                "capabilities",
                "delegate",
                "fix-issue",
                "handoff",
                "land",
                "maintain-skills",
                "pickup",
                "portfolio",
                "release",
                "review",
            ],
        )
        self.assertEqual([entry["name"] for entry in catalog["skills"]], [path.name for path in skills])
        binary_names = {entry["name"] for entry in catalog["binaries"]}
        self.assertNotIn("agent-claude", binary_names)
        self.assertNotIn("agent-codex", binary_names)
        for skill in skills:
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), skill)
            self.assertIn(f"\nname: {skill.name}\n", text)
            self.assertIn("\ndescription:", text)

    def test_policy_and_skills_do_not_pin_model_identities(self):
        files = [SYSTEM_ROOT / "AGENTS.md", *(SYSTEM_ROOT / "skills").glob("*/SKILL.md")]
        text = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertIsNone(re.search(r"(?<![\w-])--model(?:\s|=)", text.lower()))
        for marker in ("CLAUDE_CODE_SUBAGENT_MODEL", "claude-opus", "claude-sonnet", "gpt-"):
            self.assertNotIn(marker, text.lower())

    def test_dispatcher_translates_blocks_for_each_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git_env = os.environ.copy()
            for name in GIT_DISCOVERY_ENVIRONMENT:
                git_env.pop(name, None)
            subprocess.run(
                ["git", "init", "--quiet", str(root)],
                text=True,
                capture_output=True,
                env=git_env,
                check=True,
            )
            skill = root / ".agents" / "skills" / "fixture"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: fixture\ndescription: Fixture hook.\n---\n\n# Fixture\n",
                encoding="utf-8",
            )
            hook = skill / "block.py"
            hook.write_text(
                '#!/usr/bin/env python3\nimport json\nprint(json.dumps({"decision":"block","reason":"fixture blocked"}))\n',
                encoding="utf-8",
            )
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps({"version": 1, "events": {"PreToolUse": [{"command": ["block.py"]}]}}),
                encoding="utf-8",
            )
            payload = json.dumps({"cwd": str(root), "command": "echo ok"})
            env = {**git_env, "HOME": str(root / "home")}
            env.pop("AGENTS_HOME", None)
            for host, expected in (("claude", "decision"), ("codex", "decision")):
                result = subprocess.run(
                    [str(SYSTEM_ROOT / "hooks" / "dispatch.py"), "--host", host, "PreToolUse"],
                    input=payload,
                    text=True,
                    capture_output=True,
                    env=env,
                    check=True,
                )
                response = json.loads(result.stdout)
                self.assertIn(expected, response)
                self.assertIn("fixture blocked", json.dumps(response))

            cursor = subprocess.run(
                [str(SYSTEM_ROOT / "hooks" / "dispatch.py"), "--host", "cursor", "PreToolUse"],
                input=payload,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(cursor.returncode, 2)
            self.assertEqual(json.loads(cursor.stdout)["permission"], "deny")

    def test_docs_list_reads_summary_and_read_when(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "auth.md").write_text(
                "---\nsummary: Auth ownership\nread_when:\n  - Changing login.\n---\n# Auth\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "docs-list"), str(root)],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("auth.md - Auth ownership", result.stdout)
            self.assertIn("Read when: Changing login.", result.stdout)

    def test_host_config_preserves_unrelated_settings_and_file_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            codex = home / ".codex"
            claude = home / ".claude"
            codex.mkdir()
            claude.mkdir()
            config = codex / "config.toml"
            config.write_text(
                'banner = """literal config text\n[not.a.table]\n"""\n'
                'model = "future-model"\nmodel_reasoning_effort = "high"\nsecret_setting = "preserve"\n\n[features] # keep this comment\nmemories = true\n\n'
                '[plugins."code-review@claude-plugins-official"]\nenabled = true\n\n'
                '[profiles.fast]\nmodel = "profile-model"\nmodel_reasoning_effort = "low"\n\n'
                '[mcp_servers.fixture]\nmodel = "tool-model"\n\n'
                '[projects."/workspace"]\ntrust_level = "trusted"\n\n'
                '[[notices]]\nname = "preserve array table"\n',
                encoding="utf-8",
            )
            config.chmod(0o600)
            (claude / "settings.json").write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "model": "fixed-model",
                        "env": {
                            "ANTHROPIC_DEFAULT_OPUS_MODEL": "fixed-model",
                            "KEEP_ME": "yes",
                        },
                        "enabledPlugins": {
                            "code-review@claude-plugins-official": True,
                            "unused": False,
                            "useful": True,
                        },
                        "permissions": {"allow": ["Read"], "deny": []},
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "custom",
                                    "hooks": [{"type": "command", "command": "custom-claude-stop"}],
                                }
                            ],
                            "Notification": [{"matcher": "", "hooks": []}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (codex / "hooks.json").write_text(
                json.dumps(
                    {
                        "custom": "keep",
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "custom",
                                    "hooks": [{"type": "command", "command": "custom-codex-stop"}],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            cursor = home / ".cursor"
            cursor.mkdir()
            (cursor / "hooks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "custom": "keep",
                        "hooks": {
                            "stop": [{"command": "custom-cursor-stop", "timeout": 5}],
                            "afterFileEdit": [{"command": "custom-after-edit"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            plugins = claude / "plugins"
            plugins.mkdir()
            (plugins / "known_marketplaces.json").write_text(
                json.dumps({"karpathy-skills": {"source": "legacy"}, "useful": {"source": "keep"}}),
                encoding="utf-8",
            )
            subprocess.run(
                ["python3", str(SYSTEM_ROOT / "configure-hosts.py"), "--system-root", str(SYSTEM_ROOT)],
                env={**os.environ, "HOME": str(home)},
                check=True,
            )
            updated = config.read_text(encoding="utf-8")
            self.assertNotIn('model = "future-model"', updated)
            self.assertNotIn('model = "profile-model"', updated)
            self.assertIn('model = "tool-model"', updated)
            self.assertIn('model_reasoning_effort = "high"', updated)
            self.assertIn('secret_setting = "preserve"', updated)
            self.assertIn("[features] # keep this comment", updated)
            self.assertIn("[not.a.table]", updated)
            self.assertIn("[[notices]]", updated)
            self.assertIn('sandbox_mode = "danger-full-access"', updated)
            self.assertIn('approval_policy = "never"', updated)
            self.assertIn("memories = false", updated)
            self.assertIn("code-review@claude-plugins-official", updated)
            self.assertIn('[projects."/workspace"]', updated)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertEqual(tomllib.loads(updated)["notices"][0]["name"], "preserve array table")
            settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["theme"], "dark")
            self.assertNotIn("model", settings)
            self.assertEqual(settings["env"]["KEEP_ME"], "yes")
            self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", settings["env"])
            self.assertEqual(
                settings["enabledPlugins"],
                {
                    "code-review@claude-plugins-official": True,
                    "unused": False,
                    "useful": True,
                },
            )
            self.assertFalse(settings["autoMemoryEnabled"])
            self.assertEqual(settings["permissions"]["defaultMode"], "bypassPermissions")
            self.assertEqual(settings["permissions"]["allow"], ["Read"])
            self.assertTrue(settings["skipDangerousModePermissionPrompt"])
            self.assertIn("custom-claude-stop", json.dumps(settings["hooks"]))
            self.assertIn("Notification", settings["hooks"])
            updated_codex_hooks = json.loads((codex / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_codex_hooks["custom"], "keep")
            self.assertIn("custom-codex-stop", json.dumps(updated_codex_hooks["hooks"]))
            updated_cursor_hooks = json.loads((cursor / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_cursor_hooks["custom"], "keep")
            self.assertIn("custom-cursor-stop", json.dumps(updated_cursor_hooks["hooks"]))
            self.assertIn("afterFileEdit", updated_cursor_hooks["hooks"])
            known = json.loads((plugins / "known_marketplaces.json").read_text(encoding="utf-8"))
            self.assertEqual(
                known,
                {
                    "karpathy-skills": {"source": "legacy"},
                    "useful": {"source": "keep"},
                },
            )
            self.assertTrue((home / ".cursor" / "rules" / "global-engineering.mdc").is_file())

    def test_host_config_repairs_non_object_claude_env(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"env": "stale"}), encoding="utf-8")

            subprocess.run(
                ["python3", str(SYSTEM_ROOT / "configure-hosts.py"), "--system-root", str(SYSTEM_ROOT)],
                env={**os.environ, "HOME": str(home)},
                check=True,
            )

            updated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")

    def test_codex_toml_handles_dotted_features_and_fails_safely_on_inline_model_pins(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                'features."memories" = true\n'
                'profiles.fast.model = "pinned"\n'
                'profiles.fast.model_reasoning_effort = "high"\n'
                'keep = "yes"\n',
                encoding="utf-8",
            )
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            values = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertIs(values["features"]["memories"], False)
            self.assertNotIn("memories", values)
            self.assertEqual(values["keep"], "yes")
            self.assertNotIn("model", values["profiles"]["fast"])
            self.assertEqual(values["profiles"]["fast"]["model_reasoning_effort"], "high")

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            original = 'profiles.fast = { model = "pinned", model_reasoning_effort = "high" }\n'
            config.write_text(original, encoding="utf-8")
            result = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inline tables", result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertFalse((home / ".agents" / "AGENTS.md").exists())

    def test_installer_refuses_symlinked_shell_json_and_toml_configuration(self):
        cases = (
            (Path(".zshrc"), "# keep shell\n"),
            (Path(".claude/settings.json"), "{}\n"),
            (Path(".codex/config.toml"), 'keep = "yes"\n'),
        )
        for relative, original in cases:
            with self.subTest(path=str(relative)), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                home = base / "home"
                home.mkdir()
                target = base / "managed-dotfile"
                target.write_text(original, encoding="utf-8")
                destination = home / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(target)
                result = subprocess.run(
                    ["bash", str(SYSTEM_ROOT / "install.sh")],
                    env={**os.environ, "HOME": str(home)},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Host-configuration preflight failed", result.stderr)
                self.assertTrue(destination.is_symlink())
                self.assertEqual(target.read_text(encoding="utf-8"), original)
                self.assertFalse((home / ".agents" / "AGENTS.md").exists())

    def test_installer_wires_an_explicit_host_integration(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            integration = base / "vm-host"
            home.mkdir()
            (integration / "bin").mkdir(parents=True)
            (integration / "shell").mkdir()
            for name in ("agent-claude", "agent-codex"):
                helper = integration / "bin" / name
                helper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                helper.chmod(0o755)
            shell_adapter = integration / "shell" / "default-invocations.sh"
            shell_adapter.write_text(
                "claude() { :; }\ncodex() { :; }\n",
                encoding="utf-8",
            )
            shell_rc = home / ".zshrc"
            shell_rc.write_text("# keep local shell config\n", encoding="utf-8")
            shell_adapter.chmod(0)
            rejected = subprocess.run(
                [
                    "bash",
                    str(SYSTEM_ROOT / "install.sh"),
                    "--host-integration",
                    str(integration),
                ],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("not readable", rejected.stderr)
            self.assertEqual(shell_rc.read_text(encoding="utf-8"), "# keep local shell config\n")
            self.assertFalse((home / ".agents" / "AGENTS.md").exists())
            shell_adapter.chmod(0o644)
            subprocess.run(
                [
                    "bash",
                    str(SYSTEM_ROOT / "install.sh"),
                    "--host-integration",
                    str(integration),
                ],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            config = json.loads((home / ".agents" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(config["hostIntegrationRoot"]), integration.resolve())
            self.assertEqual(
                (home / ".agents" / "bin" / "agent-codex").resolve(),
                (integration / "bin" / "agent-codex").resolve(),
            )
            doctor = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            shell_adapter.unlink()
            damaged = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(damaged.returncode, 0)
            self.assertIn("default invocation adapter", damaged.stderr)

    def test_installer_migrates_only_an_exact_clean_legacy_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            legacy = base / "legacy-system"
            home.mkdir()
            shutil.copytree(
                SYSTEM_ROOT,
                legacy,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            shutil.copy2(legacy / "host" / "local" / "bin" / "agent-claude", legacy / "bin")
            shutil.copy2(legacy / "host" / "local" / "bin" / "agent-codex", legacy / "bin")
            (legacy / "shell").mkdir(exist_ok=True)
            shutil.copy2(
                legacy / "host" / "local" / "shell" / "default-invocations.sh",
                legacy / "shell",
            )
            catalog_path = legacy / "system.json"
            legacy_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            legacy_catalog["skills"] = [
                skill for skill in legacy_catalog["skills"] if skill["name"] != "release"
            ]
            legacy_catalog["skills"].append({"name": "legacy-task", "command": True})
            legacy_catalog["binaries"] = [
                binary
                for binary in legacy_catalog["binaries"]
                if binary["name"] != "agent-repo-adopt"
            ]
            legacy_catalog["binaries"].append(
                {"name": "legacy-tool", "source": "bin/legacy-tool"}
            )
            catalog_path.write_text(json.dumps(legacy_catalog), encoding="utf-8")
            legacy_skill = legacy / "skills" / "legacy-task"
            legacy_skill.mkdir()
            (legacy_skill / "SKILL.md").write_text(
                "---\nname: legacy-task\ndescription: legacy fixture\n---\n",
                encoding="utf-8",
            )
            legacy_tool = legacy / "bin" / "legacy-tool"
            legacy_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            legacy_tool.chmod(0o755)
            subprocess.run(["git", "init", "-q", str(legacy)], check=True)
            subprocess.run(["git", "-C", str(legacy), "config", "user.name", "Fixture"], check=True)
            subprocess.run(
                ["git", "-C", str(legacy), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(["git", "-C", str(legacy), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(legacy), "commit", "-q", "-m", "legacy"], check=True)

            env = {**os.environ, "HOME": str(home)}
            subprocess.run(
                [
                    "bash",
                    str(legacy / "install.sh"),
                    "--coordination-repo",
                    str(legacy),
                    "--host-integration",
                    str(legacy),
                ],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            (home / ".agents" / "managed-install.json").unlink()
            settings_path = home / ".claude" / "settings.json"
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["keepUserSetting"] = True
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            cursor_command = home / ".cursor" / "commands" / "legacy-task.md"
            legacy_command = cursor_command.read_text(encoding="utf-8")
            cursor_command.write_text("user-owned replacement\n", encoding="utf-8")

            migrate = [
                "bash",
                str(SYSTEM_ROOT / "install.sh"),
                "--coordination-repo",
                str(legacy),
                "--migrate-from-system-root",
                str(legacy),
            ]
            rejected = subprocess.run(migrate, env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unowned or modified legacy destination", rejected.stderr)
            self.assertEqual(
                (home / ".agents" / "AGENTS.md").resolve(),
                (legacy / "AGENTS.md").resolve(),
            )
            cursor_command.write_text(legacy_command, encoding="utf-8")

            ignore_path = legacy / ".gitignore"
            ignore_path.write_text("ignored-payload.py\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(legacy), "add", ".gitignore"], check=True
            )
            subprocess.run(
                ["git", "-C", str(legacy), "commit", "-q", "-m", "ignore fixture payload"],
                check=True,
            )
            ignored_dir = legacy_skill / "scripts"
            ignored_dir.mkdir()
            ignored_payload = ignored_dir / "ignored-payload.py"
            ignored_payload.write_text("raise SystemExit(1)\n", encoding="utf-8")
            rejected_ignored = subprocess.run(
                migrate, env=env, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(rejected_ignored.returncode, 0)
            self.assertIn("must be tracked and clean", rejected_ignored.stderr)
            self.assertEqual(
                (home / ".agents" / "AGENTS.md").resolve(),
                (legacy / "AGENTS.md").resolve(),
            )
            ignored_payload.unlink()
            ignored_dir.rmdir()

            subprocess.run(
                ["git", "-C", str(legacy), "rm", "--cached", "bin/legacy-tool"],
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(legacy), "commit", "-q", "-m", "untrack legacy tool"],
                check=True,
            )
            rejected_source = subprocess.run(
                migrate, env=env, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(rejected_source.returncode, 0)
            self.assertIn("untracked required files", rejected_source.stderr)
            self.assertEqual(
                (home / ".agents" / "AGENTS.md").resolve(),
                (legacy / "AGENTS.md").resolve(),
            )
            subprocess.run(
                ["git", "-C", str(legacy), "add", "bin/legacy-tool"], check=True
            )
            subprocess.run(
                ["git", "-C", str(legacy), "commit", "-q", "-m", "track legacy tool"],
                check=True,
            )

            migrated = subprocess.run(migrate, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            self.assertEqual((home / ".agents" / "AGENTS.md").resolve(), SYSTEM_ROOT / "AGENTS.md")
            self.assertEqual(
                (home / ".agents" / "bin" / "agent-codex").resolve(),
                SYSTEM_ROOT / "host" / "local" / "bin" / "agent-codex",
            )
            manifest = json.loads(
                (home / ".agents" / "managed-install.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["sourceRoot"], str(SYSTEM_ROOT))
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertTrue(settings["keepUserSetting"])
            self.assertFalse((home / ".agents" / "skills" / "legacy-task").exists())
            self.assertFalse((home / ".cursor" / "commands" / "legacy-task.md").exists())
            self.assertFalse((home / ".agents" / "bin" / "legacy-tool").exists())
            self.assertFalse((home / ".local" / "bin" / "legacy-tool").exists())
            self.assertEqual(
                (home / ".agents" / "skills" / "release").resolve(),
                SYSTEM_ROOT / "skills" / "release",
            )
            self.assertEqual(
                (home / ".agents" / "bin" / "agent-repo-adopt").resolve(),
                SYSTEM_ROOT / "bin" / "agent-repo-adopt",
            )
            doctor = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)

    def test_installer_wires_all_hosts(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual((home / ".codex" / "AGENTS.md").resolve(), SYSTEM_ROOT / "AGENTS.md")
            self.assertEqual((home / ".claude" / "CLAUDE.md").resolve(), SYSTEM_ROOT / "AGENTS.md")
            self.assertEqual(
                (home / ".agents" / "skills" / "review").resolve(),
                SYSTEM_ROOT / "skills" / "review",
            )
            self.assertTrue((home / ".cursor" / "commands" / "pickup.md").is_file())
            self.assertTrue((home / ".cursor" / "commands" / "delegate.md").is_file())
            self.assertTrue((home / ".cursor" / "commands" / "land.md").is_file())
            self.assertEqual(
                (home / ".local" / "bin" / "committer").resolve(),
                SYSTEM_ROOT / "bin" / "committer",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-trash").resolve(),
                SYSTEM_ROOT / "bin" / "agent-trash",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-claude").resolve(),
                SYSTEM_ROOT / "host" / "local" / "bin" / "agent-claude",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-codex").resolve(),
                SYSTEM_ROOT / "host" / "local" / "bin" / "agent-codex",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-skill-audit").resolve(),
                SYSTEM_ROOT / "skills" / "maintain-skills" / "scripts" / "skill-audit.py",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-capabilities").resolve(),
                SYSTEM_ROOT / "skills" / "capabilities" / "scripts" / "agent-capabilities.py",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-repo-inventory").resolve(),
                SYSTEM_ROOT / "skills" / "portfolio" / "scripts" / "repo-inventory.py",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-lease").resolve(),
                SYSTEM_ROOT / "skills" / "portfolio" / "scripts" / "agent-lease.py",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-autoreview").resolve(),
                SYSTEM_ROOT / "skills" / "review" / "scripts" / "agent-autoreview.py",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-session-recover").resolve(),
                SYSTEM_ROOT / "skills" / "pickup" / "scripts" / "agent-session-recover.py",
            )
            cursor_hooks = json.loads((home / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(cursor_hooks["version"], 1)
            config = json.loads((home / ".agents" / "config.json").read_text(encoding="utf-8"))
            for raw_path in config["shellRcPaths"]:
                text = Path(raw_path).read_text(encoding="utf-8")
                self.assertEqual(text.count("# >>> global agent invocation defaults >>>"), 1)
            self.assertFalse((home / ".profile").exists())
            doctor = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertEqual(Path(config["coordinationRepo"]), SYSTEM_ROOT)
            managed = json.loads(
                (home / ".agents" / "managed-install.json").read_text(encoding="utf-8")
            )
            self.assertEqual(managed["sourceRoot"], str(SYSTEM_ROOT))
            self.assertEqual(managed["orphanedPaths"], [])
            self.assertEqual(
                Path(config["hostIntegrationRoot"]),
                SYSTEM_ROOT / "host" / "local",
            )

    def test_local_launchers_add_remote_control_only_to_interactive_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "calls.log"
            stub = root / "native-agent"
            stub.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$AGENT_TEST_LOG"\n',
                encoding="utf-8",
            )
            stub.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(root),
                "AGENT_TEST_LOG": str(log),
                "AGENT_CLAUDE_BIN": str(stub),
                "AGENT_CODEX_BIN": str(stub),
                "AGENT_CODEX_IGNORE_DESKTOP_APP_SERVER": "1",
            }

            subprocess.run(
                [str(SYSTEM_ROOT / "host" / "local" / "bin" / "agent-claude"), "fix it"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "host" / "local" / "bin" / "agent-claude"), "doctor"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "host" / "local" / "bin" / "agent-codex"), "fix it"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "host" / "local" / "bin" / "agent-codex"), "doctor"],
                env=env,
                check=True,
            )

            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                calls,
                [
                    "--remote-control --permission-mode bypassPermissions fix it",
                    "doctor",
                    "remote-control start --json",
                    "--dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --search fix it",
                    "doctor",
                ],
            )

    def test_installer_refuses_unowned_and_modified_managed_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            collision = home / ".claude" / "skills" / "review"
            collision.mkdir(parents=True)
            marker = collision / "owned-by-user.txt"
            marker.write_text("keep\n", encoding="utf-8")
            first = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(first.returncode, 0)
            self.assertIn("unowned or modified destination", first.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((home / ".agents" / "AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            command = home / ".cursor" / "commands" / "review.md"
            command.write_text("user replacement\n", encoding="utf-8")
            second = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("unowned or modified destination", second.stderr)
            self.assertEqual(command.read_text(encoding="utf-8"), "user replacement\n")

    def test_reinstall_preserves_coordination_repo_and_effective_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            profile = home / ".profile"
            profile.write_text('export KEEP_PROFILE="yes"\n', encoding="utf-8")
            coordination = root / "coordination"
            subprocess.run(["git", "init", "-q", str(coordination)], check=True)

            subprocess.run(
                [
                    "bash",
                    str(SYSTEM_ROOT / "install.sh"),
                    "--coordination-repo",
                    str(coordination),
                ],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )

            config = json.loads((home / ".agents" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(config["coordinationRepo"]), coordination.resolve())
            self.assertIn(str(profile.resolve()), config["shellRcPaths"])
            self.assertIn('export KEEP_PROFILE="yes"', profile.read_text(encoding="utf-8"))
            self.assertFalse((home / ".bash_profile").exists())
            self.assertFalse((home / ".bash_login").exists())
            doctor = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)

    def test_installer_adopts_only_the_exact_legacy_generated_cursor_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            old_system = root / "old-system"
            home.mkdir()
            old_system.mkdir()
            old_policy = "# Old global policy\n"
            (old_system / "AGENTS.md").write_text(old_policy, encoding="utf-8")
            rule = home / ".cursor" / "rules" / "global-engineering.mdc"
            rule.parent.mkdir(parents=True)
            rule.write_text(
                "---\n"
                "description: Canonical global engineering policy\n"
                "alwaysApply: true\n"
                "---\n\n"
                "Generated from the canonical agent system. Edit the source, then rerun the installer.\n\n"
                + old_policy,
                encoding="utf-8",
            )
            manifest = home / ".agents" / "managed-install.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"version": 1, "sourceRoot": str(old_system), "paths": {}}),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Global Engineering System", rule.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            rule = home / ".cursor" / "rules" / "global-engineering.mdc"
            rule.parent.mkdir(parents=True)
            rule.write_text("user-owned rule\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(rule.read_text(encoding="utf-8"), "user-owned rule\n")

    def test_installer_prunes_only_unchanged_retired_managed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            manifest_path = home / ".agents" / "managed-install.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            retired_link = home / ".local" / "bin" / "retired-helper"
            retired_link.symlink_to(SYSTEM_ROOT / "bin" / "docs-list")
            retired_copy = home / ".cursor" / "commands" / "retired.md"
            retired_copy.write_text("retired managed content\n", encoding="utf-8")
            modified_copy = home / ".cursor" / "commands" / "modified-retired.md"
            modified_copy.write_text("user changed this\n", encoding="utf-8")
            outside_copy = home / "outside-managed-roots.md"
            outside_copy.write_text("retired managed content\n", encoding="utf-8")
            manifest["paths"].update(
                {
                    str(retired_link): {
                        "kind": "symlink",
                        "target": str(SYSTEM_ROOT / "bin" / "docs-list"),
                    },
                    str(retired_copy): {
                        "kind": "copy",
                        "sha256": hashlib.sha256(retired_copy.read_bytes()).hexdigest(),
                    },
                    str(modified_copy): {
                        "kind": "copy",
                        "sha256": hashlib.sha256(b"original managed content\n").hexdigest(),
                    },
                    str(outside_copy): {
                        "kind": "copy",
                        "sha256": hashlib.sha256(outside_copy.read_bytes()).hexdigest(),
                    },
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            second_install = subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=True,
            )
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            detail = f"{second_install.stderr}\n{json.dumps(updated, indent=2)}"
            self.assertFalse(retired_link.exists(), detail)
            self.assertFalse(retired_copy.exists(), detail)
            self.assertTrue(modified_copy.exists())
            self.assertTrue(outside_copy.exists())
            self.assertEqual(
                updated["orphanedPaths"],
                sorted([str(modified_copy), str(outside_copy)]),
            )


if __name__ == "__main__":
    unittest.main()
