import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).parents[1]
AUDIT = SYSTEM_ROOT / "skills" / "maintain-skills" / "scripts" / "skill-audit.py"


class SkillAuditTests(unittest.TestCase):
    def test_canonical_catalog_passes_strict_audit(self):
        result = subprocess.run(
            [str(AUDIT), "--root", str(SYSTEM_ROOT / "skills"), "--check", "--strict", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["uniqueSkillCount"], 11)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_reports_invalid_skill_and_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skills"
            skill = root / "broken"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: wrong-name\ndescription: Broken fixture.\n---\n[TODO: fix]\n",
                encoding="utf-8",
            )
            (skill / "hooks.json").write_text(
                json.dumps({"events": {"Stop": [{"command": ["../escape.sh"]}]}}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(AUDIT), "--root", str(root), "--check", "--strict", "--json"],
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("TODO" in error for error in report["errors"]))
            self.assertTrue(any("escapes the skill" in error for error in report["errors"]))
            self.assertTrue(any("differs from canonical folder" in warning for warning in report["warnings"]))

    def test_live_mode_does_not_assume_plugin_caches_are_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            live = home / ".agents" / "skills" / "live"
            cached = home / ".codex" / "plugins" / "cache" / "plugin" / "skills" / "cached"
            for path, name in ((live, "live"), (cached, "cached")):
                path.mkdir(parents=True)
                (path / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Fixture {name}.\n---\n# {name}\n",
                    encoding="utf-8",
                )
            result = subprocess.run(
                [str(AUDIT), "--live", "--json"],
                env={"HOME": str(home), "PATH": os.environ.get("PATH", "")},
                cwd=home,
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads(result.stdout)
            self.assertEqual([skill["name"] for skill in report["skills"]], ["live"])

    def test_codex_visible_probe_measures_rendered_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill_root = root / "skills"
            skill = skill_root / "fixture"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: fixture\ndescription: Fixture skill.\n---\n# Fixture\n",
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            codex = bin_dir / "codex"
            prompt = (
                "<skills_instructions>\n### Available skills\n"
                "- first: First description. (file: /tmp/first/SKILL.md)\n"
                "- plugin:second: Second description. (file: r1/second/SKILL.md)\n"
                "</skills_instructions>"
            )
            codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                f"print(json.dumps([{{'type':'message','content':[{{'text':{prompt!r}}}]}}]))\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            result = subprocess.run(
                [str(AUDIT), "--root", str(skill_root), "--codex-visible", "--json"],
                env={"HOME": str(root), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["codexVisibleSkillCount"], 2)
            self.assertGreater(report["codexVisibleMetadataTokensEstimate"], 0)
            self.assertEqual(report["codexVisibleSkills"][1]["name"], "plugin:second")


if __name__ == "__main__":
    unittest.main()
