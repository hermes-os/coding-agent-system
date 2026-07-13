import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


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
            head = git(first, "rev-parse", "HEAD")

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

            blocked = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=second, env=second_env)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(json.loads(blocked.stderr)["owner"], "first-worker")

            verified = command(["verify", first_lease, "--repo", str(first)], cwd=first, env=first_env)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            fenced = command(
                ["verify", first_lease, "--repo", str(first), "--head", "0" * 40],
                cwd=first,
                env=first_env,
            )
            self.assertEqual(fenced.returncode, 1)
            self.assertIn("exact-head fence failed", fenced.stderr)
            renewed = command(["renew", first_lease, "--ttl", "60"], cwd=first, env=first_env)
            self.assertEqual(renewed.returncode, 0, renewed.stderr)
            released = command(["release", first_lease], cwd=first, env=first_env)
            self.assertEqual(released.returncode, 0, released.stderr)

            expiring = command(["acquire", scope, "--ttl", "1", "--head", head], cwd=second, env=second_env)
            self.assertEqual(expiring.returncode, 0, expiring.stderr)
            time.sleep(1.2)
            reclaimed = command(["acquire", scope, "--ttl", "60", "--head", head], cwd=first, env=first_env)
            self.assertEqual(reclaimed.returncode, 0, reclaimed.stderr)
            reclaimed_lease = json.loads(reclaimed.stdout)["lease_id"]
            command(["release", reclaimed_lease], cwd=first, env=first_env, check=True)
            status = command(["status", scope], cwd=second, env=second_env)
            self.assertEqual(json.loads(status.stdout), {"locked": False, "scope": scope})


if __name__ == "__main__":
    unittest.main()
