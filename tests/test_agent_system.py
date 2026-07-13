import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]


class AgentSystemTests(unittest.TestCase):
    def test_skill_catalog_is_small_and_valid(self):
        skills = sorted(path for path in (SYSTEM_ROOT / "skills").iterdir() if path.is_dir())
        self.assertEqual(
            [path.name for path in skills],
            ["behavior-validator", "delegate", "handoff", "pickup", "review"],
        )
        for skill in skills:
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), skill)
            self.assertIn(f"\nname: {skill.name}\n", text)
            self.assertIn("\ndescription:", text)

    def test_policy_and_skills_do_not_pin_model_identities(self):
        files = [SYSTEM_ROOT / "AGENTS.md", *(SYSTEM_ROOT / "skills").glob("*/SKILL.md")]
        text = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for marker in ("--model", "CLAUDE_CODE_SUBAGENT_MODEL", "claude-opus", "claude-sonnet", "gpt-"):
            self.assertNotIn(marker, text.lower())

    def test_dispatcher_translates_blocks_for_each_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / ".agents" / "skills" / "fixture"
            skill.mkdir(parents=True)
            hook = skill / "block.py"
            hook.write_text(
                '#!/usr/bin/env python3\nimport json\nprint(json.dumps({"decision":"block","reason":"fixture blocked"}))\n',
                encoding="utf-8",
            )
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps({"events": {"PreToolUse": [{"command": ["block.py"]}]}}),
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
                'model = "future-model"\nmodel_reasoning_effort = "high"\nsecret_setting = "preserve"\n\n[features]\nmemories = true\n\n'
                '[plugins."code-review@claude-plugins-official"]\nenabled = true\n\n'
                '[profiles.fast]\nmodel = "profile-model"\nmodel_reasoning_effort = "low"\n\n'
                '[mcp_servers.fixture]\nmodel = "tool-model"\n\n'
                '[projects."/workspace"]\ntrust_level = "trusted"\n',
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
            self.assertIn("memories = false", updated)
            self.assertNotIn("code-review@claude-plugins-official", updated)
            self.assertIn('[projects."/workspace"]', updated)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["theme"], "dark")
            self.assertNotIn("model", settings)
            self.assertEqual(settings["env"]["KEEP_ME"], "yes")
            self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", settings["env"])
            self.assertEqual(settings["enabledPlugins"], {"useful": True})
            self.assertFalse(settings["autoMemoryEnabled"])
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
            cursor_hooks = json.loads((home / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(cursor_hooks["version"], 1)
            doctor = subprocess.run(
                [str(SYSTEM_ROOT / "bin" / "agent-system-doctor"), "--home", str(home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)

    def test_prune_removes_known_legacy_memory_and_gate_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            legacy_files = [
                home / ".ai" / "scripts" / "quality-gate.sh",
                home / "ClaudeVault" / "personas" / "Cal" / "journal.md",
                home / ".claude" / ".git" / "config",
                home / ".claude" / "scripts" / "tc-hook.log",
                home / ".claude" / "settings.json.bak.legacy",
                home / ".claude" / "settings.json.orig",
            ]
            for path in legacy_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("legacy\n", encoding="utf-8")

            subprocess.run(
                ["bash", str(SYSTEM_ROOT / "install.sh")],
                env={**os.environ, "HOME": str(home), "AGENT_SYSTEM_PRUNE_LEGACY": "1"},
                text=True,
                capture_output=True,
                check=True,
            )

            for path in legacy_files:
                self.assertFalse(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
