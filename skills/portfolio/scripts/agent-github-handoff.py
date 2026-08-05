#!/usr/bin/env python3
"""Exchange constrained, exact-head engineering handoffs through GitHub PRs."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import stat
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote, urlencode
import urllib.error
import urllib.request


SCHEMA_VERSION = 1
MARKER = "agent-system-handoff:v1"
RECIPIENTS = {"mac-cal", "vm-cal"}
ROLES = {"implementation", "review", "macos-validation"}
CHECKS = {
    "repo-gate",
    "source-review",
    "macos-build",
    "macos-tests",
    "macos-app-smoke",
}
MACOS_SUITES = {"macos-build", "macos-tests", "macos-app-smoke"}
OUTCOMES = {"success", "failure", "blocked"}
STATUS_STATES = {"success", "failure", "error"}
# GitHub reports the repository owner as "admin"; Forgejo distinguishes
# "owner" as a level above it. Both imply push, which is what this gate means.
WRITE_PERMISSIONS = {"owner", "admin", "write"}
AUTHORITY = {
    "arbitrary_commands": False,
    "deploy": False,
    "merge": False,
    "repository_mutation": False,
}
SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
FORGE_API_BASE_RE = re.compile(r"https://[A-Za-z0-9.-]+(?::\d+)?/api/v1/?")
FORGE_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
FORGE_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SHA_RE = re.compile(r"[0-9a-f]{40}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")
REMOTE_RE = re.compile(
    r"(?:github\.com|[A-Za-z0-9.-]+)(?::|/)([^/\s]+/[^/\s]+?)(?:\.git)?$"
)
MAX_TEXT = 1_000
COMMAND_TIMEOUT_SECONDS = 20.0
DEFAULT_OPERATION_TIMEOUT_SECONDS = 25
MAX_OPERATION_TIMEOUT_SECONDS = 30
MAX_COMMENT_PAGES = 3
MAX_DISCOVERY_CANDIDATES = 25
DISCOVERY_OVERSCAN_MULTIPLIER = 5
MAX_AGENT_CONFIG_BYTES = 256 * 1024
PINNED_CONFIG_PATH_FILE = Path("/etc/coding-agent-system/agents-config-path")
_COMMAND_DEADLINE: float | None = None
_FORGE: dict | None = None


class HandoffError(RuntimeError):
    pass


class AuthorRejected(HandoffError):
    pass


@contextmanager
def operation_deadline(seconds: int):
    global _COMMAND_DEADLINE
    if not 1 <= seconds <= MAX_OPERATION_TIMEOUT_SECONDS:
        raise HandoffError(
            f"--timeout-seconds must be between 1 and {MAX_OPERATION_TIMEOUT_SECONDS}"
        )
    previous = _COMMAND_DEADLINE
    candidate = time.monotonic() + seconds
    _COMMAND_DEADLINE = min(previous, candidate) if previous is not None else candidate
    try:
        yield
    finally:
        _COMMAND_DEADLINE = previous


def sanitized_error(value: str) -> str:
    value = re.sub(r"https?://[^\s]+", "<remote>", value)
    value = re.sub(r"(?:x-access-token:)?[A-Za-z0-9_=-]{24,}", "<redacted>", value)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:240] if lines else "provider operation failed"


def run(command: list[str], *, cwd: Path, input_text: str | None = None) -> subprocess.CompletedProcess:
    timeout = COMMAND_TIMEOUT_SECONDS
    if _COMMAND_DEADLINE is not None:
        remaining = _COMMAND_DEADLINE - time.monotonic()
        if remaining <= 0:
            raise HandoffError("provider operation exceeded its overall deadline")
        timeout = min(timeout, remaining)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HandoffError(f"provider operation timed out: {command[0]}") from exc
    except OSError as exc:
        raise HandoffError(f"required executable is unavailable: {command[0]}") from exc
    if result.returncode:
        raise HandoffError(sanitized_error(result.stderr or result.stdout))
    return result


def git(root: Path, *args: str) -> str:
    return run(["git", *args], cwd=root).stdout.strip()


def repository_root(value: str | Path | None) -> Path:
    candidate = Path(value or Path.cwd()).expanduser().resolve()
    discovered = Path(git(candidate, "rev-parse", "--show-toplevel")).resolve()
    if discovered != candidate:
        raise HandoffError("--repo must be a Git repository root")
    return candidate


def repository_slug(root: Path) -> str:
    remote = git(root, "remote", "get-url", "origin")
    match = REMOTE_RE.search(remote)
    if not match:
        raise HandoffError("origin is not a recognizable GitHub repository")
    slug = match.group(1).removesuffix(".git")
    if not SLUG_RE.fullmatch(slug):
        raise HandoffError("origin repository name is invalid")
    return slug.lower()


def check_root_controlled_directories(directory: Path, label: str) -> None:
    for candidate in reversed((directory, *directory.parents)):
        try:
            value = candidate.lstat()
        except OSError as exc:
            raise HandoffError(f"cannot inspect {label} ancestor: {candidate}") from exc
        if (
            stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != 0
            or value.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise HandoffError(f"{label} ancestors must be root-controlled directories")


def state_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def canonical_config_path() -> Path:
    pointer = PINNED_CONFIG_PATH_FILE
    try:
        pointer.parent.lstat()
        pointer_value = pointer.lstat()
    except FileNotFoundError:
        pointer_value = None
    except OSError as exc:
        raise HandoffError("cannot inspect the installer-pinned agent config path") from exc
    if pointer_value is not None:
        check_root_controlled_directories(pointer.parent, "pinned agent config")
        if (
            stat.S_ISLNK(pointer_value.st_mode)
            or not stat.S_ISREG(pointer_value.st_mode)
            or pointer_value.st_uid != 0
            or pointer_value.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or pointer_value.st_size > 4_096
        ):
            raise HandoffError("pinned agent config path is not root-controlled")
        try:
            raw = pointer.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise HandoffError("cannot read the installer-pinned agent config path") from exc
        candidate = Path(raw)
        if (
            not raw
            or "\n" in raw
            or not candidate.is_absolute()
            or candidate.name != "config.json"
            or candidate.parent.name != ".agents"
        ):
            raise HandoffError("installer-pinned agent config path is invalid")
        check_root_controlled_directories(
            candidate.parent, "installer-pinned agent config target"
        )
        check_authorization_file(candidate, allowed_owners={0})
        return candidate
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError) as exc:
        raise HandoffError("current OS account has no canonical home directory") from exc
    if not account_home.is_absolute():
        raise HandoffError("current OS account home directory is not absolute")
    return account_home / ".agents" / "config.json"


def authorization_path(args: argparse.Namespace) -> Path:
    # Tests inject a fixture below the public CLI boundary. The parser never
    # exposes this private attribute, and production ignores HOME/AGENTS_HOME.
    injected = getattr(args, "_authorization_path", None)
    return Path(injected) if injected is not None else canonical_config_path()


def check_authorization_file(
    path: Path, *, allowed_owners: set[int] | None = None
) -> os.stat_result:
    try:
        parent = path.parent.lstat()
        value = path.lstat()
    except OSError as exc:
        raise HandoffError(f"invalid agent configuration: {path}") from exc
    owners = allowed_owners or {0, os.getuid()}
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise HandoffError("agent configuration directory must be a real directory")
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        raise HandoffError("agent configuration must be a regular non-symlink file")
    if parent.st_uid not in owners or value.st_uid not in owners:
        raise HandoffError("agent configuration ownership is not authorized for this host")
    if parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise HandoffError("agent configuration directory must not be group/world writable")
    if value.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise HandoffError("agent configuration must not be group/world writable")
    if value.st_size > MAX_AGENT_CONFIG_BYTES:
        raise HandoffError("agent configuration exceeds its size limit")
    return value


def read_authorization_json(path: Path) -> object:
    path_state = check_authorization_file(path)
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        descriptor_state = os.fstat(descriptor)
        if state_signature(path_state) != state_signature(descriptor_state):
            raise HandoffError("agent configuration changed during inspection")
        content = bytearray()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_AGENT_CONFIG_BYTES:
                raise HandoffError("agent configuration exceeds its size limit")
        final_descriptor_state = os.fstat(descriptor)
        final_path_state = path.lstat()
        if (
            state_signature(descriptor_state)
            != state_signature(final_descriptor_state)
            or state_signature(final_descriptor_state)
            != state_signature(final_path_state)
        ):
            raise HandoffError("agent configuration changed during inspection")
        return json.loads(bytes(content))
    except HandoffError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"invalid agent configuration: {path}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def string_set(value: object, label: str, pattern: re.Pattern[str]) -> set[str]:
    if not isinstance(value, list) or not value:
        raise HandoffError(f"{label} must be a non-empty string list")
    output: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise HandoffError(f"{label} contains an invalid value")
        output.add(item.lower())
    return output


def authorization(path: Path) -> dict[str, Any]:
    value = read_authorization_json(path)
    peer = value.get("githubPeer") if isinstance(value, dict) else None
    if not isinstance(peer, dict):
        raise HandoffError("agent configuration has no githubPeer authorization")
    local_peer = peer.get("localPeer")
    if local_peer not in RECIPIENTS:
        raise HandoffError("githubPeer.localPeer must name one known local peer")
    repositories = string_set(peer.get("repositories"), "githubPeer.repositories", SLUG_RE)
    authors = string_set(
        peer.get("trustedAuthors"),
        "githubPeer.trustedAuthors",
        re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"),
    )
    global _FORGE
    _FORGE = forge_authorization(peer)
    return {
        "repositories": repositories,
        "authors": authors,
        "local_peer": local_peer,
        "forge": _FORGE,
    }


def forge_authorization(peer: dict[str, Any]) -> dict[str, Any]:
    """Resolve the Forgejo endpoint and credential for this host.

    Absent a `githubPeer.forge` block the caller is still on github.com and
    keeps the historical `gh` transport, so an unmigrated peer is unaffected.
    """
    forge = peer.get("forge")
    if forge is None:
        return {"kind": "github"}
    if not isinstance(forge, dict):
        raise HandoffError("githubPeer.forge must be an object")
    base = forge.get("apiBase")
    if (
        not isinstance(base, str)
        or not FORGE_API_BASE_RE.fullmatch(base)
    ):
        raise HandoffError("githubPeer.forge.apiBase must be an https API base URL")
    token_path = forge.get("tokenPath")
    if not isinstance(token_path, str) or not token_path.startswith("/"):
        raise HandoffError("githubPeer.forge.tokenPath must be an absolute path")
    return {
        "kind": "forgejo",
        "api_base": base.rstrip("/"),
        "token_path": Path(token_path),
    }


def forge_token(path: Path) -> str:
    check_authorization_file(path)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HandoffError("cannot read the forge API credential") from exc
    if not FORGE_TOKEN_RE.fullmatch(value):
        raise HandoffError("forge API credential is malformed")
    return value


def context(args: argparse.Namespace) -> tuple[Path, str, dict[str, Any]]:
    root = repository_root(args.repo)
    slug = repository_slug(root)
    auth = authorization(authorization_path(args))
    if slug not in auth["repositories"]:
        raise HandoffError(f"repository is not enrolled for GitHub peer work: {slug}")
    return root, slug, auth


def require_local_peer(auth: dict[str, Any], claimed: str, action: str) -> str:
    local_peer = auth["local_peer"]
    if claimed != local_peer:
        raise HandoffError(f"{action} is not authorized for this host's local peer")
    return local_peer


def gh_json(
    root: Path,
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    forge = _FORGE
    if forge is not None and forge.get("kind") == "forgejo":
        return forge_json(endpoint, method=method, payload=payload, forge=forge)
    command = ["gh", "api"]
    if method != "GET":
        command.extend(["--method", method])
    command.append(endpoint)
    input_text = None
    if payload is not None:
        command.extend(["--input", "-"])
        input_text = json.dumps(payload, sort_keys=True)
    output = run(command, cwd=root, input_text=input_text).stdout
    if not output.strip():
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise HandoffError("GitHub returned invalid JSON") from exc


def forge_json(
    endpoint: str,
    *,
    method: str,
    payload: dict[str, Any] | None,
    forge: dict[str, Any],
) -> Any:
    """Call Forgejo's REST API with the host's own credential.

    The request is issued in-process rather than through a helper binary so
    the token never reaches argv or a child environment, and the response is
    size-capped for the same reason every other input here is bounded.
    """
    # The credential is sent as a bearer header, so an endpoint that redirects
    # the request to another origin would leak it. Endpoints are built by this
    # script, never by a remote, but keep that guarantee enforced.
    relative = endpoint.lstrip("/")
    if (
        "://" in relative
        or relative.startswith("/")
        or any(part == ".." for part in relative.split("?", 1)[0].split("/"))
    ):
        raise HandoffError("forge endpoint escaped its API base")
    token = forge_token(forge["token_path"])
    url = f"{forge['api_base']}/{relative}"
    body = None
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": "agent-system-handoff/1",
    }
    if payload is not None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    timeout = COMMAND_TIMEOUT_SECONDS
    if _COMMAND_DEADLINE is not None:
        remaining = _COMMAND_DEADLINE - time.monotonic()
        if remaining <= 0:
            raise HandoffError("provider operation exceeded its overall deadline")
        timeout = min(timeout, remaining)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(FORGE_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = sanitized_error(f"forge request failed: {exc.code}")
        raise HandoffError(detail) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise HandoffError("forge request failed") from exc
    if len(raw) > FORGE_MAX_RESPONSE_BYTES:
        raise HandoffError("the forge returned an oversized response")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HandoffError("the forge returned invalid JSON") from exc


def paginated(
    root: Path,
    endpoint: str,
    *,
    max_pages: int = MAX_COMMENT_PAGES,
    budget_label: str = "provider result",
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, max_pages + 1):
        response = gh_json(root, f"{endpoint}{separator}per_page=100&page={page}")
        if not isinstance(response, list):
            raise HandoffError("GitHub returned an invalid paginated response")
        if not all(isinstance(item, dict) for item in response):
            raise HandoffError("GitHub returned an invalid item")
        values.extend(response)
        if len(response) < 100:
            return values
    raise HandoffError(
        f"{budget_label} exceeded the {max_pages * 100}-item safety budget"
    )


def validate_text(value: object, label: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise HandoffError(f"{label} must be a string")
    cleaned = value.strip()
    if required and not cleaned:
        raise HandoffError(f"{label} is required")
    if len(cleaned) > MAX_TEXT:
        raise HandoffError(f"{label} exceeds {MAX_TEXT} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise HandoffError(f"{label} contains control characters")
    if "<!--" in cleaned or "-->" in cleaned:
        raise HandoffError(f"{label} contains a reserved marker")
    return cleaned


def validate_sha(value: str) -> str:
    normalized = value.lower()
    if not SHA_RE.fullmatch(normalized):
        raise HandoffError("head SHA must be exactly 40 lowercase hexadecimal characters")
    return normalized


def validate_pr_data(value: object, slug: str, number: int, head: str | None = None) -> str:
    if number < 1:
        raise HandoffError("pull request number must be positive")
    try:
        actual_head = value["head"]["sha"]
        actual_repository = value["base"]["repo"]["full_name"]
        state = value["state"]
    except (KeyError, TypeError) as exc:
        raise HandoffError("GitHub returned invalid pull request data") from exc
    if not isinstance(actual_repository, str) or actual_repository.lower() != slug:
        raise HandoffError("pull request does not belong to the enrolled repository")
    if state != "open":
        raise HandoffError("pull request is not open")
    if not isinstance(actual_head, str) or not SHA_RE.fullmatch(actual_head):
        raise HandoffError("pull request head SHA is invalid")
    if head is not None and actual_head != head:
        raise HandoffError("pull request head has drifted from the handoff SHA")
    return actual_head


def validate_pr(root: Path, slug: str, number: int, head: str) -> dict[str, Any]:
    value = gh_json(root, f"repos/{slug}/pulls/{number}")
    validate_pr_data(value, slug, number, head)
    return value


def author_permission(root: Path, slug: str, author: str) -> str:
    value = gh_json(root, f"repos/{slug}/collaborators/{author}/permission")
    permission = value.get("permission") if isinstance(value, dict) else None
    if permission not in WRITE_PERMISSIONS:
        raise AuthorRejected("handoff author lacks repository write authority")
    return permission


def validate_author(
    root: Path,
    slug: str,
    auth: dict[str, Any],
    author: object,
    cache: dict[str, str] | None = None,
) -> str:
    if not isinstance(author, str) or author.lower() not in auth["authors"]:
        raise AuthorRejected("handoff author is not trusted")
    normalized = author.lower()
    if cache is not None and normalized in cache:
        return normalized
    permission = author_permission(root, slug, author)
    if cache is not None:
        cache[normalized] = permission
    return normalized


def authenticated_author(root: Path, slug: str, auth: dict[str, Any]) -> str:
    value = gh_json(root, "user")
    login = value.get("login") if isinstance(value, dict) else None
    return validate_author(root, slug, auth, login)


def request_id(packet: dict[str, Any]) -> str:
    identity = {
        key: packet[key]
        for key in (
            "repository",
            "pull_request",
            "head_sha",
            "from",
            "to",
            "role",
            "objective",
            "checks",
        )
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def request_packet(
    *,
    slug: str,
    pull_request: int,
    head: str,
    sender: str,
    recipient: str,
    role: str,
    objective: str,
    checks: list[str],
) -> dict[str, Any]:
    if sender not in RECIPIENTS or recipient not in RECIPIENTS or sender == recipient:
        raise HandoffError("from and to must be distinct known peer recipients")
    if role not in ROLES:
        raise HandoffError("role is not supported")
    normalized_checks = sorted(set(checks))
    if not normalized_checks or any(item not in CHECKS for item in normalized_checks):
        raise HandoffError("checks must contain only supported symbolic check IDs")
    if role == "macos-validation" and not set(normalized_checks).intersection(MACOS_SUITES):
        raise HandoffError("macos-validation requires a macOS check")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "event": "request",
        "repository": slug,
        "pull_request": pull_request,
        "head_sha": validate_sha(head),
        "from": sender,
        "to": recipient,
        "role": role,
        "objective": validate_text(objective, "objective"),
        "checks": normalized_checks,
        "authority": dict(AUTHORITY),
    }
    packet["request_id"] = request_id(packet)
    return packet


def transition_packet(request: dict[str, Any], event: str, actor: str, **values: Any) -> dict[str, Any]:
    if actor != request["to"]:
        raise HandoffError("only the addressed peer may acknowledge or complete a handoff")
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "request_id": request["request_id"],
        "repository": request["repository"],
        "pull_request": request["pull_request"],
        "head_sha": request["head_sha"],
        "actor": actor,
    }
    packet.update(values)
    validate_packet(packet)
    return packet


def validate_packet(packet: object) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise HandoffError("handoff packet must be an object")
    event = packet.get("event")
    common = {
        "schema_version",
        "event",
        "request_id",
        "repository",
        "pull_request",
        "head_sha",
    }
    if event == "request":
        expected = common | {"from", "to", "role", "objective", "checks", "authority"}
    elif event == "ack":
        expected = common | {"actor"}
    elif event == "complete":
        expected = common | {"actor", "outcome", "summary"}
    else:
        raise HandoffError("handoff event is invalid")
    if set(packet) != expected:
        raise HandoffError("handoff packet fields do not match its event schema")
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise HandoffError("handoff schema version is unsupported")
    request_value = packet.get("request_id")
    if not isinstance(request_value, str) or not REQUEST_ID_RE.fullmatch(request_value):
        raise HandoffError("handoff request ID is invalid")
    repository = packet.get("repository")
    if not isinstance(repository, str) or not SLUG_RE.fullmatch(repository):
        raise HandoffError("handoff repository is invalid")
    if type(packet.get("pull_request")) is not int or packet["pull_request"] < 1:
        raise HandoffError("handoff pull request is invalid")
    if not isinstance(packet.get("head_sha"), str):
        raise HandoffError("handoff head SHA is invalid")
    validate_sha(packet["head_sha"])
    if event == "request":
        sender = packet.get("from")
        recipient = packet.get("to")
        role = packet.get("role")
        if sender not in RECIPIENTS or recipient not in RECIPIENTS or sender == recipient:
            raise HandoffError("handoff peer addresses are invalid")
        if role not in ROLES:
            raise HandoffError("handoff role is invalid")
        checks = packet.get("checks")
        if (
            not isinstance(checks, list)
            or not checks
            or checks != sorted(set(checks))
            or any(item not in CHECKS for item in checks)
        ):
            raise HandoffError("handoff checks are invalid")
        if role == "macos-validation" and not set(checks).intersection(MACOS_SUITES):
            raise HandoffError("macos-validation requires a macOS check")
        validate_text(packet.get("objective"), "objective")
        if packet.get("authority") != AUTHORITY:
            raise HandoffError("handoff authority must remain fully constrained")
        if request_id(packet) != request_value:
            raise HandoffError("handoff request ID does not match its immutable request")
    else:
        if packet.get("actor") not in RECIPIENTS:
            raise HandoffError("handoff actor is invalid")
        if event == "complete":
            if packet.get("outcome") not in OUTCOMES:
                raise HandoffError("handoff outcome is invalid")
            validate_text(packet.get("summary"), "summary")
    return packet


def encode_comment(packet: dict[str, Any]) -> str:
    validate_packet(packet)
    payload = json.dumps(packet, sort_keys=True, separators=(",", ":"))
    return f"<!-- {MARKER}\n{payload}\n-->\n\nAgent peer handoff `{packet['request_id']}` ({packet['event']}).\n"


def decode_comment(body: object) -> dict[str, Any] | None:
    if not isinstance(body, str) or f"<!-- {MARKER}" not in body:
        return None
    if len(body.encode("utf-8")) > 32_000:
        raise HandoffError("handoff comment exceeds the size limit")
    pattern = re.compile(rf"<!-- {re.escape(MARKER)}\n(\{{.*?\}})\n-->", re.DOTALL)
    matches = pattern.findall(body)
    if len(matches) != 1:
        raise HandoffError("handoff comment must contain exactly one packet")
    try:
        packet = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise HandoffError("handoff comment contains invalid JSON") from exc
    return validate_packet(packet)


def issue_comments(root: Path, slug: str, pull_request: int) -> list[dict[str, Any]]:
    if pull_request < 1:
        raise HandoffError("pull request number must be positive")
    return paginated(
        root,
        f"repos/{slug}/issues/{pull_request}/comments",
        budget_label="pull request comment scan",
    )


def trusted_events(
    root: Path,
    slug: str,
    auth: dict[str, Any],
    comments: list[dict[str, Any]],
) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    output: list[tuple[int, dict[str, Any]]] = []
    ignored = 0
    permission_cache: dict[str, str] = {}
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or f"<!-- {MARKER}" not in body:
            continue
        try:
            author = comment.get("user", {}).get("login")
            validate_author(root, slug, auth, author, permission_cache)
        except AuthorRejected:
            ignored += 1
            continue
        try:
            packet = decode_comment(body)
            if packet is None:
                continue
            if packet["repository"].lower() != slug:
                raise HandoffError("handoff targets another repository")
            comment_id = comment.get("id")
            if type(comment_id) is not int or comment_id < 1:
                raise HandoffError("handoff comment ID is invalid")
            output.append((comment_id, packet))
        except HandoffError:
            ignored += 1
    return sorted(output), ignored


def reconcile(events: list[tuple[int, dict[str, Any]]]) -> tuple[dict[str, dict[str, Any]], int]:
    states: dict[str, dict[str, Any]] = {}
    rejected = 0
    for comment_id, event in events:
        request_value = event["request_id"]
        current = states.get(request_value)
        if event["event"] == "request":
            if current is None:
                states[request_value] = {
                    "request": event,
                    "state": "requested",
                    "outcome": None,
                    "comment_ids": [comment_id],
                }
            elif current["request"] == event:
                current["comment_ids"].append(comment_id)
            else:
                rejected += 1
            continue
        if current is None:
            rejected += 1
            continue
        request = current["request"]
        immutable_fields = ("repository", "pull_request", "head_sha", "request_id")
        if event["actor"] != request["to"] or any(
            event[field] != request[field] for field in immutable_fields
        ):
            rejected += 1
            continue
        if event["event"] == "ack":
            if current["state"] == "requested":
                current["state"] = "acknowledged"
                current["comment_ids"].append(comment_id)
            elif current["state"] != "acknowledged":
                rejected += 1
        elif event["event"] == "complete":
            if current["state"] in {"requested", "acknowledged"}:
                current["state"] = "completed"
                current["outcome"] = event["outcome"]
                current["summary"] = event["summary"]
                current["comment_ids"].append(comment_id)
            elif not (
                current.get("outcome") == event["outcome"]
                and current.get("summary") == event["summary"]
            ):
                rejected += 1
    return states, rejected


def load_states(
    root: Path,
    slug: str,
    auth: dict[str, Any],
    pull_request: int,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    events, ignored = trusted_events(
        root, slug, auth, issue_comments(root, slug, pull_request)
    )
    states, conflicts = reconcile(events)
    return states, ignored, conflicts


def require_request(
    root: Path,
    slug: str,
    auth: dict[str, Any],
    pull_request: int,
    request_value: str,
    head: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    if not REQUEST_ID_RE.fullmatch(request_value):
        raise HandoffError("request ID is invalid")
    states, _ignored, conflicts = load_states(root, slug, auth, pull_request)
    if conflicts:
        raise HandoffError("handoff thread contains conflicting trusted peer events")
    current = states.get(request_value)
    if current is None:
        raise HandoffError("handoff request was not found")
    request = current["request"]
    if request["pull_request"] != pull_request or request["head_sha"] != head:
        raise HandoffError("handoff request does not match the requested PR head")
    validate_pr(root, slug, pull_request, head)
    return request, current, states


def verify_public_lease(root: Path, lease_id: str | None, head: str) -> None:
    if not lease_id:
        raise HandoffError("--lease-id is required with --apply")
    result = run(
        ["agent-lease", "verify", lease_id, "--repo", str(root), "--head", head],
        cwd=root,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HandoffError("agent-lease returned invalid verification data") from exc
    if value.get("scope") != "public:mutation" or value.get("head") != head:
        raise HandoffError("lease is not the exact-head public mutation lease")


def queue_label(recipient: str) -> str:
    if recipient not in RECIPIENTS:
        raise HandoffError("queue recipient is invalid")
    return f"agent:{recipient.removesuffix('-cal')}-pending"


def pending_request_ids(
    states: dict[str, dict[str, Any]],
    recipient: str,
    head: str,
    *,
    excluding: str | None = None,
) -> list[str]:
    return sorted(
        request_value
        for request_value, current in states.items()
        if request_value != excluding
        and current["state"] == "requested"
        and current["request"]["to"] == recipient
        and current["request"]["head_sha"] == head
    )


def transition_queue_instruction(
    request: dict[str, Any], states: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    pending = pending_request_ids(
        states,
        request["to"],
        request["head_sha"],
        excluding=request["request_id"],
    )
    return {
        "queue_action": "keep" if pending else "remove",
        "queue_label": queue_label(request["to"]),
        "pending_sibling_request_ids": pending,
    }


def publish_comment(
    root: Path,
    slug: str,
    pull_request: int,
    packet: dict[str, Any],
    *,
    apply: bool,
    lease_id: str | None,
    queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    queue = queue or {
        "queue_action": "add",
        "queue_label": queue_label(packet["to"]),
    }
    output = {
        "event": packet["event"],
        "head_sha": packet["head_sha"],
        "request_id": packet["request_id"],
        "would_write": not apply,
        # queue_action is the caller's next step, not a receipt. The label is a
        # separate lease-admitted write, so say so rather than letting a
        # published comment read as a queued handoff.
        "queue_applied": False,
        **queue,
    }
    if not apply:
        return output
    verify_public_lease(root, lease_id, packet["head_sha"])
    validate_pr(root, slug, pull_request, packet["head_sha"])
    value = gh_json(
        root,
        f"repos/{slug}/issues/{pull_request}/comments",
        method="POST",
        payload={"body": encode_comment(packet)},
    )
    comment_id = value.get("id") if isinstance(value, dict) else None
    if type(comment_id) is not int:
        raise HandoffError("GitHub did not return the created comment ID")
    output.update({"comment_id": comment_id, "published": True, "would_write": False})
    return output


def request_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    validate_pr(root, slug, args.pr, head)
    authenticated_author(root, slug, auth)
    require_local_peer(auth, args.sender, "request sender")
    packet = request_packet(
        slug=slug,
        pull_request=args.pr,
        head=head,
        sender=args.sender,
        recipient=args.recipient,
        role=args.role,
        objective=args.objective,
        checks=args.check,
    )
    states, _ignored, conflicts = load_states(root, slug, auth, args.pr)
    if conflicts:
        raise HandoffError("handoff thread contains conflicting trusted peer events")
    existing = states.get(packet["request_id"])
    if existing:
        if existing["request"] != packet:
            raise HandoffError("request ID collides with a different handoff")
        queue = (
            {"queue_action": "add", "queue_label": queue_label(packet["to"])}
            if existing["state"] == "requested"
            else transition_queue_instruction(packet, states)
        )
        print(
            json.dumps(
                {
                    "event": "request",
                    "head_sha": head,
                    "published": False,
                    **queue,
                    "reason": "already-current",
                    "request_id": packet["request_id"],
                    "state": existing["state"],
                },
                sort_keys=True,
            )
        )
        return 0
    print(
        json.dumps(
            publish_comment(
                root,
                slug,
                args.pr,
                packet,
                apply=args.apply,
                lease_id=args.lease_id,
            ),
            sort_keys=True,
        )
    )
    return 0


def list_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    require_local_peer(auth, args.recipient, "queue listing")
    states, ignored, conflicts = load_states(root, slug, auth, args.pr)
    items: list[dict[str, Any]] = []
    for request_value, current in sorted(states.items()):
        request = current["request"]
        if request["to"] != args.recipient:
            continue
        if request["pull_request"] != args.pr:
            continue
        if current["state"] == "completed" and not args.include_complete:
            continue
        try:
            validate_pr(root, slug, request["pull_request"], request["head_sha"])
            current_head = True
        except HandoffError:
            current_head = False
        item = {
            "checks": request["checks"],
            "current_head": current_head,
            "from": request["from"],
            "head_sha": request["head_sha"],
            "outcome": current["outcome"],
            "pull_request": request["pull_request"],
            "request_id": request_value,
            "role": request["role"],
            "state": current["state"],
            "to": request["to"],
        }
        if current["state"] == "completed":
            item["summary"] = current.get("summary", "")
        items.append(item)
    print(
        json.dumps(
            {
                "handoffs": items,
                "conflicting_trusted_events": conflicts,
                "ignored_invalid_or_untrusted_events": ignored,
            },
            sort_keys=True,
        )
    )
    return 0


def show_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    request, _current, _states = require_request(
        root, slug, auth, args.pr, args.request_id, head
    )
    authenticated_author(root, slug, auth)
    local_peer = require_local_peer(auth, args.actor, "handoff inspection")
    if local_peer != request["to"]:
        raise HandoffError("only the addressed peer may inspect the handoff objective")
    print(json.dumps({"request": request}, sort_keys=True))
    return 0


def signal_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    request, current, states = require_request(root, slug, auth, args.pr, args.request_id, head)
    authenticated_author(root, slug, auth)
    if args.recipient != request["to"]:
        raise HandoffError("queue recipient does not match the handoff")
    if args.state == "present" and current["state"] != "requested":
        raise HandoffError("only a requested handoff may enter the peer queue")
    if args.state == "absent" and current["state"] == "requested":
        raise HandoffError("acknowledge or complete the handoff before removing its queue signal")
    if args.state == "present":
        require_local_peer(auth, request["from"], "queue publication")
    else:
        require_local_peer(auth, request["to"], "queue removal")
    label = queue_label(args.recipient)
    values = paginated(root, f"repos/{slug}/issues/{args.pr}/labels")
    present = any(item.get("name") == label for item in values)
    desired = args.state == "present"
    pending_siblings = pending_request_ids(states, args.recipient, head)
    if not desired and pending_siblings:
        print(
            json.dumps(
                {
                    "effective_state": "present",
                    "head_sha": head,
                    "label": label,
                    "pending_request_ids": pending_siblings,
                    "published": False,
                    "reason": "pending-recipient-requests",
                    "request_id": args.request_id,
                },
                sort_keys=True,
            )
        )
        return 0
    if present == desired:
        print(
            json.dumps(
                {
                    "head_sha": head,
                    "label": label,
                    "published": False,
                    "reason": "already-current",
                    "request_id": args.request_id,
                    "state": args.state,
                },
                sort_keys=True,
            )
        )
        return 0
    if not args.apply:
        print(
            json.dumps(
                {
                    "head_sha": head,
                    "label": label,
                    "request_id": args.request_id,
                    "state": args.state,
                    "would_write": True,
                },
                sort_keys=True,
            )
        )
        return 0
    verify_public_lease(root, args.lease_id, head)
    validate_pr(root, slug, args.pr, head)
    if desired:
        gh_json(
            root,
            f"repos/{slug}/issues/{args.pr}/labels",
            method="POST",
            payload={"labels": [label]},
        )
    else:
        gh_json(
            root,
            f"repos/{slug}/issues/{args.pr}/labels/{quote(label, safe='')}",
            method="DELETE",
        )
    print(
        json.dumps(
            {
                "head_sha": head,
                "label": label,
                "published": True,
                "request_id": args.request_id,
                "state": args.state,
                "would_write": False,
            },
            sort_keys=True,
        )
    )
    return 0


def queue_search(
    root: Path,
    organization: str,
    label: str,
    candidate_limit: int,
) -> dict[str, Any]:
    """Return the queue page in GitHub's issue-search shape.

    Forgejo has no `search/issues`; its equivalent is `repos/issues/search`,
    which returns a bare array and reports totals in a header this client does
    not read. Normalize it into the one shape the caller already validates so
    the discovery logic stays identical on both forges.
    """
    if _FORGE is None or _FORGE.get("kind") != "forgejo":
        query = f'org:{organization} is:pr is:open label:"{label}"'
        return gh_json(
            root,
            f"search/issues?q={quote(query, safe='')}"
            f"&sort=updated&order=desc&per_page={candidate_limit}",
        )
    parameters = urlencode(
        {
            "type": "pulls",
            "state": "open",
            "labels": label,
            "owner": organization,
            "sort": "updated",
            "order": "desc",
            "limit": candidate_limit,
        }
    )
    value = gh_json(root, f"repos/issues/search?{parameters}")
    if not isinstance(value, list):
        raise HandoffError("the forge returned invalid issue search data")
    items = value[:candidate_limit]
    for item in items:
        if not isinstance(item, dict):
            raise HandoffError("the forge returned invalid issue search data")
        # GitHub marks pull requests with this key; discovery relies on it.
        item.setdefault("pull_request", {})
    return {
        "items": items,
        "total_count": len(items),
        "incomplete_results": len(value) > candidate_limit,
    }


def search_slug(item: dict[str, Any]) -> str | None:
    repository = item.get("repository_url")
    if isinstance(repository, str):
        match = re.fullmatch(
            r"https://api\.github\.com/repos/([^/]+/[^/]+)", repository
        )
        if not match or not SLUG_RE.fullmatch(match.group(1)):
            return None
        return match.group(1).lower()
    # Forgejo returns a repository object rather than an API URL.
    value = item.get("repository")
    if not isinstance(value, dict):
        return None
    owner = value.get("owner")
    name = value.get("name")
    if not isinstance(owner, str) or not isinstance(name, str):
        full = value.get("full_name")
        if not isinstance(full, str) or not SLUG_RE.fullmatch(full):
            return None
        return full.lower()
    slug = f"{owner}/{name}"
    if not SLUG_RE.fullmatch(slug):
        return None
    return slug.lower()


def discover_command(args: argparse.Namespace) -> int:
    root = repository_root(args.repo)
    auth = authorization(authorization_path(args))
    require_local_peer(auth, args.recipient, "queue discovery")
    organization = args.organization.lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38})", organization):
        raise HandoffError("organization is invalid")
    enrolled_for_org = {
        slug for slug in auth["repositories"] if slug.partition("/")[0] == organization
    }
    if not enrolled_for_org:
        raise HandoffError("organization has no enrolled peer repositories")
    if not 1 <= args.limit <= 25:
        raise HandoffError("--limit must be between 1 and 25")
    candidate_limit = min(
        MAX_DISCOVERY_CANDIDATES,
        max(args.limit, args.limit * DISCOVERY_OVERSCAN_MULTIPLIER),
    )
    label = queue_label(args.recipient)
    search = queue_search(root, organization, label, candidate_limit)
    items = search.get("items") if isinstance(search, dict) else None
    total = search.get("total_count") if isinstance(search, dict) else None
    incomplete = search.get("incomplete_results") if isinstance(search, dict) else None
    if (
        not isinstance(items, list)
        or type(total) is not int
        or total < 0
        or type(incomplete) is not bool
    ):
        raise HandoffError("GitHub returned invalid issue search data")
    candidates = items[:candidate_limit]
    results: list[dict[str, Any]] = []
    ignored = 0
    rejected = 0
    result_overflow = False
    for item in candidates:
        if not isinstance(item, dict) or "pull_request" not in item:
            ignored += 1
            continue
        slug = search_slug(item)
        number = item.get("number")
        if slug not in enrolled_for_org or type(number) is not int or number < 1:
            ignored += 1
            continue
        pr = gh_json(root, f"repos/{slug}/pulls/{number}")
        try:
            head = validate_pr_data(pr, slug, number)
        except HandoffError:
            rejected += 1
            continue
        states, invalid_or_untrusted, conflicts = load_states(root, slug, auth, number)
        ignored += invalid_or_untrusted
        rejected += conflicts
        if conflicts:
            continue
        for request_value, current in sorted(states.items()):
            request = current["request"]
            if (
                request["to"] != args.recipient
                or request["pull_request"] != number
                or request["head_sha"] != head
                or current["state"] != "requested"
            ):
                continue
            results.append(
                {
                    "checks": request["checks"],
                    "from": request["from"],
                    "head_sha": head,
                    "pull_request": number,
                    "repository": slug,
                    "request_id": request_value,
                    "role": request["role"],
                    "to": request["to"],
                }
            )
            if len(results) > args.limit:
                result_overflow = True
                break
        if result_overflow:
            break
    print(
        json.dumps(
            {
                "handoffs": results[: args.limit],
                "ignored_invalid_untrusted_or_unenrolled": ignored,
                "label": label,
                "conflicting_trusted_events": rejected,
                "truncated": (
                    incomplete
                    or total > len(items)
                    or len(items) > candidate_limit
                    or result_overflow
                ),
            },
            sort_keys=True,
        )
    )
    return 0


def ack_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    request, current, states = require_request(root, slug, auth, args.pr, args.request_id, head)
    authenticated_author(root, slug, auth)
    local_peer = require_local_peer(auth, args.actor, "handoff acknowledgement")
    if local_peer != request["to"]:
        raise HandoffError("actor is not the addressed peer")
    queue = transition_queue_instruction(request, states)
    if current["state"] in {"acknowledged", "completed"}:
        print(
            json.dumps(
                {
                    "event": "ack",
                    "head_sha": head,
                    "published": False,
                    **queue,
                    "reason": "already-current",
                    "request_id": args.request_id,
                    "state": current["state"],
                },
                sort_keys=True,
            )
        )
        return 0
    packet = transition_packet(request, "ack", args.actor)
    print(
        json.dumps(
            publish_comment(
                root,
                slug,
                args.pr,
                packet,
                apply=args.apply,
                lease_id=args.lease_id,
                queue=queue,
            ),
            sort_keys=True,
        )
    )
    return 0


def complete_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    request, current, states = require_request(root, slug, auth, args.pr, args.request_id, head)
    authenticated_author(root, slug, auth)
    local_peer = require_local_peer(auth, args.actor, "handoff completion")
    if local_peer != request["to"]:
        raise HandoffError("actor is not the addressed peer")
    queue = transition_queue_instruction(request, states)
    summary = validate_text(args.summary, "summary")
    if current["state"] == "completed":
        if current["outcome"] != args.outcome or current.get("summary") != summary:
            raise HandoffError("handoff is already complete with a different result")
        print(
            json.dumps(
                {
                    "event": "complete",
                    "head_sha": head,
                    "published": False,
                    **queue,
                    "reason": "already-current",
                    "request_id": args.request_id,
                    "state": "completed",
                },
                sort_keys=True,
            )
        )
        return 0
    packet = transition_packet(
        request,
        "complete",
        args.actor,
        outcome=args.outcome,
        summary=summary,
    )
    print(
        json.dumps(
            publish_comment(
                root,
                slug,
                args.pr,
                packet,
                apply=args.apply,
                lease_id=args.lease_id,
                queue=queue,
            ),
            sort_keys=True,
        )
    )
    return 0


def attestation_context(suite: str) -> str:
    if suite not in MACOS_SUITES:
        raise HandoffError("macOS attestation suite is unsupported")
    return f"agent-system/platform/macos/{suite}"


def existing_status(root: Path, slug: str, head: str, status_context: str) -> dict[str, Any] | None:
    value = gh_json(root, f"repos/{slug}/commits/{head}/status")
    statuses = value.get("statuses") if isinstance(value, dict) else None
    # GitHub returns an empty list for an unreported commit; Forgejo returns
    # null. Both mean "no status yet", which is not a protocol violation.
    if statuses is None and isinstance(value, dict) and "statuses" in value:
        statuses = []
    if not isinstance(statuses, list):
        raise HandoffError("the forge returned invalid commit status data")
    return next(
        (
            item
            for item in statuses
            if isinstance(item, dict) and item.get("context") == status_context
        ),
        None,
    )


def attest_command(args: argparse.Namespace) -> int:
    root, slug, auth = context(args)
    head = validate_sha(args.head)
    request, _current, _states = require_request(
        root, slug, auth, args.pr, args.request_id, head
    )
    authenticated_author(root, slug, auth)
    require_local_peer(auth, "mac-cal", "macOS attestation")
    if request["to"] != "mac-cal" or request["role"] != "macos-validation":
        raise HandoffError("platform attestation requires a Mac-addressed validation handoff")
    if args.suite not in request["checks"]:
        raise HandoffError("attestation suite was not requested by the handoff")
    if platform.system() != "Darwin":
        raise HandoffError("macOS platform attestation can run only on Darwin")
    machine = platform.machine().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{1,32}", machine):
        raise HandoffError("host architecture is invalid")
    status_context = attestation_context(args.suite)
    description = f"{args.state} {args.request_id[:12]} Darwin/{machine}"
    current = existing_status(root, slug, head, status_context)
    if current and current.get("state") == args.state and current.get("description") == description:
        print(
            json.dumps(
                {
                    "context": status_context,
                    "head_sha": head,
                    "published": False,
                    "reason": "already-current",
                    "state": args.state,
                },
                sort_keys=True,
            )
        )
        return 0
    if not args.apply:
        print(
            json.dumps(
                {
                    "context": status_context,
                    "head_sha": head,
                    "state": args.state,
                    "would_write": True,
                },
                sort_keys=True,
            )
        )
        return 0
    verify_public_lease(root, args.lease_id, head)
    validate_pr(root, slug, args.pr, head)
    gh_json(
        root,
        f"repos/{slug}/statuses/{head}",
        method="POST",
        payload={
            "context": status_context,
            "description": description,
            "state": args.state,
        },
    )
    print(
        json.dumps(
            {
                "context": status_context,
                "head_sha": head,
                "published": True,
                "state": args.state,
                "would_write": False,
            },
            sort_keys=True,
        )
    )
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_OPERATION_TIMEOUT_SECONDS,
    )


def add_mutation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--lease-id")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    request_parser = commands.add_parser("request")
    add_common(request_parser)
    add_mutation(request_parser)
    request_parser.add_argument("--pr", type=int, required=True)
    request_parser.add_argument("--head", required=True)
    request_parser.add_argument("--from", required=True, dest="sender", choices=sorted(RECIPIENTS))
    request_parser.add_argument("--to", required=True, dest="recipient", choices=sorted(RECIPIENTS))
    request_parser.add_argument("--role", required=True, choices=sorted(ROLES))
    request_parser.add_argument("--objective", required=True)
    request_parser.add_argument("--check", action="append", required=True, choices=sorted(CHECKS))
    request_parser.set_defaults(handler=request_command)

    list_parser = commands.add_parser("list")
    add_common(list_parser)
    list_parser.add_argument("--to", required=True, dest="recipient", choices=sorted(RECIPIENTS))
    list_parser.add_argument("--pr", type=int, required=True)
    list_parser.add_argument("--include-complete", action="store_true")
    list_parser.set_defaults(handler=list_command)

    show_parser = commands.add_parser("show")
    add_common(show_parser)
    show_parser.add_argument("--pr", type=int, required=True)
    show_parser.add_argument("--head", required=True)
    show_parser.add_argument("--request-id", required=True)
    show_parser.add_argument("--actor", required=True, choices=sorted(RECIPIENTS))
    show_parser.set_defaults(handler=show_command)

    discover_parser = commands.add_parser("discover")
    add_common(discover_parser)
    discover_parser.add_argument("--organization", required=True)
    discover_parser.add_argument("--to", required=True, dest="recipient", choices=sorted(RECIPIENTS))
    discover_parser.add_argument("--limit", type=int, default=20)
    discover_parser.set_defaults(handler=discover_command)

    ack_parser = commands.add_parser("ack")
    add_common(ack_parser)
    add_mutation(ack_parser)
    ack_parser.add_argument("--pr", type=int, required=True)
    ack_parser.add_argument("--head", required=True)
    ack_parser.add_argument("--request-id", required=True)
    ack_parser.add_argument("--actor", required=True, choices=sorted(RECIPIENTS))
    ack_parser.set_defaults(handler=ack_command)

    signal_parser = commands.add_parser("signal")
    add_common(signal_parser)
    add_mutation(signal_parser)
    signal_parser.add_argument("--pr", type=int, required=True)
    signal_parser.add_argument("--head", required=True)
    signal_parser.add_argument("--request-id", required=True)
    signal_parser.add_argument("--to", required=True, dest="recipient", choices=sorted(RECIPIENTS))
    signal_parser.add_argument("--state", required=True, choices=("absent", "present"))
    signal_parser.set_defaults(handler=signal_command)

    complete_parser = commands.add_parser("complete")
    add_common(complete_parser)
    add_mutation(complete_parser)
    complete_parser.add_argument("--pr", type=int, required=True)
    complete_parser.add_argument("--head", required=True)
    complete_parser.add_argument("--request-id", required=True)
    complete_parser.add_argument("--actor", required=True, choices=sorted(RECIPIENTS))
    complete_parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    complete_parser.add_argument("--summary", required=True)
    complete_parser.set_defaults(handler=complete_command)

    attest_parser = commands.add_parser("attest")
    add_common(attest_parser)
    add_mutation(attest_parser)
    attest_parser.add_argument("--pr", type=int, required=True)
    attest_parser.add_argument("--head", required=True)
    attest_parser.add_argument("--request-id", required=True)
    attest_parser.add_argument("--suite", required=True, choices=sorted(MACOS_SUITES))
    attest_parser.add_argument("--state", required=True, choices=sorted(STATUS_STATES))
    attest_parser.set_defaults(handler=attest_command)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "apply") and not args.apply and getattr(args, "lease_id", None):
        raise HandoffError("--lease-id is valid only with --apply")
    with operation_deadline(args.timeout_seconds):
        return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, HandoffError) as exc:
        print(f"agent-github-handoff: {exc}", file=sys.stderr)
        raise SystemExit(1)
