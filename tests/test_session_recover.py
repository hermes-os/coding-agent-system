import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
RECOVER = SYSTEM_ROOT / "skills" / "pickup" / "scripts" / "agent-session-recover.py"


def load_recovery_module():
    spec = importlib.util.spec_from_file_location("agent_session_recover_fixture", RECOVER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
            auth_secret = "".join(("opaque", "session", "credential", "456"))
            cookie_secret = "".join(("private", "cookie", "value", "789"))
            structured_secret = "".join(("quoted", "credential", "value", "654"))
            uri_secret = "".join(("database", "credential", "852"))
            provider_secret = "".join(("sk-", "proj-", "x" * 40))
            claude_secret = "".join(("sk-", "ant-api03-", "y" * 40))
            long_secret = "q" * 600
            named_secrets = ["".join(("opaque", "named", str(index), "24680")) for index in range(3)]
            authorization = "".join(("Author", "ization"))
            bearer = "".join(("Bea", "rer"))
            cookie = "".join(("Coo", "kie"))
            structured_key = "".join(("pass", "word"))
            records = [
                {"type": "session_meta", "payload": {"cwd": str(repo), "id": "fixture"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": (
                            "<environment_context>hidden policy</environment_context>"
                            "Fix billing serialization. SERVICE_SECRET="
                            + secret
                            + f"\n{authorization}: {bearer} {auth_secret}"
                            + f"\n{cookie}: session={cookie_secret}"
                            + f'\n"{structured_key}": "{structured_secret}"'
                            + f"\npostgres://user:{uri_secret}@database.example/app"
                            + "\n" + provider_secret
                            + "\n" + claude_secret
                            + f'\naccess_token="{long_secret}"'
                            + f"\napiKey: {named_secrets[0]}"
                            + f'\n"api-key": "{named_secrets[1]}"'
                            + f"\nprivateKey={named_secrets[2]}"
                        ),
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
            self.assertNotIn(auth_secret, rows[0]["last_user"])
            self.assertNotIn(cookie_secret, rows[0]["last_user"])
            self.assertNotIn(structured_secret, rows[0]["last_user"])
            self.assertNotIn(uri_secret, rows[0]["last_user"])
            self.assertNotIn(provider_secret, rows[0]["last_user"])
            self.assertNotIn(claude_secret, rows[0]["last_user"])

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
            self.assertNotIn(auth_secret, rendered)
            self.assertNotIn(cookie_secret, rendered)
            self.assertNotIn(structured_secret, rendered)
            self.assertNotIn(uri_secret, rendered)
            self.assertNotIn(provider_secret, rendered)
            self.assertNotIn(claude_secret, rendered)
            self.assertNotIn(long_secret, rendered)
            for named_secret in named_secrets:
                self.assertNotIn(named_secret, rendered)
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
            auth_secret = "".join(("opaque", "claude", "credential", "321"))
            authorization = "".join(("Author", "ization"))
            bearer = "".join(("Bea", "rer"))
            records = [
                {
                    "type": "user",
                    "cwd": str(repo),
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Resume the parser repair.\n{authorization}: {bearer} {auth_secret}",
                            }
                        ]
                    },
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
            found = subprocess.run(
                [str(RECOVER), "find", "--cwd", str(repo), "--query", "parser", "--json"],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertIn("Resume the parser repair", rendered)
            self.assertIn("The parser repair is verified", rendered)
            self.assertNotIn(auth_secret, rendered)
            self.assertNotIn(auth_secret, found)
            self.assertNotIn("private reasoning", rendered)
            self.assertNotIn("private tool payload", rendered)

    def test_query_selection_keeps_matching_response_and_latest_status(self):
        module = load_recovery_module()
        turns = [
            module.Turn("user", "Repair billing serialization"),
            module.Turn("assistant", "Billing serialization is repaired and tested"),
            module.Turn("user", "Unrelated cleanup"),
            module.Turn("assistant", "Cleanup finished"),
            module.Turn("user", "Latest status request"),
            module.Turn("assistant", "Current branch is ready"),
        ]
        selected = module.selected_turns(turns, "billing serialization", 4)
        texts = [turn.text for turn in selected]
        self.assertEqual(texts[0:2], [turns[0].text, turns[1].text])
        self.assertEqual(texts[-2:], [turns[-2].text, turns[-1].text])


if __name__ == "__main__":
    unittest.main()
