from pathlib import Path
import subprocess
import tempfile
import unittest


COMMITTER = Path(__file__).parents[1] / "bin" / "committer"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=check,
    )


class CommitterTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        (repo / "target.txt").write_text("before\n", encoding="utf-8")
        (repo / "other.txt").write_text("before\n", encoding="utf-8")
        nested = repo / "nested"
        nested.mkdir()
        (nested / "existing.txt").write_text("before\n", encoding="utf-8")
        git(repo, "add", "target.txt", "other.txt", "nested/existing.txt")
        git(repo, "commit", "-qm", "initial")
        return repo

    def test_commits_only_named_paths_and_preserves_unrelated_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self.make_repo(Path(temp))
            (repo / "other.txt").write_text("staged\n", encoding="utf-8")
            git(repo, "add", "other.txt")
            (repo / "target.txt").write_text("after\n", encoding="utf-8")
            (repo / "nested" / "new.txt").write_text("new\n", encoding="utf-8")

            result = subprocess.run(
                [str(COMMITTER), "fix: scoped", "target.txt", "nested"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            changed = git(repo, "show", "--format=", "--name-only", "HEAD").stdout.splitlines()
            self.assertEqual(sorted(changed), ["nested/new.txt", "target.txt"])
            self.assertEqual(git(repo, "status", "--short", "--", "other.txt").stdout, "M  other.txt\n")

    def test_rejects_repository_wide_path(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self.make_repo(Path(temp))
            (repo / "target.txt").write_text("after\n", encoding="utf-8")
            result = subprocess.run(
                [str(COMMITTER), "fix: broad", "."],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("repository-wide path is not allowed", result.stderr)


if __name__ == "__main__":
    unittest.main()
