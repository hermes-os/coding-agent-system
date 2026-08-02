import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
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
                "incomplete_results": False,
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
        self.vm_config = base / "vm-config.json"
        self.mac_config = base / "mac-config.json"
        for path, local_peer in (
            (self.vm_config, "vm-cal"),
            (self.mac_config, "mac-cal"),
        ):
            path.write_text(
                json.dumps(
                    {
                        "githubPeer": {
                            "localPeer": local_peer,
                            "repositories": ["example/app"],
                            "trustedAuthors": ["trusted-author"],
                        }
                    }
                ),
                encoding="utf-8",
            )
        self.config = self.vm_config
        self.module = load_module()
        self.provider = Provider(self.head)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        defaults = {
            "repo": str(self.repo),
            "_authorization_path": str(self.config),
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

    def publish_request(self, **values):
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, result = self.capture(
                self.module.request_command,
                self.args(apply=True, lease_id="a" * 32, **values),
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
            _authorization_path=str(self.mac_config),
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

    def test_transition_must_match_every_immutable_request_field(self):
        request_value = self.publish_request()
        request = self.module.decode_comment(self.provider.comments[0]["body"])
        self.assertIsNotNone(request)
        mismatches = (
            {"head_sha": "f" * 40},
            {"pull_request": 8},
        )
        for comment_id, changed in enumerate(mismatches, start=20):
            packet = self.module.transition_packet(request, "ack", "mac-cal")
            packet.update(changed)
            self.provider.comments.append(
                {
                    "id": comment_id,
                    "body": self.module.encode_comment(packet),
                    "user": {"login": "trusted-author"},
                }
            )
        with mock.patch.object(self.module, "gh_json", self.provider):
            states, ignored, conflicts = self.module.load_states(
                self.repo, "example/app", self.module.authorization(self.vm_config), 7
            )
        self.assertEqual(ignored, 0)
        self.assertEqual(conflicts, 2)
        self.assertEqual(states[request_value]["state"], "requested")

        writes_before = len(self.provider.writes)
        signal = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.vm_config),
            pr=7,
            head=self.head,
            request_id=request_value,
            recipient="mac-cal",
            state="present",
            apply=True,
            lease_id="c" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "conflicting trusted"):
                self.module.signal_command(signal)
        self.assertEqual(len(self.provider.writes), writes_before)
        self.assertNotIn("agent:mac-pending", self.provider.labels)

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
            _authorization_path=str(self.mac_config),
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
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.show_command(argparse.Namespace(**{**vars(args), "actor": "vm-cal"}))
        self.provider.head = "f" * 40
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.show_command(args)

    def test_ack_and_complete_reconcile_without_granting_mutation(self):
        request_value = self.publish_request()
        common = {
            "repo": str(self.repo),
            "_authorization_path": str(self.mac_config),
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
            _authorization_path=str(self.config),
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
            _authorization_path=str(self.mac_config),
            organization="example",
            recipient="mac-cal",
            limit=20,
            timeout_seconds=25,
        )
        writes_before = len(self.provider.writes)
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, found = self.capture(self.module.discover_command, discover)
        self.assertEqual(
            set(found),
            {
                "handoffs",
                "ignored_invalid_untrusted_or_unenrolled",
                "label",
                "conflicting_trusted_events",
                "truncated",
            },
        )
        self.assertEqual(len(found["handoffs"]), 1)
        self.assertEqual(found["handoffs"][0]["request_id"], request_value)
        self.assertNotIn("objective", found["handoffs"][0])
        self.assertEqual(len(self.provider.writes), writes_before)

        ack = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.mac_config),
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
        absent = argparse.Namespace(
            **{
                **vars(present),
                "_authorization_path": str(self.mac_config),
                "state": "absent",
                "lease_id": "f" * 32,
            }
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, cleared = self.capture(self.module.signal_command, absent)
        self.assertTrue(cleared["published"])
        self.assertNotIn("agent:mac-pending", self.provider.labels)

    def test_discovery_caps_multiple_requests_and_reports_incomplete_provider_results(self):
        first = self.publish_request(objective="Run the Mac build.", check=["macos-build"])
        second = self.publish_request(objective="Run the Mac tests.", check=["macos-tests"])
        self.provider.labels.add("agent:mac-pending")
        discover = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.mac_config),
            organization="example",
            recipient="mac-cal",
            limit=1,
            timeout_seconds=25,
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, found = self.capture(self.module.discover_command, discover)
        self.assertEqual(len(found["handoffs"]), 1)
        self.assertEqual(found["handoffs"][0]["request_id"], min(first, second))
        self.assertTrue(found["truncated"])

        def incomplete_provider(root, endpoint, *, method="GET", payload=None):
            value = self.provider(root, endpoint, method=method, payload=payload)
            if endpoint.startswith("search/issues?"):
                value = {**value, "incomplete_results": True}
            return value

        self.provider.comments = self.provider.comments[:1]
        with mock.patch.object(self.module, "gh_json", incomplete_provider):
            _, incomplete = self.capture(self.module.discover_command, discover)
        self.assertEqual(len(incomplete["handoffs"]), 1)
        self.assertTrue(incomplete["truncated"])

    def test_discovery_overscan_skips_a_stale_label_before_valid_work(self):
        stale = self.module.request_packet(
            slug="example/app",
            pull_request=7,
            head=self.head,
            sender="vm-cal",
            recipient="mac-cal",
            role="macos-validation",
            objective="Stale Mac validation.",
            checks=["macos-tests"],
        )
        valid_head = "e" * 40
        valid = self.module.request_packet(
            slug="example/app",
            pull_request=8,
            head=valid_head,
            sender="vm-cal",
            recipient="mac-cal",
            role="macos-validation",
            objective="Current Mac validation.",
            checks=["macos-tests"],
        )
        comments = {
            7: [{"id": 1, "body": self.module.encode_comment(stale), "user": {"login": "trusted-author"}}],
            8: [{"id": 2, "body": self.module.encode_comment(valid), "user": {"login": "trusted-author"}}],
        }

        def provider(_root, endpoint, *, method="GET", payload=None):
            self.assertEqual(method, "GET")
            self.assertIsNone(payload)
            if endpoint.startswith("search/issues?"):
                self.assertIn("sort=updated&order=desc&per_page=5", endpoint)
                return {
                    "incomplete_results": False,
                    "total_count": 2,
                    "items": [
                        {
                            "number": number,
                            "pull_request": {"url": "unused"},
                            "repository_url": "https://api.github.com/repos/example/app",
                        }
                        for number in (7, 8)
                    ],
                }
            if endpoint == "repos/example/app/pulls/7":
                head = "f" * 40
            elif endpoint == "repos/example/app/pulls/8":
                head = valid_head
            elif endpoint.startswith("repos/example/app/issues/7/comments?"):
                return comments[7]
            elif endpoint.startswith("repos/example/app/issues/8/comments?"):
                return comments[8]
            elif endpoint == "repos/example/app/collaborators/trusted-author/permission":
                return {"permission": "write"}
            else:
                raise AssertionError(endpoint)
            return {
                "state": "open",
                "head": {"sha": head},
                "base": {"repo": {"full_name": "example/app"}},
            }

        discover = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.mac_config),
            organization="example",
            recipient="mac-cal",
            limit=1,
            timeout_seconds=25,
        )
        with mock.patch.object(self.module, "gh_json", provider):
            _, found = self.capture(self.module.discover_command, discover)
        self.assertEqual([item["request_id"] for item in found["handoffs"]], [valid["request_id"]])
        self.assertFalse(found["truncated"])

    def test_queue_removal_waits_for_every_current_head_recipient_request(self):
        first = self.publish_request(objective="Run the Mac build.", check=["macos-build"])
        second = self.publish_request(objective="Run the Mac tests.", check=["macos-tests"])
        present = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.vm_config),
            pr=7,
            head=self.head,
            request_id=first,
            recipient="mac-cal",
            state="present",
            apply=True,
            lease_id="a" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            self.capture(self.module.signal_command, present)

        def acknowledge(request_value):
            args = argparse.Namespace(
                repo=str(self.repo),
                _authorization_path=str(self.mac_config),
                pr=7,
                head=self.head,
                request_id=request_value,
                actor="mac-cal",
                apply=True,
                lease_id="b" * 32,
            )
            with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
                self.module, "verify_public_lease"
            ):
                return self.capture(self.module.ack_command, args)[1]

        first_ack = acknowledge(first)
        self.assertEqual(first_ack["queue_action"], "keep")
        self.assertEqual(first_ack["pending_sibling_request_ids"], [second])
        absent = argparse.Namespace(
            **{
                **vars(present),
                "_authorization_path": str(self.mac_config),
                "state": "absent",
            }
        )
        writes_before = len(self.provider.writes)
        with mock.patch.object(self.module, "gh_json", self.provider):
            _, held = self.capture(self.module.signal_command, absent)
        self.assertEqual(held["reason"], "pending-recipient-requests")
        self.assertIn(second, held["pending_request_ids"])
        self.assertEqual(len(self.provider.writes), writes_before)
        self.assertIn("agent:mac-pending", self.provider.labels)

        second_ack = acknowledge(second)
        self.assertEqual(second_ack["queue_action"], "remove")
        self.assertEqual(second_ack["pending_sibling_request_ids"], [])
        clear_second = argparse.Namespace(**{**vars(absent), "request_id": second})
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease"
        ):
            _, cleared = self.capture(self.module.signal_command, clear_second)
        self.assertTrue(cleared["published"])
        self.assertNotIn("agent:mac-pending", self.provider.labels)

    def test_local_peer_binding_prevents_cross_peer_lifecycle_actions(self):
        request_value = self.publish_request()
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.request_command(self.args(sender="mac-cal", recipient="vm-cal"))

        recipient = {
            "repo": str(self.repo),
            "_authorization_path": str(self.vm_config),
            "pr": 7,
            "head": self.head,
            "request_id": request_value,
            "actor": "mac-cal",
        }
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.show_command(argparse.Namespace(**recipient))
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.ack_command(
                    argparse.Namespace(**recipient, apply=False, lease_id=None)
                )
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.complete_command(
                    argparse.Namespace(
                        **recipient,
                        apply=False,
                        lease_id=None,
                        outcome="success",
                        summary="Spoofed completion.",
                    )
                )
        attest = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.vm_config),
            pr=7,
            head=self.head,
            request_id=request_value,
            suite="macos-tests",
            state="success",
            apply=False,
            lease_id=None,
        )
        with mock.patch.object(self.module, "gh_json", self.provider):
            with self.assertRaisesRegex(self.module.HandoffError, "local peer"):
                self.module.attest_command(attest)

    def test_authorization_path_is_canonical_and_public_cli_cannot_replace_it(self):
        account_home = Path(self.temp.name) / "account-home"
        redirected_home = Path(self.temp.name) / "redirected-home"
        pointer = Path(self.temp.name) / "missing-pointer"
        with mock.patch.object(self.module, "PINNED_CONFIG_PATH_FILE", pointer), mock.patch.object(
            self.module.pwd,
            "getpwuid",
            return_value=type("Account", (), {"pw_dir": str(account_home)})(),
        ), mock.patch.dict(
            self.module.os.environ,
            {"HOME": str(redirected_home), "AGENTS_HOME": str(redirected_home / ".agents")},
        ):
            self.assertEqual(
                self.module.canonical_config_path(), account_home / ".agents" / "config.json"
            )
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.module.parser().parse_args(
                [
                    "list",
                    "--repo",
                    str(self.repo),
                    "--to",
                    "mac-cal",
                    "--pr",
                    "7",
                    "--config",
                    str(self.mac_config),
                ]
            )

    def test_authorization_rejects_symlink_and_writable_config_state(self):
        linked = self.mac_config.parent / "linked-config.json"
        linked.symlink_to(self.mac_config)
        with self.assertRaisesRegex(self.module.HandoffError, "non-symlink"):
            self.module.authorization(linked)

        original_mode = self.mac_config.stat().st_mode & 0o777
        try:
            self.mac_config.chmod(0o666)
            with self.assertRaisesRegex(self.module.HandoffError, "group/world writable"):
                self.module.authorization(self.mac_config)
        finally:
            self.mac_config.chmod(original_mode)

        oversized = self.mac_config.parent / "oversized-config.json"
        oversized.write_bytes(b" " * (self.module.MAX_AGENT_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(self.module.HandoffError, "size limit"):
            self.module.authorization(oversized)

    def test_authorization_rejects_atomic_replacement_before_open(self):
        replacement = self.mac_config.parent / "replacement-config.json"
        replacement.write_text(self.vm_config.read_text(encoding="utf-8"), encoding="utf-8")
        real_lstat = Path.lstat
        replaced = False

        def replace_after_lstat(path):
            nonlocal replaced
            value = real_lstat(path)
            if path == self.mac_config and not replaced:
                os.replace(replacement, self.mac_config)
                replaced = True
            return value

        with mock.patch.object(Path, "lstat", replace_after_lstat):
            with self.assertRaisesRegex(self.module.HandoffError, "changed during inspection"):
                self.module.authorization(self.mac_config)
        self.assertTrue(replaced)

    def test_authorization_fifo_replacement_cannot_block_before_validation(self):
        replacement = self.mac_config.parent / "replacement-config"
        os.mkfifo(replacement)
        real_open = self.module.os.open
        replaced = False

        def replace_with_fifo(path, flags, *args, **kwargs):
            nonlocal replaced
            if path == self.mac_config and not replaced:
                os.replace(replacement, self.mac_config)
                replaced = True
                self.assertTrue(flags & self.module.os.O_NONBLOCK)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(self.module.os, "open", replace_with_fifo):
            with self.assertRaisesRegex(self.module.HandoffError, "changed during inspection"):
                self.module.authorization(self.mac_config)
        self.assertTrue(replaced)

    def test_authorization_rejects_atomic_replacement_during_read(self):
        replacement = self.mac_config.parent / "replacement-config.json"
        replacement.write_text(self.vm_config.read_text(encoding="utf-8"), encoding="utf-8")
        real_read = self.module.os.read
        replaced = False

        def replace_after_read(descriptor, size):
            nonlocal replaced
            content = real_read(descriptor, size)
            if content and not replaced:
                os.replace(replacement, self.mac_config)
                replaced = True
            return content

        with mock.patch.object(self.module.os, "read", replace_after_read):
            with self.assertRaisesRegex(self.module.HandoffError, "changed during inspection"):
                self.module.authorization(self.mac_config)
        self.assertTrue(replaced)

    def test_root_pinned_config_cannot_target_caller_owned_enrollment(self):
        with self.assertRaisesRegex(self.module.HandoffError, "ownership"):
            self.module.check_authorization_file(
                self.mac_config, allowed_owners={self.mac_config.stat().st_uid + 1}
            )

        pointer = Path(self.temp.name) / "etc" / "coding-agent-system" / "agents-config-path"
        pointer.parent.mkdir(parents=True)
        target = Path(self.temp.name) / "root" / ".agents" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text(self.vm_config.read_text(encoding="utf-8"), encoding="utf-8")
        pointer.write_text(f"{target}\n", encoding="utf-8")
        real_lstat = Path.lstat
        real_check = self.module.check_authorization_file
        checked = []

        def root_controlled_lstat(path):
            value = real_lstat(path)
            if path in {pointer.parent, pointer}:
                return SimpleNamespace(
                    st_mode=value.st_mode,
                    st_uid=0,
                    st_size=value.st_size,
                )
            return value

        def root_fixture_check(path, *, allowed_owners=None):
            checked.append((path, allowed_owners))
            effective_owners = (
                {os.getuid()} if allowed_owners == {0} else allowed_owners
            )
            return real_check(path, allowed_owners=effective_owners)

        with mock.patch.object(
            self.module, "PINNED_CONFIG_PATH_FILE", pointer
        ), mock.patch.object(Path, "lstat", root_controlled_lstat), mock.patch.object(
            self.module, "check_root_controlled_directories"
        ) as checked_directories, mock.patch.object(
            self.module,
            "check_authorization_file",
            side_effect=root_fixture_check,
        ):
            selected = self.module.canonical_config_path()
            self.assertEqual(selected, target)
            self.assertEqual(
                self.module.authorization(selected)["local_peer"],
                "vm-cal",
            )
        self.assertEqual(
            checked_directories.call_args_list,
            [
                mock.call(pointer.parent, "pinned agent config"),
                mock.call(target.parent, "installer-pinned agent config target"),
            ],
        )
        self.assertEqual(checked, [(target, {0}), (target, None)])

    def test_root_pinned_config_rejects_a_writable_ancestor_swap(self):
        target_directory = Path("/safe/caller-writable/.agents")

        def directory_state(path):
            mode = 0o777 if path == Path("/safe/caller-writable") else 0o755
            return SimpleNamespace(st_mode=self.module.stat.S_IFDIR | mode, st_uid=0)

        with mock.patch.object(Path, "lstat", directory_state):
            with self.assertRaisesRegex(self.module.HandoffError, "root-controlled"):
                self.module.check_root_controlled_directories(
                    target_directory, "installer-pinned agent config target"
                )

    def test_each_write_revalidates_pr_head_after_lease_admission(self):
        def advance_head(*_args, **_kwargs):
            self.provider.head = "f" * 40

        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease", side_effect=advance_head
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.request_command(
                    self.args(apply=True, lease_id="a" * 32)
                )
        self.assertEqual(self.provider.writes, [])

        self.provider = Provider(self.head)
        request_value = self.publish_request()
        writes_before = len(self.provider.writes)
        signal = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.vm_config),
            pr=7,
            head=self.head,
            request_id=request_value,
            recipient="mac-cal",
            state="present",
            apply=True,
            lease_id="b" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease", side_effect=advance_head
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.signal_command(signal)
        self.assertEqual(len(self.provider.writes), writes_before)

        self.provider = Provider(self.head)
        request_value = self.publish_request()
        writes_before = len(self.provider.writes)
        attest = argparse.Namespace(
            repo=str(self.repo),
            _authorization_path=str(self.mac_config),
            pr=7,
            head=self.head,
            request_id=request_value,
            suite="macos-tests",
            state="success",
            apply=True,
            lease_id="c" * 32,
        )
        with mock.patch.object(self.module, "gh_json", self.provider), mock.patch.object(
            self.module, "verify_public_lease", side_effect=advance_head
        ), mock.patch.object(self.module.platform, "system", return_value="Darwin"), mock.patch.object(
            self.module.platform, "machine", return_value="arm64"
        ):
            with self.assertRaisesRegex(self.module.HandoffError, "drifted"):
                self.module.attest_command(attest)
        self.assertEqual(len(self.provider.writes), writes_before)

    def test_comment_scan_and_whole_operation_deadlines_are_bounded(self):
        calls = 0

        def full_page(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return [{"id": number, "body": "ordinary"} for number in range(100)]

        with mock.patch.object(self.module, "gh_json", side_effect=full_page):
            with self.assertRaisesRegex(self.module.HandoffError, "300-item safety budget"):
                self.module.issue_comments(self.repo, "example/app", 7)
        self.assertEqual(calls, 3)

        with mock.patch.object(self.module.time, "monotonic", side_effect=[100.0, 126.0]), mock.patch.object(
            self.module.subprocess, "run"
        ) as invoked:
            with self.module.operation_deadline(25):
                with self.assertRaisesRegex(self.module.HandoffError, "overall deadline"):
                    self.module.run(["gh", "api", "user"], cwd=self.repo)
        invoked.assert_not_called()

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
            _authorization_path=str(self.mac_config),
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
