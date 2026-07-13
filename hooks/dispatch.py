#!/usr/bin/env python3
"""Dispatch host hook events to manifests owned by global and repository skills."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


EVENT_ALIASES = {
    "stop": "Stop",
    "pretooluse": "PreToolUse",
    "pre_tool_use": "PreToolUse",
}
MAX_HOOK_TIMEOUT_SECONDS = 600


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


def project_root(payload: dict) -> Path:
    start = payload_cwd(payload).resolve()
    try:
        output = subprocess.check_output(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return Path(output.strip())
    except (OSError, subprocess.CalledProcessError):
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


def safe_command(skill_dir: Path, command: list[str]) -> list[str]:
    executable = Path(command[0])
    if executable.is_absolute():
        raise ValueError("hook executable must be skill-relative")
    executable = (skill_dir / executable).resolve()
    if skill_dir.resolve() not in executable.parents:
        raise ValueError("relative hook executable escapes its skill directory")
    return [str(executable), *command[1:]]


def supported_events() -> set[str]:
    system_root = Path(__file__).resolve().parent.parent
    try:
        catalog = json.loads((system_root / "system.json").read_text(encoding="utf-8"))
        events = catalog["hookEvents"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid system hook catalog: {exc}") from exc
    if not isinstance(events, list) or not events or not all(isinstance(event, str) for event in events):
        raise ValueError("system hook catalog must contain hookEvents")
    return set(events)


def hook_manifests(root: Path) -> list[Path]:
    agents_home = Path(os.environ.get("AGENTS_HOME", Path.home() / ".agents")).expanduser()
    skill_roots = (agents_home / "skills", root / ".agents" / "skills")
    manifests: list[Path] = []
    seen: set[Path] = set()
    owners: dict[str, Path] = {}
    for skill_root in skill_roots:
        if not skill_root.is_dir():
            continue
        for manifest in sorted(skill_root.glob("*/hooks.json")):
            resolved = manifest.resolve()
            if resolved not in seen:
                owner = manifest.parent.name
                if owner in owners:
                    raise ValueError(
                        f"duplicate hook skill name {owner!r}: {owners[owner]} and {manifest}"
                    )
                owners[owner] = manifest
                seen.add(resolved)
                manifests.append(manifest)
    return manifests


def manifest_entries(manifest_path: Path, event: str, allowed_events: set[str]) -> list[dict]:
    try:
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
                or timeout > MAX_HOOK_TIMEOUT_SECONDS
            ):
                raise ValueError(
                    f"{name}[{index}] timeoutSeconds must be between 1 and "
                    f"{MAX_HOOK_TIMEOUT_SECONDS}"
                )
    return events.get(event, [])


def main() -> int:
    args = parse_args()
    event = canonical_event(args.event)
    raw = sys.stdin.read()
    payload = hook_input(raw)
    root = project_root(payload)
    try:
        allowed_events = supported_events()
        if event not in allowed_events:
            raise ValueError(f"unsupported hook event {event!r}")
        manifests = hook_manifests(root)
    except ValueError as exc:
        return emit(args.host, event, f"Invalid skill hook configuration: {exc}")

    for manifest_path in manifests:
        try:
            entries = manifest_entries(manifest_path, event, allowed_events)
        except ValueError as exc:
            return emit(args.host, event, f"Invalid skill hook manifest {manifest_path}: {exc}")

        for entry in entries:
            command = entry.get("command") if isinstance(entry, dict) else None
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                return emit(args.host, event, f"Invalid {event} command in {manifest_path}")

            skill_dir = manifest_path.parent
            try:
                argv = safe_command(skill_dir, command)
                timeout = entry.get("timeoutSeconds", 300)
                env = os.environ.copy()
                env.update({
                    "AGENT_HOOK_EVENT": event,
                    "AGENT_HOOK_HOST": args.host,
                    "AGENT_PROJECT_DIR": str(root),
                    "AGENT_SKILL_DIR": str(skill_dir),
                })
                result = subprocess.run(
                    argv,
                    cwd=root,
                    input=raw,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
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
