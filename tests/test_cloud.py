"""cloud/: the cloud environments' setup scripts, their loader, and github-sync.

github-sync runs against two local bare repositories that play the Git server
and GitHub.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"
SCRIPTS = sorted(path for path in CLOUD.glob("*.sh") if path.name != "common.sh")
SYNC = CLOUD / "github-sync"
AGREEMENT = ROOT / "working-agreement.md"
PUBLIC = {"marquee", "nomad"}  # public on GitHub
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
    def loaded(self, script):
        """The files as the loader lays them out, with the script's last line
        (`setup <step>...`) cut to its instructions step, and a home of its own."""
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp)
        (temp / "cloud").mkdir()
        (temp / "home").mkdir()
        shutil.copy(CLOUD / "common.sh", temp / "cloud")
        shutil.copy(AGREEMENT, temp)
        lines = script.read_text().rstrip("\n").split("\n")
        self.assertTrue(lines[-1].startswith("setup "), f"{script.name} ends with `setup <step>...`")
        (temp / "cloud" / script.name).write_text("\n".join(lines[:-1] + ["instructions"]) + "\n")
        return temp

    def test_each_writes_the_cloud_rules_its_notes_and_the_working_agreement(self):
        for script in SCRIPTS:
            with self.subTest(script.name):
                temp = self.loaded(script)
                subprocess.run(
                    ["bash", str(temp / "cloud" / script.name)],
                    env={**os.environ, "HOME": str(temp / "home")},
                    check=True,
                )
                written = (temp / "home" / ".claude" / "CLAUDE.md").read_text()
                self.assertTrue(written.startswith("# In a cloud session\n"))
                self.assertIn("\n## ", written.split("# Working agreement")[0], "the repository's notes")
                self.assertTrue(written.endswith(AGREEMENT.read_text()))

    def test_the_public_repositories_commit_as_the_noreply_identity(self):
        for script in SCRIPTS:
            with self.subTest(script.name):
                last = script.read_text().rstrip("\n").split("\n")[-1]
                self.assertEqual("public_identity" in last.split(), script.stem in PUBLIC)

    def test_they_parse(self):
        for script in [*SCRIPTS, CLOUD / "common.sh"]:
            with self.subTest(script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)

    def test_they_download_only_from_hosts_the_cloud_network_allows(self):
        # From the default ("Trusted") allowlist in the Claude Code docs. uv's
        # Pythons and GitHub release files come through github.com's
        # *.githubusercontent.com hosts, and micromamba's packages from
        # conda.anaconda.org; both are on it.
        allowed = {
            "github.com", "raw.githubusercontent.com", "registry.npmjs.org", "static.rust-lang.org",
            "conda.anaconda.org", "storage.googleapis.com", "pypi.org", "files.pythonhosted.org",
        }
        for script in [*SCRIPTS, CLOUD / "common.sh", CLOUD / "app-script"]:
            with self.subTest(script.name):
                hosts = set(re.findall(r"https://([^/\s\"']+)", script.read_text()))
                self.assertLessEqual(hosts, allowed)

    def test_shell_env_puts_its_lines_first_once(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp)
        (temp / ".bashrc").write_text("case $- in *i*) ;; *) return ;; esac\nalias ll='ls -l'\n")
        call = ". cloud/common.sh; shell_env 'export A=1' 'export B=2'; shell_env 'export A=1' 'export B=2'"
        subprocess.run(["bash", "-c", call], cwd=ROOT, env={**os.environ, "HOME": str(temp)}, check=True)
        for name in (".bashrc", ".profile"):
            lines = (temp / name).read_text().splitlines()
            self.assertEqual(lines[:2], ["export A=1", "export B=2"])
            self.assertEqual(lines.count("export A=1"), 1)
        self.assertEqual((temp / ".bashrc").read_text().splitlines()[2], "case $- in *i*) ;; *) return ;; esac")


class AppScriptTest(unittest.TestCase):
    def test_the_app_accepts_each_loader_and_it_names_files_that_exist(self):
        for script in SCRIPTS:
            with self.subTest(script.name):
                loader = subprocess.run(
                    [str(CLOUD / "app-script"), script.stem], check=True, text=True, capture_output=True
                ).stdout
                self.assertLess(len(loader.encode()), 64 * 1024)  # the largest file the app loads
                subprocess.run(["bash", "-n"], input=loader, text=True, check=True)
                self.assertIn(f"cloud/common.sh cloud/{script.stem}.sh working-agreement.md", loader)
                self.assertIn(f'exec bash "$d/cloud/{script.stem}.sh"', loader)

    def test_it_refuses_a_repository_without_a_script(self):
        result = subprocess.run([str(CLOUD / "app-script"), "nothing"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


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
