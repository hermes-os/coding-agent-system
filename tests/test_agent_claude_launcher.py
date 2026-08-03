import json
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import tempfile
import time
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = SYSTEM_ROOT / "host" / "local" / "bin" / "agent-claude"
SETPRIV = Path("/usr/bin/setpriv")


def identity_is_mapped(map_path, identity):
    for line in map_path.read_text(encoding="utf-8").splitlines():
        inside, _outside, length = (int(part) for part in line.split())
        if inside <= identity < inside + length:
            return True
    return False


def can_switch_to(user_name):
    if os.geteuid() != 0 or not SETPRIV.is_file():
        return False
    user = pwd.getpwnam(user_name)
    return identity_is_mapped(Path("/proc/self/uid_map"), user.pw_uid) and identity_is_mapped(
        Path("/proc/self/gid_map"), user.pw_gid
    )


class AgentClaudeLauncherTests(unittest.TestCase):
    def make_fixture(self, root):
        root.chmod(0o755)
        control = root / "control"
        control.mkdir()
        control.chmod(0o777)
        report = control / "report.json"
        report.touch()
        report.chmod(0o666)
        release = control / "release"

        source_dir = root / "root-only"
        source_dir.mkdir()
        source_dir.chmod(0o700)

        stub = root / "native-agent"
        stub.write_text(
            "#!/usr/bin/python3\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            "import time\n"
            "args = sys.argv[1:]\n"
            "paths = []\n"
            "index = 0\n"
            "while index < len(args):\n"
            "    arg = args[index]\n"
            "    if arg == '--':\n"
            "        break\n"
            "    if arg == '--mcp-config':\n"
            "        index += 1\n"
            "        while index < len(args) and not args[index].startswith('-'):\n"
            "            paths.append(args[index])\n"
            "            index += 1\n"
            "        continue\n"
            "    if arg.startswith('--mcp-config='):\n"
            "        paths.append(arg.split('=', 1)[1])\n"
            "    elif arg == '--settings':\n"
            "        index += 1\n"
            "        paths.append(args[index])\n"
            "    elif arg.startswith('--settings='):\n"
            "        paths.append(arg.split('=', 1)[1])\n"
            "    elif arg in ('--append-system-prompt-file', '--system-prompt-file'):\n"
            "        index += 1\n"
            "        paths.append(args[index])\n"
            "    elif arg.startswith('--append-system-prompt-file=') or arg.startswith('--system-prompt-file='):\n"
            "        paths.append(arg.split('=', 1)[1])\n"
            "    index += 1\n"
            "payload = {\n"
            "    'uid': os.getuid(),\n"
            "    'args': args,\n"
            "    'paths': paths,\n"
            "    'contents': [Path(path).read_text(encoding='utf-8') for path in paths],\n"
            "}\n"
            "Path(os.environ['AGENT_TEST_REPORT']).write_text(\n"
            "    json.dumps(payload), encoding='utf-8'\n"
            ")\n"
            "release = Path(os.environ['AGENT_TEST_RELEASE'])\n"
            "deadline = time.monotonic() + 10\n"
            "while not release.exists() and time.monotonic() < deadline:\n"
            "    time.sleep(0.02)\n"
            "sys.exit(23)\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub, report, release, source_dir

    def launcher_env(self, root, stub, report, release):
        return {
            **os.environ,
            "HOME": str(root),
            "AGENT_CLAUDE_BIN": str(stub),
            "AGENT_CLAUDE_RUN_AS": "nobody",
            "AGENT_TEST_REPORT": str(report),
            "AGENT_TEST_RELEASE": str(release),
        }

    def wait_for_report(self, report, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if report.stat().st_size:
                return json.loads(report.read_text(encoding="utf-8"))
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(
                    f"dropped Claude child exited {process.returncode}: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.02)
        self.fail("dropped Claude child did not produce its report")

    def run_as(self, user_name, *command):
        user = pwd.getpwnam(user_name)
        return subprocess.run(
            [
                str(SETPRIV),
                f"--reuid={user.pw_uid}",
                f"--regid={user.pw_gid}",
                "--init-groups",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--bounding-set=-all",
                "--no-new-privs",
                *map(str, command),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    @unittest.skipUnless(
        can_switch_to("nobody") and can_switch_to("daemon"),
        "requires mapped unprivileged test users",
    )
    def test_root_only_config_files_are_rewritten_private_and_cleaned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stub, report, release, source_dir = self.make_fixture(root)
            sources = []
            for index in range(7):
                source = source_dir / f"source-{index}.json"
                source.write_text(f'{{"fixture": {index}}}\n', encoding="utf-8")
                source.chmod(0o600)
                sources.append(source)

            process = subprocess.Popen(
                [
                    str(LAUNCHER),
                    "-p",
                    "--mcp-config",
                    str(sources[0]),
                    str(sources[1]),
                    "--settings",
                    str(sources[2]),
                    f"--settings={sources[3]}",
                    f"--mcp-config={sources[4]}",
                    "--append-system-prompt-file",
                    str(sources[5]),
                    f"--system-prompt-file={sources[6]}",
                    "--permission-mode",
                    "bypassPermissions",
                    "prove it",
                    "--",
                    "--settings",
                    "--mcp-config",
                ],
                env=self.launcher_env(root, stub, report, release),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            payload = self.wait_for_report(report, process)

            nobody = pwd.getpwnam("nobody")
            self.assertEqual(payload["uid"], nobody.pw_uid)
            staged_paths = [Path(raw_path) for raw_path in payload["paths"]]
            self.assertEqual(
                payload["contents"],
                [source.read_text(encoding="utf-8") for source in sources],
            )
            self.assertEqual(len(staged_paths), len(sources))
            self.assertTrue(all(path not in sources for path in staged_paths))
            self.assertEqual(len({path.parent for path in staged_paths}), 1)
            staging_dir = staged_paths[0].parent
            self.assertEqual(stat.S_IMODE(staging_dir.stat().st_mode), 0o700)
            self.assertEqual(staging_dir.stat().st_uid, nobody.pw_uid)
            self.assertEqual(staging_dir.stat().st_gid, nobody.pw_gid)
            for path in staged_paths:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_uid, nobody.pw_uid)
                self.assertEqual(path.stat().st_gid, nobody.pw_gid)
                self.assertEqual(
                    self.run_as("nobody", "/usr/bin/cat", path).returncode,
                    0,
                )
                self.assertNotEqual(
                    self.run_as("daemon", "/usr/bin/cat", path).returncode,
                    0,
                )
            self.assertNotEqual(
                self.run_as("nobody", "/usr/bin/cat", sources[0]).returncode,
                0,
            )

            rewritten = payload["args"]
            for source in sources:
                self.assertNotIn(str(source), rewritten)
                self.assertFalse(any(str(source) in arg for arg in rewritten))
            self.assertEqual(rewritten[0:2], ["-p", "--mcp-config"])
            self.assertEqual(rewritten[2:4], [str(path) for path in staged_paths[0:2]])
            self.assertEqual(rewritten[4:6], ["--settings", str(staged_paths[2])])
            self.assertEqual(rewritten[6], f"--settings={staged_paths[3]}")
            self.assertEqual(rewritten[7], f"--mcp-config={staged_paths[4]}")
            self.assertEqual(
                rewritten[8:10],
                ["--append-system-prompt-file", str(staged_paths[5])],
            )
            self.assertEqual(rewritten[10], f"--system-prompt-file={staged_paths[6]}")
            self.assertEqual(rewritten[-3:], ["--", "--settings", "--mcp-config"])

            release.touch()
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 23, (stdout, stderr))
            self.assertFalse(staging_dir.exists())

    @unittest.skipUnless(
        can_switch_to("nobody"),
        "requires a mapped unprivileged test user",
    )
    def test_interrupt_reaches_staged_child_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stub, report, release, source_dir = self.make_fixture(root)
            source = source_dir / "source.json"
            source.write_text('{"fixture": "signal"}\n', encoding="utf-8")
            source.chmod(0o600)
            stub.write_text(
                "#!/usr/bin/env bash\n"
                "config_path=''\n"
                "expect_config=0\n"
                "for arg in \"$@\"; do\n"
                "  if (( expect_config )); then\n"
                "    config_path=\"$arg\"\n"
                "    break\n"
                "  fi\n"
                "  if [[ \"$arg\" == '--mcp-config' ]]; then\n"
                "    expect_config=1\n"
                "  fi\n"
                "done\n"
                "printf '%s\\n' \"$config_path\" >\"$AGENT_TEST_REPORT\"\n"
                "trap 'exit 130' INT\n"
                "while true; do\n"
                "  sleep 1\n"
                "done\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

            process = subprocess.Popen(
                [str(LAUNCHER), "-p", "--mcp-config", str(source)],
                env=self.launcher_env(root, stub, report, release),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + 10
            staged_path = None
            while time.monotonic() < deadline:
                if report.stat().st_size:
                    staged_path = Path(report.read_text(encoding="utf-8").strip())
                    break
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(
                        f"staged child exited {process.returncode}: "
                        f"stdout={stdout!r} stderr={stderr!r}"
                    )
                time.sleep(0.02)
            self.assertIsNotNone(staged_path)
            self.assertTrue(staged_path.exists())

            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130, (stdout, stderr))
            self.assertFalse(staged_path.parent.exists())

    def test_end_of_options_preserves_option_looking_positionals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o755)
            report = root / "args.json"
            stub = root / "native-agent"
            stub.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(os.environ['AGENT_TEST_REPORT']).write_text(\n"
                "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            arguments = ["-p", "--", "--settings", "--mcp-config"]
            expected = [
                "--permission-mode",
                "bypassPermissions",
                *arguments,
            ]
            result = subprocess.run(
                [str(LAUNCHER), *arguments],
                env={
                    **os.environ,
                    "HOME": str(root),
                    "AGENT_CLAUDE_BIN": str(stub),
                    "AGENT_CLAUDE_RUN_AS": "current",
                    "AGENT_TEST_REPORT": str(report),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), expected)

    @unittest.skipUnless(
        can_switch_to("claude-agent"),
        "requires the mapped Cal execution user",
    )
    def test_cal_host_admin_profile_preserves_elevation_and_rejects_read_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o755)
            stub = root / "native-agent"
            stub.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "status = {}\n"
                "for line in Path('/proc/self/status').read_text().splitlines():\n"
                "    if line.startswith(('CapBnd:', 'NoNewPrivs:')):\n"
                "        key, value = line.split(':', 1)\n"
                "        status[key] = value.strip()\n"
                "status['uid'] = os.getuid()\n"
                "status['openclawState'] = os.environ.get('OPENCLAW_STATE_DIR')\n"
                "Path(os.environ['AGENT_TEST_REPORT']).write_text(json.dumps(status))\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

            for host_admin in ("0", "1"):
                with self.subTest(host_admin=host_admin):
                    report = root / f"report-{host_admin}.json"
                    report.touch()
                    report.chmod(0o666)
                    env = {
                        **os.environ,
                        "HOME": str(root),
                        "AGENT_CLAUDE_BIN": str(stub),
                        "AGENT_CLAUDE_RUN_AS": "claude-agent",
                        "AGENT_CLAUDE_HOST_ADMIN": host_admin,
                        "AGENT_TEST_REPORT": str(report),
                    }
                    result = subprocess.run(
                        [str(LAUNCHER), "-p", "inspect"],
                        env=env,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    status = json.loads(report.read_text(encoding="utf-8"))
                    self.assertEqual(
                        status["uid"],
                        pwd.getpwnam("claude-agent").pw_uid,
                    )
                    if host_admin == "1":
                        self.assertEqual(status["NoNewPrivs"], "0")
                        self.assertNotEqual(int(status["CapBnd"], 16), 0)
                        self.assertEqual(status["openclawState"], "/root/.openclaw")
                    else:
                        self.assertEqual(status["NoNewPrivs"], "1")
                        self.assertEqual(int(status["CapBnd"], 16), 0)
                        self.assertIsNone(status["openclawState"])

            rejected = subprocess.run(
                [str(LAUNCHER), "-p", "inspect"],
                env={
                    **os.environ,
                    "HOME": str(root),
                    "AGENT_CLAUDE_BIN": str(stub),
                    "AGENT_CLAUDE_RUN_AS": "claude-agent",
                    "AGENT_CLAUDE_HOST_ADMIN": "1",
                    "AGENT_ACCESS_MODE": "read",
                    "AGENT_TEST_REPORT": str(root / "rejected.json"),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rejected.returncode, 64)
            self.assertIn("unavailable for read access", rejected.stderr)

    def test_remote_control_is_pinned_for_interactive_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "args.json"
            stub = root / "native-agent"
            stub.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(os.environ['AGENT_TEST_REPORT']).write_text(\n"
                "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(root),
                "AGENT_CLAUDE_BIN": str(stub),
                "AGENT_CLAUDE_RUN_AS": "current",
                "AGENT_REMOTE_CONTROL": "0",
                "AGENT_CLAUDE_REMOTE_CONTROL": "0",
                "AGENT_TEST_REPORT": str(report),
            }

            cases = (
                (
                    ["fix it"],
                    [
                        "--remote-control",
                        "--permission-mode",
                        "bypassPermissions",
                        "fix it",
                    ],
                ),
                (
                    ["--bare"],
                    [
                        "--remote-control",
                        "--permission-mode",
                        "bypassPermissions",
                        "--bare",
                    ],
                ),
                (
                    ["--safe-mode"],
                    [
                        "--remote-control",
                        "--permission-mode",
                        "dontAsk",
                        "--safe-mode",
                    ],
                ),
                (
                    ["-p", "work"],
                    ["--permission-mode", "bypassPermissions", "-p", "work"],
                ),
                (
                    ["--background", "work"],
                    [
                        "--permission-mode",
                        "bypassPermissions",
                        "--background",
                        "work",
                    ],
                ),
            )
            for arguments, expected in cases:
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [str(LAUNCHER), *arguments],
                        env=env,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(report.read_text(encoding="utf-8")),
                        expected,
                    )

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_missing_and_unsafe_config_paths_fail_before_child_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stub, report, release, source_dir = self.make_fixture(root)
            directory = source_dir / "directory.json"
            directory.mkdir()
            target = source_dir / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            target.chmod(0o600)
            symlink = source_dir / "symlink.json"
            symlink.symlink_to(target)
            writable = source_dir / "writable.json"
            writable.write_text("{}\n", encoding="utf-8")
            writable.chmod(0o622)

            for unsafe, reason in (
                (source_dir / "missing.json", "does not exist"),
                (directory, "not a regular file"),
                (symlink, "symbolic links are not allowed"),
                (writable, "writable by another user"),
            ):
                with self.subTest(path=unsafe):
                    result = subprocess.run(
                        [str(LAUNCHER), "-p", "--mcp-config", str(unsafe)],
                        env=self.launcher_env(root, stub, report, release),
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 78)
                    self.assertIn(reason, result.stderr)
                    self.assertEqual(report.stat().st_size, 0)

            staged_before = set(Path("/tmp").glob("agent-claude.*"))
            result = subprocess.run(
                [
                    str(LAUNCHER),
                    "-p",
                    "--mcp-config",
                    str(target),
                    str(source_dir / "still-missing.json"),
                ],
                env=self.launcher_env(root, stub, report, release),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 78)
            self.assertIn("does not exist", result.stderr)
            self.assertEqual(set(Path("/tmp").glob("agent-claude.*")), staged_before)


if __name__ == "__main__":
    unittest.main()
