import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
LEASE = SYSTEM_ROOT / "skills" / "portfolio" / "scripts" / "agent-lease.py"


def command(args, *, cwd, env, check=False):
    return subprocess.run(
        [str(LEASE), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def git_result(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def load_lease_module():
    spec = importlib.util.spec_from_file_location("agent_lease_fixture", LEASE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LeaseTests(unittest.TestCase):
    def test_remote_ref_serializes_two_hosts_and_reaps_expired_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            first = root / "first"
            second = root / "second"
            first.mkdir()
            git(root, "init", "--bare", str(remote))
            git(first, "init")
            git(first, "config", "user.name", "Fixture")
            git(first, "config", "user.email", "fixture@example.test")
            (first / "file.txt").write_text("fixture\n", encoding="utf-8")
            git(first, "add", "file.txt")
            git(first, "commit", "-m", "initial")
            git(first, "remote", "add", "origin", str(remote))
            git(first, "push", "-u", "origin", "HEAD")
            git(root, "clone", str(remote), str(second))
            (first / "unpublished.txt").write_text("not public\n", encoding="utf-8")
            git(first, "add", "unpublished.txt")
            git(first, "commit", "-m", "local candidate")
            head = git(first, "rev-parse", "HEAD")
            unpublished_blob = git(first, "rev-parse", "HEAD:unpublished.txt")

            first_env = {
                **os.environ,
                "AGENT_COORDINATION_REPO_DIR": str(first),
                "AGENT_STATE_DIR": str(root / "first-state"),
                "AGENT_TASK_ID": "first-worker",
            }
            second_env = {
                **os.environ,
                "AGENT_COORDINATION_REPO_DIR": str(second),
                "AGENT_STATE_DIR": str(root / "second-state"),
                "AGENT_TASK_ID": "second-worker",
            }
            scope = "repo:example/project:write"

            acquired = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=first, env=first_env)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            first_lease = json.loads(acquired.stdout)["lease_id"]
            token_file = root / "first-state" / "leases" / f"{first_lease}.json"
            first_token = json.loads(token_file.read_text(encoding="utf-8"))
            self.assertEqual(git(remote, "ls-tree", "-r", first_token["ref"]), "")
            self.assertNotEqual(git_result(remote, "cat-file", "-e", unpublished_blob).returncode, 0)

            blocked = command(["acquire", "repo:EXAMPLE/PROJECT:write", "--ttl", "60", "--head", head], cwd=second, env=second_env)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(json.loads(blocked.stderr)["owner"], "first-worker")

            verified = command(["verify", first_lease, "--repo", str(first)], cwd=first, env=first_env)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            fenced = command(
                ["verify", first_lease, "--head", "0" * 40],
                cwd=first,
                env=first_env,
            )
            self.assertEqual(fenced.returncode, 1)
            self.assertIn("exact-head", fenced.stderr)

            (first / "drift.txt").write_text("drift\n", encoding="utf-8")
            git(first, "add", "drift.txt")
            git(first, "commit", "-m", "drift fixture")
            drift = git(first, "rev-parse", "HEAD")
            bypass = command(
                ["verify", first_lease, "--repo", str(first), "--head", drift],
                cwd=first,
                env=first_env,
            )
            self.assertEqual(bypass.returncode, 1)
            self.assertIn("exact-head", bypass.stderr)
            git(first, "reset", "--hard", head)

            observer = root / "observer"
            observer.mkdir()
            git(observer, "init")
            git(observer, "remote", "add", "origin", str(remote))
            renewed = command(["renew", first_lease, "--ttl", "60"], cwd=first, env=first_env)
            self.assertEqual(renewed.returncode, 0, renewed.stderr)
            module = load_lease_module()
            with self.assertRaises(module.LeaseChanged):
                module.metadata_for(observer, first_token["ref"], first_token["commit"])
            current, held = module.read_remote_metadata(observer, first_token["ref"])
            self.assertIsNotNone(current)
            self.assertEqual(held["lease_id"], first_lease)
            released = command(["release", first_lease], cwd=first, env=first_env)
            self.assertEqual(released.returncode, 0, released.stderr)

            unfenced_scope = "repo:example/unfenced:write"
            unfenced = command(["acquire", unfenced_scope, "--ttl", "60"], cwd=first, env=first_env)
            self.assertEqual(unfenced.returncode, 0, unfenced.stderr)
            unfenced_id = json.loads(unfenced.stdout)["lease_id"]
            rejected = command(["verify", unfenced_id, "--repo", str(first)], cwd=first, env=first_env)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("no exact-head fence", rejected.stderr)
            command(["release", unfenced_id], cwd=first, env=first_env, check=True)

            expiring = command(["acquire", scope, "--ttl", "1", "--head", head], cwd=second, env=second_env)
            self.assertEqual(expiring.returncode, 0, expiring.stderr)
            time.sleep(1.2)
            still_held = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=first, env=first_env)
            self.assertEqual(still_held.returncode, 2)
            self.assertTrue(json.loads(still_held.stderr)["expired"])
            reaped = command(["reap", scope], cwd=first, env=first_env)
            self.assertEqual(reaped.returncode, 0, reaped.stderr)
            reclaimed = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=first, env=first_env)
            self.assertEqual(reclaimed.returncode, 0, reclaimed.stderr)
            reclaimed_lease = json.loads(reclaimed.stdout)["lease_id"]
            command(["release", reclaimed_lease], cwd=first, env=first_env, check=True)
            status = command(["status", scope], cwd=second, env=second_env)
            self.assertEqual(json.loads(status.stdout), {"locked": False, "scope": scope})

            invalid_ttl = command(["acquire", scope, "--ttl", "86401", "--head", head], cwd=first, env=first_env)
            self.assertEqual(invalid_ttl.returncode, 1)
            self.assertIn("ttl must be between", invalid_ttl.stderr)

    def test_persistence_failures_do_not_strand_remote_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            checkout = root / "checkout"
            checkout.mkdir()
            git(root, "init", "--bare", str(remote))
            git(checkout, "init")
            git(checkout, "config", "user.name", "Fixture")
            git(checkout, "config", "user.email", "fixture@example.test")
            (checkout / "file.txt").write_text("fixture\n", encoding="utf-8")
            git(checkout, "add", "file.txt")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "remote", "add", "origin", str(remote))
            git(checkout, "push", "-u", "origin", "HEAD")
            head = git(checkout, "rev-parse", "HEAD")
            state = root / "state"
            env = {
                **os.environ,
                "AGENT_COORDINATION_REPO_DIR": str(checkout),
                "AGENT_STATE_DIR": str(state),
                "AGENT_TASK_ID": "fault-worker",
            }
            scope = "repo:example/faults:write"
            module = load_lease_module()
            acquire_args = argparse.Namespace(
                scope=scope,
                ttl=60,
                head=head,
                owner=None,
                coordination_repo=str(checkout),
            )

            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                module, "atomic_json", side_effect=OSError("fixture write failure")
            ):
                with self.assertRaisesRegex(module.LeaseError, "remote lease was not acquired"):
                    module.acquire(acquire_args)
                self.assertIsNone(module.remote_sha(checkout, module.lock_ref(scope)))

            acquired = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=checkout, env=env)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            lease_id = json.loads(acquired.stdout)["lease_id"]
            token_file = state / "leases" / f"{lease_id}.json"
            original_token = json.loads(token_file.read_text(encoding="utf-8"))
            renew_args = argparse.Namespace(lease_id=lease_id, ttl=120, head=None)

            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                module, "atomic_json", side_effect=OSError("fixture write failure")
            ):
                with self.assertRaisesRegex(module.LeaseError, "remote lease was restored"):
                    module.renew(renew_args)
                self.assertEqual(
                    module.remote_sha(checkout, original_token["ref"]),
                    original_token["commit"],
                )

            verified = command(["verify", lease_id, "--repo", str(checkout)], cwd=checkout, env=env)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            released = command(["release", lease_id], cwd=checkout, env=env)
            self.assertEqual(released.returncode, 0, released.stderr)

    def test_atomic_remote_creation_under_synchronized_contention(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            checkout = root / "checkout"
            barrier = root / "barrier"
            checkout.mkdir()
            barrier.mkdir()
            git(root, "init", "--bare", str(remote))
            git(checkout, "init")
            git(checkout, "config", "user.name", "Fixture")
            git(checkout, "config", "user.email", "fixture@example.test")
            (checkout / "file.txt").write_text("fixture\n", encoding="utf-8")
            git(checkout, "add", "file.txt")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "remote", "add", "origin", str(remote))
            git(checkout, "push", "-u", "origin", "HEAD")
            head = git(checkout, "rev-parse", "HEAD")
            scope = "repo:example/race:write"
            helper = root / "race.py"
            helper.write_text(
                """import argparse
import importlib.util
import os
from pathlib import Path
import sys
import time

lease_path, repo_path, scope, head, barrier_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("lease_racer", lease_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original = module.remote_sha
waited = False

def synchronized(repo, ref):
    global waited
    value = original(repo, ref)
    if value is None and not waited:
        waited = True
        barrier = Path(barrier_path)
        (barrier / str(os.getpid())).touch()
        deadline = time.time() + 10
        while len(list(barrier.iterdir())) < 2 and time.time() < deadline:
            time.sleep(0.01)
        if len(list(barrier.iterdir())) < 2:
            raise RuntimeError("barrier timeout")
    return value

module.remote_sha = synchronized
args = argparse.Namespace(scope=scope, ttl=60, head=head, owner=None, coordination_repo=repo_path)
try:
    raise SystemExit(module.acquire(args))
except module.LeaseError as exc:
    print(f"agent-lease: {exc}", file=sys.stderr)
    raise SystemExit(1)
""",
                encoding="utf-8",
            )
            processes = []
            environments = []
            for number in (1, 2):
                env = {
                    **os.environ,
                    "AGENT_STATE_DIR": str(root / f"state-{number}"),
                    "AGENT_TASK_ID": f"race-{number}",
                }
                environments.append(env)
                processes.append(
                    subprocess.Popen(
                        [sys.executable, str(helper), str(LEASE), str(checkout), scope, head, str(barrier)],
                        cwd=checkout,
                        env=env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            results = [process.communicate(timeout=20) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 2], results)
            winner = next(index for index, process in enumerate(processes) if process.returncode == 0)
            lease_id = json.loads(results[winner][0])["lease_id"]
            released = command(["release", lease_id], cwd=checkout, env=environments[winner])
            self.assertEqual(released.returncode, 0, released.stderr)


if __name__ == "__main__":
    unittest.main()
