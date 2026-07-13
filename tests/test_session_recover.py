import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
RECOVER = SYSTEM_ROOT / "skills" / "pickup" / "scripts" / "agent-session-recover.py"


class SessionRecoveryTests(unittest.TestCase):
    def test_find_and_render_visible_redacted_turns_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_root = root / "codex"
            claude_root = root / "claude"
            repo = root / "project"
            codex_root.mkdir()
            claude_root.mkdir()
            repo.mkdir()
            session = codex_root / "session.jsonl"
            secret = "".join(("actual", "secret", "value", "123"))
            records = [
                {"type": "session_meta", "payload": {"cwd": str(repo), "id": "fixture"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "<environment_context>hidden policy</environment_context>Fix billing serialization. SERVICE_SECRET=" + secret,
                    },
                },
                {"type": "response_item", "payload": {"type": "function_call_output", "output": "raw tool output"}},
                {
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "message": "Implemented the lease and tests."},
                },
            ]
            session.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            env = {
                **os.environ,
                "AGENT_CODEX_SESSIONS": str(codex_root),
                "AGENT_CLAUDE_PROJECTS": str(claude_root),
            }

            found = subprocess.run(
                [str(RECOVER), "find", "--cwd", str(repo), "--query", "billing serialization", "--json"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(found.returncode, 0, found.stderr)
            rows = json.loads(found.stdout)
            self.assertEqual(rows[0]["host"], "codex")
            self.assertNotIn(secret, rows[0]["last_user"])

            output = root / "recovery.md"
            subprocess.run(
                [str(RECOVER), "render", str(session), "--query", "billing", "--out", str(output)],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("Fix billing serialization", rendered)
            self.assertIn("Implemented the lease and tests", rendered)
            self.assertIn("[REDACTED]", rendered)
            self.assertNotIn(secret, rendered)
            self.assertNotIn("hidden policy", rendered)
            self.assertNotIn("raw tool output", rendered)

    def test_renders_claude_text_without_thinking_or_tool_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_root = root / "codex"
            claude_root = root / "claude"
            repo = root / "project"
            codex_root.mkdir()
            claude_root.mkdir()
            repo.mkdir()
            session = claude_root / "session.jsonl"
            records = [
                {
                    "type": "user",
                    "cwd": str(repo),
                    "message": {"content": [{"type": "text", "text": "Resume the parser repair."}]},
                },
                {
                    "type": "assistant",
                    "cwd": str(repo),
                    "message": {
                        "content": [
                            {"type": "thinking", "thinking": "private reasoning"},
                            {"type": "tool_use", "input": "private tool payload"},
                            {"type": "text", "text": "The parser repair is verified."},
                        ]
                    },
                },
            ]
            session.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            env = {
                **os.environ,
                "AGENT_CODEX_SESSIONS": str(codex_root),
                "AGENT_CLAUDE_PROJECTS": str(claude_root),
            }
            rendered = subprocess.run(
                [str(RECOVER), "render", str(session), "--query", "parser"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertIn("Resume the parser repair", rendered)
            self.assertIn("The parser repair is verified", rendered)
            self.assertNotIn("private reasoning", rendered)
            self.assertNotIn("private tool payload", rendered)


if __name__ == "__main__":
    unittest.main()
