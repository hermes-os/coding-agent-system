import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = SYSTEM_ROOT / "host" / "local" / "bin"


class AgentPermissionContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.log = self.home / "calls.jsonl"
        self.stub = self.home / "native-agent"
        self.stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            "with Path(os.environ['AGENT_TEST_LOG']).open('a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['app-server', 'daemon', 'version'] and "
            "os.environ.get('AGENT_TEST_DAEMON_RUNNING') == '1':\n"
            "    print(json.dumps({'status': 'running', 'socketPath': '/tmp/test.sock'}))\n",
            encoding="utf-8",
        )
        self.stub.chmod(0o755)

        kimi_home = self.home / ".agents" / "kimi"
        kimi_home.mkdir(parents=True)
        (kimi_home / "agent.yaml").write_text("version: 1\n", encoding="utf-8")
        guard = kimi_home / "session-guard.py"
        guard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        guard.chmod(0o755)
        kimi_config = self.home / ".kimi" / "config.toml"
        kimi_config.parent.mkdir()
        kimi_config.write_text('default_model = "operator"\n', encoding="utf-8")

        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "AGENT_TEST_LOG": str(self.log),
            "AGENT_CLAUDE_BIN": str(self.stub),
            "AGENT_CLAUDE_RUN_AS": "current",
            "AGENT_CODEX_BIN": str(self.stub),
            "AGENT_CODEX_IGNORE_DESKTOP_APP_SERVER": "1",
            "AGENT_KIMI_BIN": str(self.stub),
            "AGENT_REMOTE_CONTROL": "0",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, agent, *arguments, access=None):
        environment = dict(self.environment)
        if access is not None:
            environment["AGENT_ACCESS_MODE"] = access
        return subprocess.run(
            [str(LAUNCHERS / f"agent-{agent}"), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]

    def test_write_agent_invocations_bypass_provider_permissions(self):
        self.assertEqual(self.invoke("claude", "-p", "inspect").returncode, 0)
        self.assertEqual(self.invoke("codex", "exec", "-").returncode, 0)
        self.assertEqual(self.invoke("kimi", "--print").returncode, 0)

        claude, codex, kimi = self.calls()
        self.assertEqual(
            claude[:2],
            ["--permission-mode", "bypassPermissions"],
        )
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", codex)
        self.assertIn("--dangerously-bypass-hook-trust", codex)
        self.assertIn("--yolo", kimi)

    def test_read_agent_invocations_disable_bypass(self):
        self.assertEqual(
            self.invoke("claude", "-p", "inspect", access="read").returncode,
            0,
        )
        self.assertEqual(
            self.invoke("codex", "exec", "-", access="read").returncode,
            0,
        )
        self.assertEqual(
            self.invoke("kimi", "--print", access="read").returncode,
            0,
        )

        claude, codex, kimi = self.calls()
        self.assertEqual(claude[:2], ["--permission-mode", "dontAsk"])
        self.assertNotIn("bypassPermissions", claude)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", codex)
        self.assertIn('sandbox_mode="read-only"', codex)
        self.assertIn('approval_policy="never"', codex)
        self.assertNotIn("--yolo", kimi)

    def test_codex_review_is_read_only_without_an_environment_override(self):
        result = self.invoke("codex", "review", "--uncommitted")
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertEqual(call[0], "review")
        self.assertIn('sandbox_mode="read-only"', call)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", call)

    def test_codex_exec_review_is_read_only_without_an_environment_override(self):
        result = self.invoke("codex", "exec", "review", "--uncommitted")
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertEqual(call[0], "exec")
        self.assertIn('sandbox_mode="read-only"', call)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", call)

    def test_end_of_options_does_not_bypass_managed_permissions(self):
        result = self.invoke("codex", "exec", "--", "-h")
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertEqual(call[0], "exec")
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", call)

    def test_codex_falls_back_to_legacy_json_remote_control_pid_state(self):
        state = self.home / ".codex" / "app-server-daemon"
        state.mkdir(parents=True)
        (state / "app-server.pid").write_text(
            json.dumps({"pid": os.getpid(), "processStartTime": "test"}),
            encoding="utf-8",
        )
        self.environment["AGENT_REMOTE_CONTROL"] = "1"

        result = self.invoke("codex", "continue")

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0], ["app-server", "daemon", "version"])
        self.assertEqual(calls[-1][-1], "continue")
        self.assertFalse(
            any(call[:2] == ["remote-control", "start"] for call in calls)
        )

    def test_codex_recognizes_current_daemon_status(self):
        self.environment["AGENT_REMOTE_CONTROL"] = "1"
        self.environment["AGENT_TEST_DAEMON_RUNNING"] = "1"
        state = self.home / ".codex" / "app-server-daemon"
        state.mkdir(parents=True)
        (state / "settings.json").write_text(
            json.dumps({"remoteControlEnabled": True}),
            encoding="utf-8",
        )

        result = self.invoke("codex", "continue")

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0], ["app-server", "daemon", "version"])
        self.assertEqual(calls[-1][-1], "continue")
        self.assertFalse(
            any(call[:2] == ["remote-control", "start"] for call in calls)
        )

    def test_read_mode_rejects_provider_bypass_flags(self):
        cases = (
            (
                "claude",
                ("-p", "--permission-mode", "bypassPermissions", "inspect"),
            ),
            (
                "codex",
                ("exec", "--dangerously-bypass-approvals-and-sandbox", "-"),
            ),
            ("kimi", ("--print", "--yolo")),
        )
        for agent, arguments in cases:
            with self.subTest(agent=agent):
                result = self.invoke(agent, *arguments, access="read")
                self.assertEqual(result.returncode, 64, result.stderr)

        self.assertEqual(self.calls(), [])

    def test_codex_rejects_compact_permission_overrides(self):
        cases = (
            ("write", ("exec", "-sworkspace-write", "-")),
            ("write", ("exec", "-s=read-only", "-")),
            ("write", ("exec", '-csandbox_mode="workspace-write"', "-")),
            ("write", ("exec", '-capproval_policy="on-request"', "-")),
            ("write", ("exec", "-aon-request", "-")),
            ("write", ("exec", "-c", 'sandbox_mode = "read-only"', "-")),
            ("read", ("exec", "-sworkspace-write", "-")),
            ("read", ("exec", "-s=danger-full-access", "-")),
            ("read", ("exec", '-csandbox_mode="danger-full-access"', "-")),
            ("read", ("exec", '-capproval_policy="on-request"', "-")),
            ("read", ("exec", "-a=on-request", "-")),
            (
                "read",
                ("exec", '--config=approval_policy = "on-request"', "-"),
            ),
        )
        for access, arguments in cases:
            with self.subTest(access=access, arguments=arguments):
                result = self.invoke("codex", *arguments, access=access)
                self.assertEqual(result.returncode, 64, result.stderr)

        self.assertEqual(self.calls(), [])

    def test_codex_allows_unrelated_compact_config(self):
        result = self.invoke(
            "codex",
            "exec",
            '-cmodel_reasoning_effort = "high"',
            "-",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            '-cmodel_reasoning_effort = "high"',
            self.calls()[0],
        )


if __name__ == "__main__":
    unittest.main()
