from __future__ import annotations

from pathlib import Path
import runpy
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

    def test_rejects_symlinked_workflow_ancestors_without_external_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            external = base / "external"
            root.mkdir()
            external.mkdir()
            self.init_repo(root)
            (root / ".github").symlink_to(external, target_is_directory=True)
            result = self.run_adopt(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workflow ancestor must not be a symlink", result.stderr)
            self.assertFalse((external / "workflows" / "agent-repository-check.yml").exists())

    def test_publication_guard_uses_only_the_canonical_origin_and_requires_action(self):
        functions = runpy.run_path(str(REPO_ADOPT))
        require_published = functions["require_published"]
        repository = "hermes-os/coding-agent-system"

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            remote = base / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            (source / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "initial"], check=True)
            no_action = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(source), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(source), "push", "-q", "origin", "main"], check=True)
            canonical_url = "https://github.com/hermes-os/coding-agent-system.git"
            subprocess.run(
                ["git", "-C", str(source), "config", "remote.origin.url", canonical_url],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "config",
                    f"url.file://{remote}.insteadOf",
                    canonical_url,
                ],
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "no root action.yml"):
                require_published(source, repository, no_action)

            (source / "action.yml").write_text(
                "name: Fixture\ndescription: Fixture action\nruns:\n  using: composite\n  steps: []\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(source), "add", "action.yml"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "add action"], check=True)
            published = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(source), "push", "-q", "origin", "main"], check=True)
            require_published(source, repository, published)

            (source / "README.md").write_text("unpublished\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "unpublished"], check=True)
            unpublished = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            secondary = base / "secondary.git"
            subprocess.run(["git", "init", "-q", "--bare", str(secondary)], check=True)
            subprocess.run(["git", "-C", str(source), "remote", "add", "secondary", str(secondary)], check=True)
            subprocess.run(["git", "-C", str(source), "push", "-q", "secondary", "main"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "update-ref", "refs/remotes/origin/stale", unpublished],
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "not published on origin"):
                require_published(source, repository, unpublished)

            subprocess.run(
                ["git", "-C", str(source), "config", "remote.origin.url", "git@github.com:someone/fork.git"],
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "does not match catalog repository"):
                require_published(source, repository, published)


if __name__ == "__main__":
    unittest.main()
