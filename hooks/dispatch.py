#!/usr/bin/env python3
"""Dispatch host hook events to manifests owned by global and repository skills."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from lib.host_contract import hook_budgets

EVENT_ALIASES = {
    "stop": "Stop",
    "pretooluse": "PreToolUse",
    "pre_tool_use": "PreToolUse",
}
MAX_RUNTIME_SKILLS = 256
MAX_MANIFEST_BYTES = 64 * 1024
MAX_HOOK_OUTPUT_BYTES = 256 * 1024
PROCESS_GROUP_GRACE_SECONDS = 0.2


@dataclass(frozen=True)
class HookOwner:
    manifest: Path
    boundary: Path
    reject_symlinks: bool


class HookOutputLimitError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("claude", "codex", "cursor"), default="claude")
    parser.add_argument("event")
    return parser.parse_args()


def hook_input(raw: str) -> dict:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def canonical_event(value: str) -> str:
    return EVENT_ALIASES.get(value.replace("-", "").lower(), value)


def payload_cwd(payload: dict) -> Path:
    for key in ("cwd", "workspace_root", "workspaceRoot", "project_dir", "projectDir"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return Path(value).expanduser()
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots")
    if isinstance(roots, list) and roots:
        first = roots[0]
        if isinstance(first, str):
            return Path(first).expanduser()
        if isinstance(first, dict):
            for key in ("path", "root", "uri"):
                value = first.get(key)
                if isinstance(value, str) and value:
                    return Path(value.removeprefix("file://")).expanduser()
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def project_root(payload: dict, timeout: float | None = None) -> Path:
    start = payload_cwd(payload).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return Path(result.stdout.strip()).resolve() if result.returncode == 0 else start
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("event-wide hook budget exhausted during project discovery") from exc
    except OSError:
        return start


def emit(host: str, event: str, reason: str | None = None) -> int:
    if host == "cursor":
        if reason and event == "Stop":
            print(json.dumps({"followup_message": reason}))
            return 0
        if event == "PreToolUse":
            if reason:
                print(json.dumps({
                    "permission": "deny",
                    "user_message": reason,
                    "agent_message": reason,
                }))
                return 2
            print(json.dumps({"permission": "allow"}))
            return 0
        print("{}")
        return 0

    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def symlink_component(root: Path, path: Path) -> Path | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return current
    return None


def safe_command(owner: HookOwner, command: list[str]) -> list[str]:
    skill_dir = owner.manifest.parent
    executable = Path(command[0])
    if executable.is_absolute():
        raise ValueError("hook executable must be skill-relative")
    candidate = skill_dir / executable
    if owner.reject_symlinks:
        link = symlink_component(skill_dir, candidate)
        if link is not None:
            raise ValueError(f"repository hook executable path must not be a symlink: {link}")
    executable = candidate.resolve()
    resolved_skill = skill_dir.resolve()
    resolved_boundary = owner.boundary.resolve()
    if resolved_skill not in executable.parents:
        raise ValueError("relative hook executable escapes its skill directory")
    if executable != resolved_boundary and resolved_boundary not in executable.parents:
        raise ValueError("relative hook executable escapes its declared skill root")
    return [str(executable), *command[1:]]


def system_hook_contract() -> tuple[set[str], dict[str, int]]:
    try:
        catalog = json.loads((SYSTEM_ROOT / "system.json").read_text(encoding="utf-8"))
        events = catalog["hookEvents"]
        budgets = hook_budgets(catalog)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid system hook catalog: {exc}") from exc
    if not isinstance(events, list) or not events or not all(isinstance(event, str) for event in events):
        raise ValueError("system hook catalog must contain hookEvents")
    return set(events), budgets


def direct_children(root: Path) -> list[Path]:
    if root.is_symlink():
        raise ValueError(f"skill root must not be a symlink: {root}")
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError(f"skill root must be a directory: {root}")
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ValueError(f"cannot list skill root {root}: {exc}") from exc
    if len(children) > MAX_RUNTIME_SKILLS:
        raise ValueError(
            f"skill root contains {len(children)} entries; runtime limit is {MAX_RUNTIME_SKILLS}: {root}"
        )
    return children


def global_hook_owners(agents_home: Path) -> list[HookOwner]:
    skill_root = agents_home / "skills"
    manifest_path = agents_home / "managed-install.json"
    managed: dict = {}
    if manifest_path.is_file() and not manifest_path.is_symlink():
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            managed = document.get("paths", {}) if isinstance(document, dict) else {}
        except (OSError, json.JSONDecodeError):
            managed = {}
    owners: list[HookOwner] = []
    for directory in direct_children(skill_root):
        if directory.is_symlink():
            entry = managed.get(str(directory)) if isinstance(managed, dict) else None
            expected = SYSTEM_ROOT / "skills" / directory.name
            if (
                not isinstance(entry, dict)
                or entry.get("kind") != "symlink"
                or not isinstance(entry.get("target"), str)
                or Path(entry["target"]).resolve(strict=False) != expected.resolve(strict=False)
                or directory.resolve(strict=False) != expected.resolve(strict=False)
            ):
                raise ValueError(f"unmanaged global skill symlink: {directory}")
        elif not directory.is_dir():
            continue
        skill_file = directory / "SKILL.md"
        hook_file = directory / "hooks.json"
        if hook_file.exists() and not skill_file.is_file():
            raise ValueError(f"{hook_file}: hooks require an adjacent SKILL.md")
        if not skill_file.is_file() or not hook_file.is_file():
            continue
        if not directory.is_symlink() and (skill_file.is_symlink() or hook_file.is_symlink()):
            raise ValueError(f"global skill files must not be symlinks: {directory}")
        owners.append(HookOwner(hook_file, directory.resolve(), False))
    return owners


def repository_hook_owners(root: Path) -> list[HookOwner]:
    agents_root = root / ".agents"
    skill_root = agents_root / "skills"
    for candidate in (agents_root, skill_root):
        if candidate.is_symlink():
            raise ValueError(f"repository skill path must not be a symlink: {candidate}")
    owners: list[HookOwner] = []
    for directory in direct_children(skill_root):
        if directory.is_symlink():
            raise ValueError(f"repository skill owner must not be a symlink: {directory}")
        if not directory.is_dir():
            continue
        skill_file = directory / "SKILL.md"
        hook_file = directory / "hooks.json"
        for candidate in (skill_file, hook_file):
            if candidate.is_symlink():
                raise ValueError(f"repository skill file must not be a symlink: {candidate}")
        if hook_file.exists() and not skill_file.is_file():
            raise ValueError(f"{hook_file}: hooks require an adjacent SKILL.md")
        if skill_file.is_file() and hook_file.is_file():
            owners.append(HookOwner(hook_file, skill_root, True))
    return owners


def hook_manifests(root: Path) -> list[HookOwner]:
    agents_home = Path(os.environ.get("AGENTS_HOME", Path.home() / ".agents")).expanduser()
    manifests: list[HookOwner] = []
    seen: set[Path] = set()
    owners: dict[str, Path] = {}
    for discovered in (
        global_hook_owners(agents_home),
        repository_hook_owners(root),
    ):
        for owner in discovered:
            resolved = owner.manifest.resolve()
            if resolved not in seen:
                name = owner.manifest.parent.name
                if name in owners:
                    raise ValueError(
                        f"duplicate hook skill name {name!r}: {owners[name]} and {owner.manifest}"
                    )
                owners[name] = owner.manifest
                seen.add(resolved)
                manifests.append(owner)
    return manifests


def manifest_entries(
    manifest_path: Path, event: str, allowed_events: set[str], budgets: dict[str, int]
) -> list[dict]:
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    unknown_root = sorted(set(manifest) - {"version", "events"})
    if unknown_root:
        raise ValueError(f"unknown keys: {', '.join(unknown_root)}")
    if manifest.get("version") != 1:
        raise ValueError("version must be 1")
    events = manifest.get("events")
    if not isinstance(events, dict):
        raise ValueError("events must be an object")
    for name, entries in events.items():
        if name not in allowed_events:
            raise ValueError(f"unsupported hook event {name!r}")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{name} must contain at least one hook")
        total_timeout = 0
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"{name}[{index}] must be an object")
            unknown_entry = sorted(set(entry) - {"command", "timeoutSeconds"})
            if unknown_entry:
                raise ValueError(f"{name}[{index}] unknown keys: {', '.join(unknown_entry)}")
            command = entry.get("command")
            if not isinstance(command, list) or not command or not all(
                isinstance(item, str) and item for item in command
            ):
                raise ValueError(f"{name}[{index}] command must be a non-empty string list")
            timeout = entry.get("timeoutSeconds", 300)
            if (
                not isinstance(timeout, int)
                or isinstance(timeout, bool)
                or timeout <= 0
                or timeout > budgets[name]
            ):
                raise ValueError(
                    f"{name}[{index}] timeoutSeconds must be between 1 and {budgets[name]}"
                )
            total_timeout += timeout
        if total_timeout > budgets[name]:
            raise ValueError(
                f"{name} declares {total_timeout} seconds across hooks, exceeding "
                f"the {budgets[name]}-second event budget"
            )
    return events.get(event, [])


def require_time(deadline: float, phase: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"event-wide hook budget exhausted during {phase}")
    return remaining


def scheduled_hooks(
    root: Path,
    event: str,
    allowed_events: set[str],
    budgets: dict[str, int],
    deadline: float,
) -> list[tuple[HookOwner, dict]]:
    require_time(deadline, "skill discovery")
    owners = hook_manifests(root)
    require_time(deadline, "skill discovery")
    scheduled: list[tuple[HookOwner, dict]] = []
    for owner in owners:
        require_time(deadline, "manifest validation")
        entries = manifest_entries(owner.manifest, event, allowed_events, budgets)
        scheduled.extend((owner, entry) for entry in entries)
    require_time(deadline, "manifest validation")
    return scheduled


def process_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    group_id = process.pid
    try:
        os.killpg(group_id, signal.SIGTERM)
    except (PermissionError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=PROCESS_GROUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + PROCESS_GROUP_GRACE_SECONDS
    while process_group_exists(group_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    if process_group_exists(group_id):
        try:
            os.killpg(group_id, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=PROCESS_GROUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def run_hook_process(
    argv: list[str],
    cwd: Path,
    raw_input: str,
    timeout: float,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    payload = raw_input.encode("utf-8")
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        terminate_process_group(process)
        raise OSError("hook process pipes were not created")

    selector = selectors.DefaultSelector()
    try:
        streams = {
            process.stdout.fileno(): ("stdout", process.stdout),
            process.stderr.fileno(): ("stderr", process.stderr),
        }
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        output_open = set(streams)
        input_offset = 0
        for descriptor, (name, stream) in streams.items():
            os.set_blocking(descriptor, False)
            selector.register(stream, selectors.EVENT_READ, name)
        os.set_blocking(process.stdin.fileno(), False)
        if payload:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()

        deadline = time.monotonic() + timeout
        group_cleaned = False
        while process.poll() is None or output_open:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"hook exceeded its {timeout:.3f}-second runtime budget")
            if process.poll() is not None and not group_cleaned:
                terminate_process_group(process)
                group_cleaned = True
            if process.returncode is not None and not process.stdin.closed:
                try:
                    selector.unregister(process.stdin)
                except KeyError:
                    pass
                process.stdin.close()
            if not selector.get_map():
                time.sleep(min(0.01, remaining))
                continue
            for key, _ in selector.select(min(0.1, remaining)):
                if key.data == "stdin":
                    try:
                        written = os.write(
                            process.stdin.fileno(),
                            payload[input_offset : input_offset + 64 * 1024],
                        )
                    except (BrokenPipeError, OSError):
                        written = 0
                        input_offset = len(payload)
                    else:
                        input_offset += written
                    if input_offset >= len(payload):
                        try:
                            selector.unregister(process.stdin)
                        except KeyError:
                            pass
                        process.stdin.close()
                    continue

                descriptor = key.fileobj.fileno()
                try:
                    chunk = os.read(descriptor, 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except KeyError:
                        pass
                    key.fileobj.close()
                    output_open.discard(descriptor)
                    continue
                total = len(buffers["stdout"]) + len(buffers["stderr"]) + len(chunk)
                if total > MAX_HOOK_OUTPUT_BYTES:
                    raise HookOutputLimitError(
                        f"hook output exceeds {MAX_HOOK_OUTPUT_BYTES} bytes"
                    )
                buffers[key.data].extend(chunk)

        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            buffers["stdout"].decode("utf-8", errors="replace"),
            buffers["stderr"].decode("utf-8", errors="replace"),
        )
    finally:
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()
        terminate_process_group(process)


def main() -> int:
    started = time.monotonic()
    args = parse_args()
    event = canonical_event(args.event)
    raw = sys.stdin.read()
    payload = hook_input(raw)
    try:
        allowed_events, budgets = system_hook_contract()
        if event not in allowed_events:
            raise ValueError(f"unsupported hook event {event!r}")
        deadline = started + budgets[event]
        remaining = require_time(deadline, "project discovery")
        root = project_root(payload, remaining)
        require_time(deadline, "project discovery")
        scheduled = scheduled_hooks(root, event, allowed_events, budgets, deadline)
    except (TimeoutError, ValueError) as exc:
        return emit(args.host, event, f"Invalid skill hook configuration: {exc}")

    declared_total = sum(entry.get("timeoutSeconds", 300) for _, entry in scheduled)
    if declared_total > budgets[event]:
        return emit(
            args.host,
            event,
            f"Invalid skill hook configuration: {event} declares {declared_total} seconds "
            f"across active skills, exceeding the {budgets[event]}-second event budget",
        )

    for owner, entry in scheduled:
        manifest_path = owner.manifest
        command = entry.get("command") if isinstance(entry, dict) else None
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            return emit(args.host, event, f"Invalid {event} command in {manifest_path}")

        skill_dir = manifest_path.parent
        try:
            argv = safe_command(owner, command)
            remaining = require_time(deadline, "hook execution")
            timeout = min(entry.get("timeoutSeconds", 300), remaining)
            env = os.environ.copy()
            env.update({
                "AGENT_HOOK_EVENT": event,
                "AGENT_HOOK_HOST": args.host,
                "AGENT_PROJECT_DIR": str(root),
                "AGENT_SKILL_DIR": str(skill_dir),
            })
            result = run_hook_process(
                argv,
                root,
                raw,
                timeout,
                env,
            )
        except (OSError, TimeoutError, ValueError) as exc:
            return emit(args.host, event, f"Skill hook failed: {skill_dir.name}/{event}: {exc}")

        output = result.stdout.strip()
        message = None
        if output:
            try:
                message = json.loads(output.splitlines()[-1])
            except json.JSONDecodeError:
                pass
        if isinstance(message, dict) and message.get("decision") == "block":
            return emit(args.host, event, str(message.get("reason") or "Skill hook blocked the action"))
        if result.returncode != 0:
            reason = result.stderr.strip() or output or f"exit {result.returncode}"
            return emit(args.host, event, f"Skill hook failed: {skill_dir.name}/{event}: {reason}")

    return emit(args.host, event)


if __name__ == "__main__":
    raise SystemExit(main())
