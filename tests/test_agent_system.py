import json
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import tomllib
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]


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
            env = {**os.environ, "HOME": str(root / "home")}
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
            self.assertNotIn("code-review@claude-plugins-official", updated)
            self.assertIn('[projects."/workspace"]', updated)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertEqual(tomllib.loads(updated)["notices"][0]["name"], "preserve array table")
            settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["theme"], "dark")
            self.assertNotIn("model", settings)
            self.assertEqual(settings["env"]["KEEP_ME"], "yes")
            self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", settings["env"])
            self.assertEqual(settings["enabledPlugins"], {"useful": True})
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
            self.assertEqual(known, {"useful": {"source": "keep"}})
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
                SYSTEM_ROOT / "bin" / "agent-claude",
            )
            self.assertEqual(
                (home / ".local" / "bin" / "agent-codex").resolve(),
                SYSTEM_ROOT / "bin" / "agent-codex",
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

    def test_standard_launchers_add_remote_control_only_to_interactive_work(self):
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
                [str(SYSTEM_ROOT / "bin" / "agent-claude"), "fix it"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-claude"), "doctor"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-codex"), "fix it"],
                env=env,
                check=True,
            )
            subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-codex"), "doctor"],
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
