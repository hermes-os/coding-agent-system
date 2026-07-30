#!/usr/bin/env python3
"""Block Kimi turns whose persisted system prompt predates managed policy."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from lib.host_contract import kimi_policy_marker


MAX_CONTEXT_RECORD_BYTES = 2 * 1024 * 1024


def share_dir() -> Path:
    configured = os.environ.get("KIMI_SHARE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".kimi"


def session_context(
    root: Path,
    session_id: str,
    *,
    allow_missing: bool = False,
) -> Path | None:
    sessions_root = (root / "sessions").resolve()
    try:
        if allow_missing and not sessions_root.exists():
            return None
        candidates = []
        for work_dir in sessions_root.iterdir():
            if not work_dir.is_dir():
                continue
            current = work_dir / session_id / "context.jsonl"
            legacy = work_dir / f"{session_id}.jsonl"
            candidates.extend(
                path for path in (current, legacy) if path.is_file()
            )
    except OSError as exc:
        raise ValueError(f"cannot inspect Kimi session store: {exc}") from exc
    if allow_missing and not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError(
            f"Kimi session store has {len(candidates)} contexts for {session_id}"
        )
    context = candidates[0]
    resolved_context = context.resolve()
    if sessions_root not in resolved_context.parents or context.is_symlink():
        raise ValueError("Kimi session context escapes the session store")
    return resolved_context


def persisted_system_prompt(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_CONTEXT_RECORD_BYTES:
                    raise ValueError("Kimi system-prompt record exceeds the size limit")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid Kimi context record: {exc}") from exc
                if not isinstance(record, dict):
                    raise ValueError("Kimi context record is not an object")
                if record.get("role") != "_system_prompt":
                    raise ValueError("Kimi context does not begin with a system prompt")
                content = record.get("content")
                if not isinstance(content, str):
                    raise ValueError("Kimi persisted system prompt is not text")
                return content
    except OSError as exc:
        raise ValueError(f"cannot read Kimi session context: {exc}") from exc
    raise ValueError("Kimi session context is empty")


def validate_session_id(value: object) -> str:
    session_id = value
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Kimi session ID is missing")
    if (
        "/" in session_id
        or "\\" in session_id
        or session_id in {".", ".."}
    ):
        raise ValueError("Kimi session ID is unsafe")
    return session_id


def current_policy_marker() -> str:
    policy_path = Path.home() / ".agents" / "AGENTS.md"
    try:
        return kimi_policy_marker(policy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read canonical agent policy: {exc}") from exc


def validate_context(context: Path) -> None:
    if current_policy_marker() not in persisted_system_prompt(context):
        raise ValueError(
            "this Kimi session predates the current managed policy; start a fresh session"
        )


def validate_hook(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Kimi hook payload is not an object")
    session_id = validate_session_id(payload.get("session_id"))
    context = session_context(share_dir(), session_id)
    assert context is not None
    validate_context(context)


def preflight_argv(argv: list[str]) -> None:
    print_mode = False
    session_id: str | None = None
    value_options = {
        "--work-dir",
        "-w",
        "--add-dir",
        "--model",
        "-m",
        "--prompt",
        "--command",
        "-p",
        "-c",
        "--input-format",
        "--output-format",
        "--mcp-config-file",
        "--mcp-config",
        "--max-steps-per-turn",
        "--max-retries-per-step",
        "--max-ralph-iterations",
    }
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in {"--print", "--quiet"}:
            print_mode = True
            index += 1
            continue
        if argument in {"--wire", "--acp"}:
            raise ValueError(
                f"{argument} can load sessions outside the managed preflight"
            )
        if argument in {"--continue", "-C"}:
            raise ValueError(f"{argument} cannot identify a session before launch")
        if argument in {"--session", "--resume", "-S", "-r"}:
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                raise ValueError(f"{argument} picker mode is not managed")
            session_id = validate_session_id(argv[index + 1])
            index += 2
            continue
        if argument.startswith("--session=") or argument.startswith("--resume="):
            session_id = validate_session_id(argument.split("=", 1)[1])
            index += 1
            continue
        if (
            argument.startswith("-")
            and not argument.startswith("--")
            and len(argument) > 2
        ):
            cluster = argument[1:]
            offset = 0
            while offset < len(cluster):
                option = cluster[offset]
                if option in {"y", "V", "h"}:
                    offset += 1
                    continue
                if option == "C":
                    raise ValueError(
                        "-C cannot identify a session before launch"
                    )
                if option in {"S", "r"}:
                    attached = cluster[offset + 1 :]
                    if attached:
                        session_id = validate_session_id(attached)
                    else:
                        if (
                            index + 1 >= len(argv)
                            or argv[index + 1].startswith("-")
                        ):
                            raise ValueError(f"-{option} picker mode is not managed")
                        session_id = validate_session_id(argv[index + 1])
                        index += 1
                    break
                if option in {"w", "m", "p", "c"}:
                    if offset + 1 == len(cluster):
                        index += 1
                    break
                raise ValueError(
                    f"unsupported short option in cluster: -{option}"
                )
            index += 1
            continue
        if argument in value_options:
            index += 2
            continue
        index += 1

    if not print_mode:
        raise ValueError("managed Kimi agent work requires --print or --quiet")
    if session_id is not None:
        context = session_context(share_dir(), session_id, allow_missing=True)
        if context is not None:
            validate_context(context)


def main() -> int:
    if sys.argv[1:] == ["--hook"]:
        mode = "hook"
    elif len(sys.argv) >= 3 and sys.argv[1:3] == ["--preflight", "--"]:
        mode = "preflight"
    else:
        print("usage: kimi_session_guard.py --hook", file=sys.stderr)
        return 2
    try:
        if mode == "hook":
            validate_hook(json.load(sys.stdin))
        else:
            preflight_argv(sys.argv[3:])
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Kimi policy guard blocked the turn: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
