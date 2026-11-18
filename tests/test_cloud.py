"""cloud/: the Red Acre cloud environment's setup script, and github-sync.

github-sync runs against two local bare repositories that play the Git server
and GitHub.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "cloud" / "red-acre.sh"
SYNC = ROOT / "cloud" / "github-sync"
AGREEMENT = ROOT / "working-agreement.md"
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, check=True, text=True, capture_output=True
    ).stdout.strip()


class SetupScriptTest(unittest.TestCase):
    def test_it_writes_the_working_agreement_as_it_is(self):
        embedded = re.search(r"^        cat <<'AGREEMENT'\n(.*?)^AGREEMENT$", SETUP.read_text(), re.S | re.M)
        self.assertIsNotNone(embedded)
        self.assertEqual(
            embedded.group(1),
            AGREEMENT.read_text(),
            "copy working-agreement.md into cloud/red-acre.sh, then load the script in the Claude app again",
        )

    def test_the_app_accepts_it(self):
        subprocess.run(["bash", "-n", str(SETUP)], check=True)
        self.assertLess(SETUP.stat().st_size, 64 * 1024)  # the largest file the app loads


class GithubSyncTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        for side in ("forge", "github"):
            git("init", "-q", "--bare", "-b", "main", str(self.temp / side / "game.git"))
        self.work = self.temp / "work"
        git("init", "-q", "-b", "main", str(self.work))
        self.commit("one")
        self.push("forge", "main")
        self.push("github", "main")

    def commit(self, message):
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)

    def drop_last_commit(self):
        git("reset", "-q", "--hard", "HEAD~1", cwd=self.work)

    def push(self, side, refspec):
        git("push", "-q", "--force", str(self.temp / side / "game.git"), refspec, cwd=self.work)

    def refs(self, side):
        lines = git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.temp / side / "game.git")
        return dict(line.split() for line in lines.splitlines())

    def sync(self):
        result = subprocess.run(
            [str(SYNC), "game"],
            text=True,
            capture_output=True,
            env={
                **GIT_ENV,
                "GITHUB_SYNC_FORGE": str(self.temp / "forge"),
                "GITHUB_SYNC_GITHUB": str(self.temp / "github"),
                "GITHUB_SYNC_CACHE": str(self.temp / "cache"),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_branches_only_github_has_are_kept(self):
        cloud = self.commit("a cloud session's work")
        self.push("github", "HEAD:refs/heads/claude/fix-the-gate")
        self.drop_last_commit()
        landed = self.commit("landed on the Git server")
        git("tag", "v1", cwd=self.work)
        self.push("forge", "main")
        self.push("forge", "v1")
        self.sync()
        github = self.refs("github")
        self.assertEqual(github["refs/heads/claude/fix-the-gate"], cloud)
        self.assertEqual(github["refs/heads/main"], landed)
        self.assertEqual(github["refs/tags/v1"], landed)

    def test_commits_only_github_has_on_a_branch_are_kept_as_rescue(self):
        merged = self.commit("a pull request merged on GitHub")
        self.push("github", "main")
        self.drop_last_commit()
        landed = self.commit("landed on the Git server")
        self.push("forge", "main")
        first = self.sync()
        github = self.refs("github")
        self.assertEqual(github["refs/heads/main"], landed)
        self.assertEqual(github[f"refs/heads/rescue/main-{merged[:12]}"], merged)
        self.assertIn(f"rescue/main-{merged[:12]}", first.stderr)

        second = self.sync()
        self.assertEqual(second.stderr, "")
        self.assertEqual(self.refs("github"), github)

    def test_the_git_servers_claude_branches_are_not_pushed(self):
        self.commit("a cloud branch brought to the Git server")
        self.push("forge", "HEAD:refs/heads/claude/fix-the-gate")
        self.sync()
        self.assertNotIn("refs/heads/claude/fix-the-gate", self.refs("github"))


if __name__ == "__main__":
    unittest.main()
