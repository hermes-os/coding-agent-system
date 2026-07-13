import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "portfolio" / "scripts" / "repo-inventory.py"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )


class RepoInventoryTests(unittest.TestCase):
    def test_reports_dirty_state_and_active_plan_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "projects" / "demo"
            repo.mkdir(parents=True)
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "Test")
            (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
            git(repo, "add", "tracked.txt")
            git(repo, "commit", "-qm", "initial")
            (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
            (repo / "new.txt").write_text("new\n", encoding="utf-8")
            plan = repo / "docs" / "plan" / "active.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Active\n", encoding="utf-8")

            result = subprocess.run(
                [str(SCRIPT), "--root", str(root / "projects"), "--max-depth", "2", "--json"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(len(report["repositories"]), 1)
            item = report["repositories"][0]
            self.assertEqual(item["path"], str(repo.resolve()))
            self.assertEqual(item["unstaged"], 1)
            self.assertEqual(item["untracked"], 2)
            self.assertEqual(item["plans"], ["docs/plan/active.md"])


if __name__ == "__main__":
    unittest.main()
