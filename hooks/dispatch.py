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
    if not executable.is_absolute():
        executable = (skill_dir / executable).resolve()
        if skill_dir.resolve() not in executable.parents:
            raise ValueError("relative hook executable escapes its skill directory")
    return [str(executable), *command[1:]]


def hook_manifests(root: Path) -> list[Path]:
    agents_home = Path(os.environ.get("AGENTS_HOME", Path.home() / ".agents")).expanduser()
    skill_roots = (agents_home / "skills", root / ".agents" / "skills")
    manifests: list[Path] = []
    seen: set[Path] = set()
    for skill_root in skill_roots:
        if not skill_root.is_dir():
            continue
        for manifest in sorted(skill_root.glob("*/hooks.json")):
            resolved = manifest.resolve()
            if resolved not in seen:
                seen.add(resolved)
                manifests.append(manifest)
    return manifests


def main() -> int:
    args = parse_args()
    event = canonical_event(args.event)
    raw = sys.stdin.read()
    payload = hook_input(raw)
    root = project_root(payload)

    for manifest_path in hook_manifests(root):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = manifest.get("events", {}).get(event, [])
        except (OSError, json.JSONDecodeError) as exc:
            return emit(args.host, event, f"Invalid skill hook manifest {manifest_path}: {exc}")

        for entry in entries:
            command = entry.get("command") if isinstance(entry, dict) else None
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                return emit(args.host, event, f"Invalid {event} command in {manifest_path}")

            skill_dir = manifest_path.parent
            try:
                argv = safe_command(skill_dir, command)
                timeout = int(entry.get("timeoutSeconds", 300))
                if timeout <= 0:
                    raise ValueError("timeoutSeconds must be positive")
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
