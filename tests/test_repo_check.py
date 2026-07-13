from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
REPO_CHECK = SYSTEM_ROOT / "bin" / "agent-repo-check"
POINTER = "READ ~/.agents/AGENTS.md BEFORE ANYTHING (skip if missing).\n"


class RepositoryCheckTests(unittest.TestCase):
    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text(POINTER + "\n# Fixture\n", encoding="utf-8")
        (root / "CLAUDE.md").symlink_to("AGENTS.md")

    def run_check(self, root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [str(REPO_CHECK), "--repo", str(root), "--strict", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(result.stdout)

    def test_valid_repository_contract_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            plan = root / "docs" / "plan" / "fixture.md"
            plan.parent.mkdir(parents=True)
            sections = "\n".join(f"## {name}\n\nFixture.\n" for name in (
                "Status",
                "Problem",
                "Goals",
                "Non-Goals",
                "Decisions",
                "Milestones",
                "Verification",
                "Open Questions",
            ))
            plan.write_text(
                "---\nsummary: Fixture plan.\nread_when:\n  - Testing repository checks.\n---\n\n"
                "# Fixture\n\n"
                + sections,
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["warnings"], [])

    def test_rejects_duplicate_instructions_secrets_bad_plans_and_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            (root / "CODEX.md").write_text("duplicate policy\n", encoding="utf-8")
            (root / ".env.production").write_text("SECRET=value\n", encoding="utf-8")
            plan = root / "docs" / "plan" / "broken.md"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                "---\nsummary: Broken plan.\nread_when:\n  - Testing failures.\n---\n"
                "# Broken\n\n## Status\n\nActive.\n",
                encoding="utf-8",
            )
            skill = root / ".agents" / "skills" / "broken"
            hook = skill / "hooks" / "check.sh"
            hook.parent.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: broken\ndescription: Broken fixture.\n---\n# Broken\n",
                encoding="utf-8",
            )
            hook.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps({"version": 2, "events": {"Stop": [{"command": ["hooks/check.sh"]}]}}),
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(root), "add", "-Af"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            joined = "\n".join(report["errors"])
            self.assertIn("host-specific instruction", joined)
            self.assertIn("credential-shaped", joined)
            self.assertIn("missing plan sections", joined)
            self.assertIn("repository skill audit failed", joined)

    def test_product_system_json_does_not_bypass_global_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "system.json").write_text("{}\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Product\n", encoding="utf-8")
            (root / "CLAUDE.md").symlink_to("AGENTS.md")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("canonical global pointer" in error for error in report["errors"]))

    def test_rejects_managed_root_and_nested_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.init_repo(root)
            external_docs = base / "external-docs"
            external_docs.mkdir()
            (external_docs / "outside.md").write_text("outside\n", encoding="utf-8")
            (root / "docs").symlink_to(external_docs, target_is_directory=True)
            agents = root / ".agents"
            agents.mkdir()
            (agents / "skills").symlink_to(base, target_is_directory=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            joined = "\n".join(report["errors"])
            self.assertIn("documentation path must not be a symlink", joined)
            self.assertIn("repository skill path must not be a symlink", joined)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.init_repo(root)
            skill = root / ".agents" / "skills" / "fixture"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: fixture\ndescription: Fixture skill.\n---\n",
                encoding="utf-8",
            )
            (skill / "references").symlink_to(base, target_is_directory=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("repository skill path" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
