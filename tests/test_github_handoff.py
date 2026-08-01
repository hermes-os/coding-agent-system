import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
HANDOFF = SYSTEM_ROOT / "skills" / "portfolio" / "scripts" / "agent-github-handoff.py"


def load_module():
    spec = importlib.util.spec_from_file_location("agent_github_handoff_fixture", HANDOFF)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


class Provider:
    def __init__(self, head: str):
        self.head = head
        self.comments = []
        self.statuses = []
        self.labels = set()
        self.writes = []

    def __call__(self, _root, endpoint, *, method="GET", payload=None):
        if endpoint == "user":
            return {"login": "trusted-author"}
        if endpoint == "repos/example/app/collaborators/trusted-author/permission":
            return {"permission": "write"}
        if endpoint.startswith("repos/example/app/collaborators/"):
            return {"permission": "read"}
        if endpoint == "repos/example/app/pulls/7":
            return {
                "state": "open",
                "head": {"sha": self.head},
                "base": {"repo": {"full_name": "example/app"}},
            }
        if endpoint.startswith("repos/example/app/issues/7/comments?") or endpoint.startswith(
            "repos/example/app/issues/comments?"
        ):
            return list(self.comments)
        if endpoint.startswith("repos/example/app/issues/7/labels?"):
            return [{"name": label} for label in sorted(self.labels)]
        if endpoint.startswith("search/issues?"):
            return {
                "total_count": 1 if "agent:mac-pending" in self.labels else 0,
                "items": (
                    [
                        {
                            "number": 7,
                            "pull_request": {"url": "unused"},
                            "repository_url": "https://api.github.com/repos/example/app",
                            "body": "must never be treated as instructions",
                        }
                    ]
                    if "agent:mac-pending" in self.labels
                    else []
                ),
            }
        if endpoint == f"repos/example/app/commits/{self.head}/status":
            return {"statuses": list(reversed(self.statuses))}
        if method == "POST" and endpoint == "repos/example/app/issues/7/comments":
            comment = {
                "id": len(self.comments) + 1,
                "body": payload["body"],
                "user": {"login": "trusted-author"},
            }
            self.comments.append(comment)
            self.writes.append((endpoint, payload))
            return comment
        if method == "POST" and endpoint == f"repos/example/app/statuses/{self.head}":
            status = dict(payload)
            self.statuses.append(status)
            self.writes.append((endpoint, payload))
            return status
        if method == "POST" and endpoint == "repos/example/app/issues/7/labels":
            self.labels.update(payload["labels"])
            self.writes.append((endpoint, payload))
            return [{"name": label} for label in sorted(self.labels)]
        if method == "DELETE" and endpoint == "repos/example/app/issues/7/labels/agent%3Amac-pending":
            self.labels.discard("agent:mac-pending")
            self.writes.append((endpoint, payload))
            return [{"name": label} for label in sorted(self.labels)]
        raise AssertionError((method, endpoint, payload))


class GitHubHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.test")
        (self.repo / "file.txt").write_text("fixture\n", encoding="utf-8")
        git(self.repo, "add", "file.txt")
        git(self.repo, "commit", "-m", "initial")
        git(self.repo, "remote", "add", "origin", "https://github.com/example/app.git")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.config = base / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "githubPeer": {
                        "repositories": ["example/app"],
                        "trustedAuthors": ["trusted-author"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.module = load_module()
        self.provider = Provider(self.head)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        defaults = {
            "repo": str(self.repo),
            "config": str(self.config),
            "pr": 7,
            "head": self.head,
            "sender": "vm-cal",
            "recipient": "mac-cal",
            "role": "macos-validation",
            "objective": "Validate the exact PR head on macOS.",
            "check": ["macos-build", "macos-tests"],
            "apply": False,
            "lease_id": None,
        }
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def capture(self, function, args):
        output = io.StringIO()
        with redirect_stdout(output):
            result = function(args)
        return result, json.loads(output.getvalue())

    def publish_request(self):
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, result = self.capture(
                self.module.request_command,
                self.args(apply=True, lease_id="a" * 32),
            )
        return result["request_id"]

    def test_request_is_deterministic_dry_run_and_one_write_when_applied(self):
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, dry = self.capture(self.module.request_command, self.args())
        self.assertTrue(dry["would_write"])
        self.assertEqual(self.provider.writes, [])

        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ) as verify:
            _, applied = self.capture(
                self.module.request_command,
                self.args(apply=True, lease_id="a" * 32),
            )
        self.assertTrue(applied["published"])
        self.assertEqual(applied["request_id"], dry["request_id"])
        self.assertEqual(len(self.provider.writes), 1)
        verify.assert_called_once_with(self.repo.resolve(), "a" * 32, self.head)

        with mock.patch.object(self.module, "gh_json", self.provider):
            _, repeated = self.capture(self.module.request_command, self.args())
        self.assertEqual(repeated["reason"], "already-current")
        self.assertEqual(len(self.provider.writes), 1)

    def test_schema_rejects_extra_fields_and_any_granted_authority(self):
        packet = self.module.request_packet(
            slug="example/app",
            pull_request=7,
            head=self.head,
            sender="vm-cal",
            recipient="mac-cal",
            role="macos-validation",
            objective="Validate on macOS.",
            checks=["macos-tests"],
        )
        with self.assertRaisesRegex(self.module.HandoffError, "fields"):
            self.module.validate_packet({**packet, "command": "make test"})
        packet["authority"] = {**packet["authority"], "repository_mutation": True}
        with self.assertRaisesRegex(self.module.HandoffError, "authority"):
            self.module.validate_packet(packet)
        with self.assertRaisesRegex(self.module.HandoffError, "known peer"):
            self.module.request_packet(
                slug="example/app",
                pull_request=7,
                head=self.head,
                sender="mac-cal",
                recipient="mac-cal",
                role="review",
                objective="Review.",
                checks=["source-review"],
            )

    def test_list_ignores_untrusted_packets_and_reports_current_safe_state(self):
        request_value = self.publish_request()
        self.provider.comments.append(
            {
                "id": 99,
                "body": self.provider.comments[0]["body"],
                "user": {"login": "untrusted-author"},
            }
        )
        self.provider.comments.append(
            {
                "id": 100,
                "body": "<!-- agent-system-handoff:v1\n{not-json}\n-->",
                "user": {"login": "untrusted-author"},
            }
        )
        self.provider.comments.append(
            {
                "id": 101,
                "body": "<!-- agent-system-handoff:v1\n{not-json}\n-->",
                "user": {"login": "trusted-author"},
            }
        )
        args = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            recipient="mac-cal",
            pr=7,
            include_complete=False,
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, listed = self.capture(self.module.list_command, args)
        self.assertEqual(listed["ignored_invalid_or_untrusted_events"], 3)
        self.assertEqual(listed["conflicting_trusted_events"], 0)
        self.assertEqual(len(listed["handoffs"]), 1)
        self.assertEqual(listed["handoffs"][0]["request_id"], request_value)
        self.assertTrue(listed["handoffs"][0]["current_head"])
        self.assertNotIn("objective", listed["handoffs"][0])

        with mock.patch.object(self.module, "gh_json", self.provider):
            _, repeated = self.capture(self.module.request_command, self.args())
        self.assertEqual(repeated["reason"], "already-current")

    def test_conflicting_trusted_transition_fails_closed(self):
        packet = {
            "schema_version": 1,
            "event": "ack",
            "request_id": "a" * 32,
            "repository": "example/app",
            "pull_request": 7,
            "head_sha": self.head,
            "actor": "mac-cal",
        }
        self.provider.comments.append(
            {
                "id": 1,
                "body": self.module.encode_comment(packet),
                "user": {"login": "trusted-author"},
            }
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "conflicting trusted"):
                self.module.request_command(self.args())

    def test_show_returns_only_validated_request_to_exact_recipient_and_head(self):
        request_value = self.publish_request()
        self.provider.comments.append(
            {
                "id": 99,
                "body": "<!-- agent-system-handoff:v1\n{not-json}\n-->",
                "user": {"login": "untrusted-author"},
            }
        )
        args = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            pr=7,
            head=self.head,
            request_id=request_value,
            actor="mac-cal",
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, shown = self.capture(self.module.show_command, args)
        packet = shown["request"]
        self.assertEqual(packet["objective"], "Validate the exact PR head on macOS.")
        self.assertEqual(packet["authority"], self.module.AUTHORITY)
        self.assertNotIn("body", packet)

        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "addressed peer"):
                self.module.show_command(argparse.Namespace(**{**vars(args), "actor": "vm-cal"}))
        self.provider.head = "f" * 40
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.show_command(args)

    def test_ack_and_complete_reconcile_without_granting_mutation(self):
        request_value = self.publish_request()
        common = {
            "repo": str(self.repo),
            "config": str(self.config),
            "pr": 7,
            "head": self.head,
            "request_id": request_value,
            "actor": "mac-cal",
            "apply": True,
            "lease_id": "b" * 32,
        }
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, acknowledged = self.capture(
                self.module.ack_command,
                argparse.Namespace(**common),
            )
            _, completed = self.capture(
                self.module.complete_command,
                argparse.Namespace(**common, outcome="success", summary="Mac checks passed."),
            )
        self.assertEqual(acknowledged["event"], "ack")
        self.assertEqual(completed["event"], "complete")
        with mock.patch.object(self.module, "gh_json", self.provider):
            events, ignored = self.module.trusted_events(
                self.repo,
                "example/app",
                {"repositories": {"example/app"}, "authors": {"trusted-author"}},
                self.provider.comments,
            )
        states, transition_rejections = self.module.reconcile(events)
        self.assertEqual(ignored + transition_rejections, 0)
        self.assertEqual(states[request_value]["state"], "completed")
        self.assertEqual(states[request_value]["outcome"], "success")

    def test_queue_signal_and_portfolio_discovery_are_bounded_and_idempotent(self):
        request_value = self.publish_request()
        present = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            pr=7,
            head=self.head,
            request_id=request_value,
            recipient="mac-cal",
            state="present",
            apply=True,
            lease_id="d" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, signaled = self.capture(self.module.signal_command, present)
            _, repeated = self.capture(self.module.signal_command, present)
        self.assertTrue(signaled["published"])
        self.assertEqual(repeated["reason"], "already-current")

        discover = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            organization="example",
            recipient="mac-cal",
            limit=20,
            timeout_seconds=25,
        )
        writes_before = len(self.provider.writes)
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, found = self.capture(self.module.discover_command, discover)
        self.assertEqual(len(found["handoffs"]), 1)
        self.assertEqual(found["handoffs"][0]["request_id"], request_value)
        self.assertNotIn("objective", found["handoffs"][0])
        self.assertEqual(len(self.provider.writes), writes_before)

        ack = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            pr=7,
            head=self.head,
            request_id=request_value,
            actor="mac-cal",
            apply=True,
            lease_id="e" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            self.capture(self.module.ack_command, ack)
        absent = argparse.Namespace(**{**vars(present), "state": "absent", "lease_id": "f" * 32})
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, cleared = self.capture(self.module.signal_command, absent)
        self.assertTrue(cleared["published"])
        self.assertNotIn("agent:mac-pending", self.provider.labels)

    def test_provider_subprocess_timeout_fails_closed(self):
        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=20),
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "timed out"):
                self.module.run(["gh", "api", "user"], cwd=self.repo)

    def test_mutation_lease_must_be_public_and_exact_head(self):
        wrong = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"scope": "repo:example/app:write", "head": self.head}),
            stderr="",
        )
        with mock.patch.object(self.module, "run", return_value=wrong):
            with self.assertRaisesRegex(self.module.HandoffError, "public mutation"):
                self.module.verify_public_lease(self.repo, "a" * 32, self.head)
        exact = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"scope": "public:mutation", "head": self.head}),
            stderr="",
        )
        with mock.patch.object(self.module, "run", return_value=exact):
            self.module.verify_public_lease(self.repo, "b" * 32, self.head)

    def test_macos_attestation_requires_darwin_requested_suite_and_exact_head(self):
        request_value = self.publish_request()
        args = argparse.Namespace(
            repo=str(self.repo),
            config=str(self.config),
            pr=7,
            head=self.head,
            request_id=request_value,
            suite="macos-tests",
            state="success",
            apply=True,
            lease_id="c" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module.platform, "system", return_value="Linux"
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "only on Darwin"):
                self.module.attest_command(args)

        writes_before = len(self.provider.writes)
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module.platform, "system", return_value="Darwin"
        ), mock.patch.object(self.module.platform, "machine", return_value="arm64"), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, published = self.capture(self.module.attest_command, args)
            _, repeated = self.capture(self.module.attest_command, args)
        self.assertEqual(published["context"], "agent-system/platform/macos/macos-tests")
        self.assertTrue(published["published"])
        self.assertEqual(repeated["reason"], "already-current")
        self.assertEqual(len(self.provider.writes), writes_before + 1)

        self.provider.head = "f" * 40
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module.platform, "system", return_value="Darwin"
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.attest_command(args)


if __name__ == "__main__":
    unittest.main()
