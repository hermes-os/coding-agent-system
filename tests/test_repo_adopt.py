from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
REPO_ADOPT = SYSTEM_ROOT / "bin" / "agent-repo-adopt"
POINTER = "READ ~/.agents/AGENTS.md BEFORE ANYTHING (skip if missing).\n"


class RepositoryAdoptTests(unittest.TestCase):
    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text(POINTER + "\n# Fixture\n", encoding="utf-8")

    def run_adopt(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(REPO_ADOPT), "--repo", str(root), "--allow-unpublished", *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_writes_exact_sha_workflow_and_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            result = self.run_adopt(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "CLAUDE.md").is_symlink())
            workflow = root / ".github" / "workflows" / "agent-repository-check.yml"
            content = workflow.read_text(encoding="utf-8")
            head = subprocess.run(
                ["git", "-C", str(SYSTEM_ROOT), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            self.assertIn(f"hermes-os/coding-agent-system@{head}", content)
            check = self.run_adopt(root, "--check")
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_refuses_to_replace_unmanaged_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            workflow = root / ".github" / "workflows" / "agent-repository-check.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: User workflow\n", encoding="utf-8")
            result = self.run_adopt(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to replace unmanaged workflow", result.stderr)
            self.assertEqual(workflow.read_text(encoding="utf-8"), "name: User workflow\n")


if __name__ == "__main__":
    unittest.main()
