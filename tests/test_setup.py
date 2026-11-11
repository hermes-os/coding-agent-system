"""setup.sh, run against a temporary HOME with stand-in `hermes` and `podman`.

Git is real: `repo` clones from a local folder that plays the Git server.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup.sh"
AGREEMENT = ROOT / "working-agreement.md"
PROFILES = sorted(path.name for path in (ROOT / "profiles").iterdir())

# Each stand-in appends its arguments, one JSON list per line, to $CALLS.
RECORD = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
"""
HERMES = RECORD + """
args = sys.argv[1:]
if os.environ.get("HERMES_FAILS") in args:
    sys.exit(1)
if args[:2] == ["profile", "create"]:
    os.makedirs(os.path.join(os.environ["HOME"], ".hermes", "profiles", args[2]))
"""
PODMAN = RECORD + """
if sys.argv[1] == "images":
    print("3.1 GB")
"""


class SetupTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.home = self.temp / "home"
        self.home.mkdir()
        self.fakes = self.temp / "fakes"
        self.fakes.mkdir()
        self.calls = self.temp / "calls"
        self.fake("hermes", HERMES)
        self.fake("podman", PODMAN)

    def fake(self, name, body):
        path = self.fakes / name
        path.write_text(body)
        path.chmod(0o755)

    def setup(self, *args, **env):
        return subprocess.run(
            [str(SETUP), *args],
            text=True,
            capture_output=True,
            env={
                "HOME": str(self.home),
                "PATH": f"{self.fakes}:/usr/bin:/bin",
                "CALLS": str(self.calls),
                "WORKBENCH_FORGE": str(self.temp / "forge"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                **env,
            },
        )

    def ok(self, *args, **env):
        result = self.setup(*args, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def recorded(self, command):
        if not self.calls.exists():
            return []
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        return [call[1:] for call in calls if call[0] == command]

    def bundle_skills(self, profile):
        spec = json.loads((ROOT / "profiles" / profile / "profile.json").read_text())
        for skill in spec.get("skills", []):
            folder = self.home / ".hermes/hermes-agent/skills/software-development" / skill
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(skill)
        return spec


class ProfileTest(SetupTest):
    def test_every_profile_is_written_as_the_repository_describes_it(self):
        for name in PROFILES:
            with self.subTest(profile=name):
                spec = self.bundle_skills(name)
                self.ok(name)
                home = self.home / ".hermes/profiles" / name

                intro = (ROOT / "profiles" / name / "intro.md").read_text()
                soul = intro + "\n" + AGREEMENT.read_text() if spec.get("agreement") else intro
                self.assertEqual((home / "SOUL.md").read_text(), soul)

                hermes = self.recorded("hermes")
                self.assertIn(
                    ["profile", "create", name, "--no-alias", "--no-skills", "--description", spec["description"]],
                    hermes,
                )
                settings = {call[4]: call[5] for call in hermes if call[:4] == ["-p", name, "config", "set"]}
                expected = {
                    key: value if isinstance(value, str) else json.dumps(value)
                    for key, value in spec["config"].items()
                }
                expected["HERMES_DOCKER_BINARY"] = str(self.fakes / "podman")
                self.assertEqual(settings, expected)

                self.assertEqual(
                    sorted(path.name for path in (home / "skills").iterdir()),
                    sorted(spec.get("skills", [])),
                )

    def test_the_image_is_built_from_the_containerfile(self):
        self.bundle_skills("worker")
        self.ok("worker")
        build = self.recorded("podman")[0]
        self.assertEqual(build[0], "build")
        self.assertEqual(build[build.index("-t") + 1], "localhost/workbench:latest")
        self.assertEqual(build[build.index("-f") + 1], str(ROOT / "workbench/Containerfile"))
        self.assertTrue((self.home / ".cache/workbench").is_dir())
        self.assertTrue((self.home / "workbench").is_dir())

    def test_a_second_run_restores_the_profile_without_creating_it_again(self):
        self.bundle_skills("worker")
        self.ok("worker")
        home = self.home / ".hermes/profiles/worker"
        (home / "SOUL.md").write_text("edited by hand")
        (home / "skills/stray").mkdir()

        self.ok("worker")

        self.assertTrue((home / "SOUL.md").read_text().endswith(AGREEMENT.read_text()))
        self.assertFalse((home / "skills/stray").exists())
        creates = [call for call in self.recorded("hermes") if call[:2] == ["profile", "create"]]
        self.assertEqual(len(creates), 1)

    def test_a_skill_hermes_does_not_bundle_stops_the_run(self):
        (self.home / ".hermes/hermes-agent/skills/software-development/another").mkdir(parents=True)
        result = self.setup("worker")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no bundled skill named", result.stderr)

    def test_a_setting_hermes_refuses_stops_the_run(self):
        self.bundle_skills("worker")
        result = self.setup("worker", HERMES_FAILS="config")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / ".hermes/profiles/worker/SOUL.md").exists())

    def test_a_host_without_hermes_is_told_so(self):
        (self.fakes / "hermes").unlink()
        result = self.setup("worker")
        self.assertEqual(result.returncode, 1)
        self.assertIn("hermes is not installed", result.stderr)
        self.assertEqual(self.recorded("podman"), [])

    def test_an_unknown_profile_or_no_command_prints_usage(self):
        for args in ([], ["no-such-profile"], ["repo"]):
            with self.subTest(args=args):
                result = self.setup(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
                for name in PROFILES:
                    self.assertIn(name, result.stderr)
        self.assertEqual(self.recorded("hermes"), [])


class RepoTest(SetupTest):
    def git(self, *args, cwd):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    def commit(self, source, name):
        (source / name).write_text(name)
        self.git("add", name, cwd=source)
        self.git("commit", "-m", f"add {name}", cwd=source)
        self.git("push", "origin", "HEAD:main", cwd=source)

    def test_repo_clones_once_then_fast_forwards(self):
        origin = self.temp / "forge/app.git"
        origin.mkdir(parents=True)
        self.git("init", "--bare", "-b", "main", cwd=origin)
        source = self.temp / "source"
        source.mkdir()
        self.git("init", "-b", "main", cwd=source)
        self.git("remote", "add", "origin", str(origin), cwd=source)
        self.commit(source, "one")

        first = self.ok("repo", "app")
        clone = self.home / "workbench/app"
        self.assertTrue((clone / "one").is_file())
        self.assertIn("add one", first.stdout)

        self.commit(source, "two")
        second = self.ok("repo", "app")
        self.assertTrue((clone / "two").is_file())
        self.assertIn("add two", second.stdout)

        # Kanban's task worktrees stay out of the clone's `git status`.
        exclude = (clone / ".git/info/exclude").read_text().splitlines()
        self.assertEqual(exclude.count(".worktrees/"), 1)

    def test_a_repository_the_server_does_not_have_fails(self):
        result = self.setup("repo", "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / "workbench/missing").exists())


class LinksTest(SetupTest):
    def test_links_puts_the_agreement_where_agents_read_it(self):
        self.ok("links")
        for path in ("AGENTS.md", ".claude/CLAUDE.md"):
            self.assertEqual(os.readlink(self.home / path), str(AGREEMENT))
        self.ok("links")


class ToolsTest(SetupTest):
    def test_tools_links_every_command_and_skill(self):
        self.ok("tools")
        commands = {path.name for path in (ROOT / "bin").iterdir() if path.is_file()}
        self.assertLessEqual({"committer", "agent-trash"}, commands)
        installed = self.home / ".local/bin"
        self.assertEqual({path.name for path in installed.iterdir()}, commands)
        for name in commands:
            self.assertEqual(os.readlink(installed / name), str(ROOT / "bin" / name))
            self.assertTrue(os.access(installed / name, os.X_OK), name)

        skills = {path.name for path in (ROOT / "skills").iterdir()}
        for folder in (".agents/skills", ".claude/skills"):
            self.assertEqual({path.name for path in (self.home / folder).iterdir()}, skills)
            for name in skills:
                self.assertEqual(os.readlink(self.home / folder / name), str(ROOT / "skills" / name))
        self.ok("tools")

    def test_tools_removes_links_to_what_this_repository_deleted(self):
        skills = self.home / ".claude/skills"
        commands = self.home / ".local/bin"
        skills.mkdir(parents=True)
        commands.mkdir(parents=True)
        (skills / "retired").symlink_to(ROOT / "skills/retired")
        (commands / "retired").symlink_to(ROOT / "bin/retired")
        (commands / "elsewhere").symlink_to(self.temp / "not-there")
        (skills / "own").mkdir()

        self.ok("tools")

        self.assertFalse((skills / "retired").is_symlink())
        self.assertFalse((commands / "retired").is_symlink())
        self.assertTrue((commands / "elsewhere").is_symlink(), "a link into another tree is not ours")
        self.assertTrue((skills / "own").is_dir())

    def test_tools_does_not_replace_a_file_that_is_not_a_link(self):
        commands = self.home / ".local/bin"
        commands.mkdir(parents=True)
        (commands / "committer").write_text("someone's own script")

        result = self.setup("tools")

        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a link", result.stderr)
        self.assertEqual((commands / "committer").read_text(), "someone's own script")


if __name__ == "__main__":
    unittest.main()
