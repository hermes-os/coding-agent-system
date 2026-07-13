#!/usr/bin/env python3
"""Cross-host expiring leases backed by atomic Git remote refs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid


MAX_TTL_SECONDS = 86_400
REPOSITORY_SCOPE_RE = re.compile(r"repo:[a-z0-9_.-]+/[a-z0-9_.-]+:write")


class LeaseError(RuntimeError):
    pass


class LeaseChanged(LeaseError):
    pass


def now_epoch() -> int:
    return int(time.time())


def iso_time(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError) as exc:
        raise LeaseError("lease contains an invalid timestamp") from exc


def lease_epoch(value: object, label: str) -> int:
    try:
        epoch = int(value)
    except (TypeError, ValueError) as exc:
        raise LeaseError(f"lease contains an invalid {label}") from exc
    if epoch < 0:
        raise LeaseError(f"lease contains an invalid {label}")
    return epoch


def is_expired(value: dict) -> bool:
    return lease_epoch(value.get("expires_at"), "expires_at") <= now_epoch()


def state_root() -> Path:
    configured = os.environ.get("AGENT_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".agents" / "state"


def token_path(lease_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", lease_id):
        raise LeaseError("invalid lease id")
    return state_root() / "leases" / f"{lease_id}.json"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        temp.chmod(0o600)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def load_token(lease_id: str) -> dict:
    path = token_path(lease_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LeaseError(f"lease token not found: {lease_id}") from exc
    if not isinstance(value, dict) or value.get("lease_id") != lease_id:
        raise LeaseError(f"invalid lease token: {lease_id}")
    return value


def coordination_repo(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("AGENT_COORDINATION_REPO_DIR")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if (candidate / ".git").exists():
            return candidate
        raise LeaseError(f"coordination repository is not a Git checkout: {candidate}")

    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists() and (candidate / "agent-system").is_dir():
            return candidate

    try:
        output = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LeaseError("cannot locate the shared coordination repository") from exc
    return Path(output).resolve()


def sanitize_error(value: str) -> str:
    value = re.sub(r"https?://[^\s]+", "<remote>", value)
    value = re.sub(r"(?:x-access-token:)?[A-Za-z0-9_=-]{24,}", "<redacted>", value)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:240] if lines else "Git operation failed"


def git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise LeaseError("Git is unavailable") from exc
    if check and result.returncode != 0:
        raise LeaseError(sanitize_error(result.stderr or result.stdout))
    return result


def remote_name() -> str:
    return os.environ.get("AGENT_COORDINATION_REMOTE", "origin")


def lock_ref(scope: str) -> str:
    scope = canonical_scope(scope)
    readable = re.sub(r"[^a-z0-9]+", "-", scope).strip("-")[:32] or "lease"
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:12]
    return f"refs/heads/agent-locks/{readable}-{digest}"


def canonical_scope(scope: str) -> str:
    normalized = scope.strip().lower()
    if normalized == "public:mutation" or REPOSITORY_SCOPE_RE.fullmatch(normalized):
        return normalized
    raise LeaseError("scope must be public:mutation or repo:<owner>/<repo>:write")


def remote_sha(repo: Path, ref: str) -> str | None:
    result = git(repo, "ls-remote", "--refs", remote_name(), ref)
    line = result.stdout.strip()
    return line.split()[0] if line else None


def metadata_for(repo: Path, ref: str, expected: str) -> dict | None:
    if git(repo, "cat-file", "-e", f"{expected}^{{commit}}", check=False).returncode != 0:
        fetched = git(repo, "fetch", "--quiet", "--no-tags", remote_name(), ref, check=False)
        if fetched.returncode != 0:
            return None
        if git(repo, "cat-file", "-e", f"{expected}^{{commit}}", check=False).returncode != 0:
            if remote_sha(repo, ref) != expected:
                raise LeaseChanged("lease changed while loading metadata")
            return None
    result = git(repo, "show", "-s", "--format=%B", expected, check=False)
    if result.returncode != 0:
        return None
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("version") == 1:
            return value
    return None


def read_remote_metadata(repo: Path, ref: str) -> tuple[str | None, dict | None]:
    for _ in range(3):
        current = remote_sha(repo, ref)
        if not current:
            return None, None
        try:
            metadata = metadata_for(repo, ref, current)
        except LeaseChanged:
            continue
        if remote_sha(repo, ref) == current:
            return current, metadata
    raise LeaseError("lease changed repeatedly; retry")


def make_commit(repo: Path, metadata: dict) -> str:
    tree = git(repo, "mktree", input_text="").stdout.strip()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Agent Lease",
            "GIT_AUTHOR_EMAIL": "agent-lease@local.invalid",
            "GIT_COMMITTER_NAME": "Agent Lease",
            "GIT_COMMITTER_EMAIL": "agent-lease@local.invalid",
        }
    )
    payload = "agent lease\n\n" + json.dumps(metadata, sort_keys=True) + "\n"
    result = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", tree],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise LeaseError(sanitize_error(result.stderr or result.stdout))
    return result.stdout.strip()


def delete_ref(repo: Path, ref: str, expected: str) -> bool:
    result = git(
        repo,
        "push",
        "--porcelain",
        f"--force-with-lease={ref}:{expected}",
        remote_name(),
        f":{ref}",
        check=False,
    )
    return result.returncode == 0


def replace_ref(repo: Path, ref: str, expected: str, commit: str) -> bool:
    result = git(
        repo,
        "push",
        "--porcelain",
        f"--force-with-lease={ref}:{expected}",
        remote_name(),
        f"{commit}:{ref}",
        check=False,
    )
    return result.returncode == 0


def owner_name(explicit: str | None) -> str:
    return explicit or os.environ.get("AGENT_TASK_ID") or os.environ.get("AGENT_RUN_ID") or f"{socket.gethostname()}:{os.getpid()}"


def public_metadata(value: dict, *, locked: bool = True) -> dict:
    acquired_at = lease_epoch(value.get("acquired_at"), "acquired_at") if value.get("acquired_at") is not None else None
    expires_at = lease_epoch(value.get("expires_at"), "expires_at") if value.get("expires_at") is not None else None
    return {
        "locked": locked,
        "scope": value.get("scope"),
        "lease_id": value.get("lease_id"),
        "owner": value.get("owner"),
        "head": value.get("head"),
        "acquired_at": iso_time(acquired_at) if acquired_at is not None else None,
        "expires_at": iso_time(expires_at) if expires_at is not None else None,
    }


def owned_remote(repo: Path, token: dict) -> tuple[str, dict]:
    current, held = read_remote_metadata(repo, token["ref"])
    if not current:
        raise LeaseError("lease is no longer active")
    if not held or held.get("lease_id") != token.get("lease_id"):
        raise LeaseError("lease ownership changed")
    return current, held


def acquire(args: argparse.Namespace) -> int:
    repo = coordination_repo(args.coordination_repo)
    git(repo, "remote", "get-url", remote_name())
    scope = canonical_scope(args.scope)
    ref = lock_ref(scope)

    for _ in range(3):
        current, held = read_remote_metadata(repo, ref)
        if current:
            if not held:
                raise LeaseError("existing lease metadata is unreadable; refusing to replace it")
            output = public_metadata(held)
            output["expired"] = is_expired(held)
            print(json.dumps(output, sort_keys=True), file=sys.stderr)
            return 2

        acquired = now_epoch()
        metadata = {
            "version": 1,
            "scope": scope,
            "lease_id": uuid.uuid4().hex,
            "owner": owner_name(args.owner),
            "head": args.head,
            "acquired_at": acquired,
            "expires_at": acquired + args.ttl,
        }
        public_metadata(metadata)
        commit = make_commit(repo, metadata)
        token = {
            **metadata,
            "ref": ref,
            "commit": commit,
            "coordination_repo": str(repo),
        }
        path = token_path(metadata["lease_id"])
        try:
            atomic_json(path, token)
        except OSError as exc:
            raise LeaseError("cannot persist lease token; remote lease was not acquired") from exc
        result = git(repo, "push", "--porcelain", remote_name(), f"{commit}:{ref}", check=False)
        if result.returncode != 0:
            if remote_sha(repo, ref) == commit:
                print(json.dumps(public_metadata(metadata), sort_keys=True))
                return 0
            path.unlink(missing_ok=True)
            continue
        print(json.dumps(public_metadata(metadata), sort_keys=True))
        return 0

    current, held = read_remote_metadata(repo, ref)
    if held:
        print(json.dumps(public_metadata(held), sort_keys=True), file=sys.stderr)
    return 2


def status(args: argparse.Namespace) -> int:
    repo = coordination_repo(args.coordination_repo)
    scope = canonical_scope(args.scope)
    ref = lock_ref(scope)
    current, held = read_remote_metadata(repo, ref)
    if not current:
        print(json.dumps({"locked": False, "scope": scope}, sort_keys=True))
        return 0
    if not held:
        raise LeaseError("lease metadata is unreadable")
    result = public_metadata(held)
    result["expired"] = is_expired(held)
    print(json.dumps(result, sort_keys=True))
    return 0


def renew(args: argparse.Namespace) -> int:
    token = load_token(args.lease_id)
    repo = coordination_repo(token.get("coordination_repo"))
    current, held = owned_remote(repo, token)
    metadata = {key: held.get(key) for key in ("version", "scope", "lease_id", "owner", "head", "acquired_at", "expires_at")}
    metadata["head"] = args.head if args.head is not None else metadata.get("head")
    metadata["expires_at"] = now_epoch() + args.ttl
    public_metadata(metadata)
    commit = make_commit(repo, metadata)
    if not replace_ref(repo, token["ref"], current, commit):
        raise LeaseError("lease changed while renewing")
    renewed_token = {**token, **metadata, "commit": commit}
    try:
        atomic_json(token_path(args.lease_id), renewed_token)
    except OSError as exc:
        if replace_ref(repo, token["ref"], commit, current):
            raise LeaseError("cannot persist renewed lease; remote lease was restored") from exc
        raise LeaseError(
            "cannot persist renewed lease; lease remains manageable by its existing lease id"
        ) from exc
    print(json.dumps(public_metadata(metadata), sort_keys=True))
    return 0


def verify(args: argparse.Namespace) -> int:
    token = load_token(args.lease_id)
    repo = coordination_repo(token.get("coordination_repo"))
    _, held = owned_remote(repo, token)
    if is_expired(held):
        raise LeaseError("lease expired")
    stored_head = held.get("head")
    if args.head is not None:
        if not stored_head or args.head != stored_head:
            raise LeaseError("exact-head assertion does not match the lease fence")
    if args.repo:
        if not stored_head:
            raise LeaseError("lease has no exact-head fence for repository verification")
        actual = git(Path(args.repo).expanduser().resolve(), "rev-parse", "HEAD").stdout.strip()
        if actual != stored_head:
            raise LeaseError(f"exact-head fence failed: expected {stored_head[:12]}, found {actual[:12]}")
    print(json.dumps(public_metadata(held), sort_keys=True))
    return 0


def release(args: argparse.Namespace) -> int:
    token = load_token(args.lease_id)
    repo = coordination_repo(token.get("coordination_repo"))
    current, held = read_remote_metadata(repo, token["ref"])
    if current is None:
        token_path(args.lease_id).unlink(missing_ok=True)
        print(json.dumps({"released": True, "lease_id": args.lease_id}, sort_keys=True))
        return 0
    if not held or held.get("lease_id") != token.get("lease_id"):
        raise LeaseError("lease ownership changed; refusing release")
    if not delete_ref(repo, token["ref"], current):
        raise LeaseError("lease changed while releasing")
    token_path(args.lease_id).unlink(missing_ok=True)
    print(json.dumps({"released": True, "lease_id": args.lease_id}, sort_keys=True))
    return 0


def reap(args: argparse.Namespace) -> int:
    repo = coordination_repo(args.coordination_repo)
    scope = canonical_scope(args.scope)
    ref = lock_ref(scope)
    current, held = read_remote_metadata(repo, ref)
    if not current:
        print(json.dumps({"reaped": False, "scope": scope, "reason": "not-locked"}, sort_keys=True))
        return 0
    if not held:
        raise LeaseError("lease metadata is unreadable; refusing to reap")
    if not is_expired(held):
        print(json.dumps(public_metadata(held), sort_keys=True), file=sys.stderr)
        return 2
    if not delete_ref(repo, ref, current):
        raise LeaseError("lease changed while reaping")
    print(json.dumps({"reaped": True, "scope": scope}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    acquire_parser = commands.add_parser("acquire")
    acquire_parser.add_argument("scope")
    acquire_parser.add_argument("--ttl", type=int, default=1800)
    acquire_parser.add_argument("--head")
    acquire_parser.add_argument("--owner")
    acquire_parser.add_argument("--coordination-repo")
    acquire_parser.set_defaults(handler=acquire)

    status_parser = commands.add_parser("status")
    status_parser.add_argument("scope")
    status_parser.add_argument("--coordination-repo")
    status_parser.set_defaults(handler=status)

    renew_parser = commands.add_parser("renew")
    renew_parser.add_argument("lease_id")
    renew_parser.add_argument("--ttl", type=int, default=1800)
    renew_parser.add_argument("--head")
    renew_parser.set_defaults(handler=renew)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("lease_id")
    verify_parser.add_argument("--repo")
    verify_parser.add_argument("--head")
    verify_parser.set_defaults(handler=verify)

    release_parser = commands.add_parser("release")
    release_parser.add_argument("lease_id")
    release_parser.set_defaults(handler=release)

    reap_parser = commands.add_parser("reap")
    reap_parser.add_argument("scope")
    reap_parser.add_argument("--coordination-repo")
    reap_parser.set_defaults(handler=reap)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "ttl") and not 1 <= args.ttl <= MAX_TTL_SECONDS:
        raise LeaseError(f"ttl must be between 1 and {MAX_TTL_SECONDS} seconds")
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LeaseError as exc:
        print(f"agent-lease: {exc}", file=sys.stderr)
        raise SystemExit(1)
