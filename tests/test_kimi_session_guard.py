import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from lib.host_contract import kimi_policy_marker


SYSTEM_ROOT = Path(__file__).parents[1]
GUARD = SYSTEM_ROOT / "lib" / "kimi_session_guard.py"


class KimiSessionGuardTests(unittest.TestCase):
    def run_guard(
        self,
        home: Path,
        share: Path,
        session_id: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(GUARD), "--hook"],
            input=json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": session_id,
                    "cwd": str(home / "repo"),
                }
            ),
            env={
                **os.environ,
                "HOME": str(home),
                "KIMI_SHARE_DIR": str(share),
            },
            text=True,
            capture_output=True,
            check=False,
        )

    def run_preflight(
        self,
        home: Path,
        share: Path,
        argv: list[str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(GUARD), "--preflight", "--", *argv],
            env={
                **os.environ,
                "HOME": str(home),
                "KIMI_SHARE_DIR": str(share),
            },
            text=True,
            capture_output=True,
            check=False,
        )

    def fixture(self, root: Path, prompt: str) -> tuple[Path, Path, str]:
        home = root / "home"
        share = root / "kimi-runtime"
        session_id = "11111111-2222-3333-4444-555555555555"
        (home / ".agents").mkdir(parents=True)
        policy = "# Global Engineering System\n\nCurrent policy.\n"
        (home / ".agents" / "AGENTS.md").write_text(policy, encoding="utf-8")
        context = share / "sessions" / "work-dir" / session_id / "context.jsonl"
        context.parent.mkdir(parents=True)
        context.write_text(
            json.dumps({"role": "_system_prompt", "content": prompt}) + "\n",
            encoding="utf-8",
        )
        return home, share, session_id

    def test_accepts_current_managed_policy_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = "# Global Engineering System\n\nCurrent policy.\n"
            home, share, session_id = self.fixture(
                root,
                f"system\n{kimi_policy_marker(policy)}\n",
            )
            result = self.run_guard(home, share, session_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_blocks_stale_or_unmanaged_session(self):
        with tempfile.TemporaryDirectory() as temp:
            home, share, session_id = self.fixture(
                Path(temp),
                "old unmanaged system prompt",
            )
            result = self.run_guard(home, share, session_id)
        self.assertEqual(result.returncode, 2)
        self.assertIn("predates the current managed policy", result.stderr)

    def test_blocks_ambiguous_session_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = "# Global Engineering System\n\nCurrent policy.\n"
            home, share, session_id = self.fixture(
                root,
                kimi_policy_marker(policy),
            )
            duplicate = share / "sessions" / "other" / session_id / "context.jsonl"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text(
                json.dumps(
                    {
                        "role": "_system_prompt",
                        "content": kimi_policy_marker(policy),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_guard(home, share, session_id)
        self.assertEqual(result.returncode, 2)
        self.assertIn("2 contexts", result.stderr)

    def test_preflight_accepts_current_or_new_explicit_print_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = "# Global Engineering System\n\nCurrent policy.\n"
            home, share, session_id = self.fixture(
                root,
                kimi_policy_marker(policy),
            )
            current = self.run_preflight(
                home,
                share,
                ["--session", session_id, "--print"],
            )
            fresh = self.run_preflight(
                home,
                share,
                [
                    "--session",
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "--print",
                ],
            )
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)

    def test_preflight_blocks_stale_resume_and_interactive_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            home, share, session_id = self.fixture(Path(temp), "stale")
            stale = self.run_preflight(
                home,
                share,
                ["--resume", session_id, "--print"],
            )
            interactive = self.run_preflight(home, share, [])
        self.assertEqual(stale.returncode, 2)
        self.assertIn("predates the current managed policy", stale.stderr)
        self.assertEqual(interactive.returncode, 2)
        self.assertIn("requires --print or --quiet", interactive.stderr)

    def test_preflight_validates_clustered_resume_options(self):
        with tempfile.TemporaryDirectory() as temp:
            home, share, session_id = self.fixture(Path(temp), "stale")
            results = [
                self.run_preflight(
                    home,
                    share,
                    [argument, "--print"],
                )
                for argument in (
                    f"-yS{session_id}",
                    f"-yr{session_id}",
                )
            ]
            continued = self.run_preflight(
                home,
                share,
                ["-yC", "--print"],
            )
        for result in results:
            self.assertEqual(result.returncode, 2)
            self.assertIn("predates the current managed policy", result.stderr)
        self.assertEqual(continued.returncode, 2)
        self.assertIn("cannot identify a session before launch", continued.stderr)

    def test_preflight_accepts_safe_short_option_clusters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = "# Global Engineering System\n\nCurrent policy.\n"
            home, share, _ = self.fixture(
                root,
                kimi_policy_marker(policy),
            )
            results = [
                self.run_preflight(home, share, [argument, "--print"])
                for argument in ("-ypfix-it", "-ymoperator")
            ]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_preserves_equals_in_attached_session_id(self):
        with tempfile.TemporaryDirectory() as temp:
            home, share, session_id = self.fixture(Path(temp), "stale")
            current_dir = share / "sessions" / "work-dir" / session_id
            literal_session_id = f"={session_id}"
            current_dir.rename(current_dir.parent / literal_session_id)
            results = [
                self.run_preflight(
                    home,
                    share,
                    [f"-{option}{literal_session_id}", "--print"],
                )
                for option in ("S", "r")
            ]
        for result in results:
            self.assertEqual(result.returncode, 2)
            self.assertIn("predates the current managed policy", result.stderr)

    def test_preflight_blocks_stale_legacy_context(self):
        with tempfile.TemporaryDirectory() as temp:
            home, share, session_id = self.fixture(Path(temp), "stale")
            current = (
                share
                / "sessions"
                / "work-dir"
                / session_id
                / "context.jsonl"
            )
            legacy = current.parent.parent / f"{session_id}.jsonl"
            current.replace(legacy)
            current.parent.rmdir()
            result = self.run_preflight(
                home,
                share,
                [f"-S{session_id}", "--print"],
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("predates the current managed policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
