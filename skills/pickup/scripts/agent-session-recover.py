#!/usr/bin/env python3
"""Find and sanitize local Codex or Claude sessions for crash recovery."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time


TAG_NAMES = (
    "environment_context",
    "skills_instructions",
    "apps_instructions",
    "plugins_instructions",
    "app-context",
    "hook_prompt",
    "system-reminder",
    "INSTRUCTIONS",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [^-]*(?:PRIVATE KEY|CERTIFICATE)-----.*?-----END [^-]+-----", re.DOTALL),
    re.compile(r"\b(?:github_pat_|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
)
ASSIGNMENT_RE = re.compile(
    r"\b(?P<name>[A-Z0-9_-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|(?:API|PRIVATE|ACCESS|CLIENT)[_-]?KEY)[A-Z0-9_-]*)"
    r"[\"']?\s*[:=]\s*(?:(?P<quote>[\"'])(?P<quoted>[^\"'\r\n]+)(?P=quote)|"
    r"(?P<bare>[^\s\"',;}\]]+))",
    re.IGNORECASE | re.MULTILINE,
)
AUTH_QUERY_RE = re.compile(r"(?i)([?&](?:token|code|secret|key|password)=)[^&#\s]+")
AUTHORIZATION_RE = re.compile(
    r"(\bauthorization[\"']?\s*:\s*[\"']?\s*(?:bearer|basic)\s+)[A-Za-z0-9+/_.~=-]{8,}",
    re.IGNORECASE,
)
COOKIE_RE = re.compile(r"(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]+", re.IGNORECASE)
URI_CREDENTIAL_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s/]+(@)")


@dataclass
class Turn:
    role: str
    text: str


@dataclass
class Session:
    host: str
    path: Path
    mtime: float
    cwd: str | None
    turns: list[Turn]
    redactions: int = 0


def roots() -> list[tuple[str, Path]]:
    values: list[tuple[str, Path]] = []
    codex = os.environ.get("AGENT_CODEX_SESSIONS")
    claude = os.environ.get("AGENT_CLAUDE_PROJECTS")
    for raw in (codex.split(os.pathsep) if codex else [str(Path.home() / ".codex" / "sessions"), str(Path.home() / ".codex" / "archived_sessions")]):
        values.append(("codex", Path(raw).expanduser()))
    for raw in (claude.split(os.pathsep) if claude else [str(Path.home() / ".claude" / "projects")]):
        values.append(("claude", Path(raw).expanduser()))
    return values


def known_session(path: Path) -> tuple[str, Path]:
    resolved = path.expanduser().resolve()
    for host, root in roots():
        try:
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        return host, resolved
    raise ValueError("session is outside configured local transcript roots")


def strip_host_context(text: str) -> str:
    for tag in TAG_NAMES:
        text = re.sub(
            rf"<{re.escape(tag)}\b[^>]*>.*?</{re.escape(tag)}>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    text = re.sub(r"(?ms)^# AGENTS\.md instructions.*?(?=^\S|\Z)", "", text)
    return text


def redact(text: str) -> tuple[str, int]:
    text = strip_host_context(text)
    count = 0
    for pattern in SECRET_PATTERNS:
        text, replaced = pattern.subn("[REDACTED]", text)
        count += replaced

    def assignment(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group('name')}=[REDACTED]"

    text = ASSIGNMENT_RE.sub(assignment, text)
    text, replaced = AUTH_QUERY_RE.subn(r"\1[REDACTED]", text)
    count += replaced
    text, replaced = AUTHORIZATION_RE.subn(r"\1[REDACTED]", text)
    count += replaced
    text, replaced = COOKIE_RE.subn(r"\1[REDACTED]", text)
    count += replaced
    text, replaced = URI_CREDENTIAL_RE.subn(r"\1[REDACTED]\2", text)
    count += replaced
    home = str(Path.home())
    if home and home in text:
        text = text.replace(home, "~")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, count


def content_text(message: object) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"):
            value = block.get("text")
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def parse_records(host: str, lines, keep: int = 120) -> tuple[str | None, list[Turn], int]:
    cwd: str | None = None
    turns: deque[Turn] = deque(maxlen=keep)
    redactions = 0
    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(value, dict):
            continue
        if host == "codex":
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
            if value.get("type") == "session_meta" and isinstance(payload.get("cwd"), str):
                cwd = payload["cwd"]
            if value.get("type") != "event_msg" or payload.get("type") not in ("user_message", "agent_message"):
                continue
            role = "user" if payload.get("type") == "user_message" else "assistant"
            raw = payload.get("message")
        else:
            if isinstance(value.get("cwd"), str):
                cwd = value["cwd"]
            if value.get("type") not in ("user", "assistant") or value.get("isMeta") is True:
                continue
            role = str(value["type"])
            raw = content_text(value.get("message"))
        if not isinstance(raw, str):
            continue
        clean, replaced = redact(raw)
        redactions += replaced
        if clean:
            turns.append(Turn(role, clean))
    return cwd, list(turns), redactions


def sampled_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        first = handle.read(128 * 1024)
        tail = b""
        if size > len(first):
            handle.seek(max(len(first), size - 2 * 1024 * 1024))
            tail = handle.read()
    chunks = [first]
    if tail:
        newline = tail.find(b"\n")
        chunks.append(tail[newline + 1 :] if newline >= 0 else b"")
    return b"\n".join(chunks).decode("utf-8", errors="replace").splitlines()


def query_terms(query: str) -> list[str]:
    return sorted({term for term in re.findall(r"[a-z0-9_-]+", query.lower()) if len(term) >= 3})


def normalized_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))


def score_session(session: Session, requested_cwd: Path, terms: list[str], query: str) -> int:
    score = 0
    if session.cwd:
        actual = normalized_path(session.cwd)
        requested = normalized_path(requested_cwd)
        if actual == requested:
            score += 80
        elif actual.startswith(requested + os.sep) or requested.startswith(actual + os.sep):
            score += 30
    user_text = "\n".join(turn.text.lower() for turn in session.turns if turn.role == "user")
    score += min(40, sum(5 for term in terms if term in user_text))
    if query.strip() and query.lower().strip() in user_text:
        score += 15
    age_days = max(0.0, (time.time() - session.mtime) / 86400)
    score += max(0, 20 - int(age_days))
    if "subagents" in session.path.parts:
        score -= 10
    return score


def find_sessions(args: argparse.Namespace) -> int:
    cutoff = time.time() - args.since_days * 86400
    candidates: list[tuple[str, Path, float]] = []
    for host, root in roots():
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                candidates.append((host, path, mtime))
    candidates.sort(key=lambda item: item[2], reverse=True)
    terms = query_terms(args.query)
    ranked: list[tuple[int, Session]] = []
    for host, path, mtime in candidates[: args.max_files]:
        try:
            cwd, turns, redactions = parse_records(host, sampled_lines(path), keep=30)
        except OSError:
            continue
        session = Session(host, path, mtime, cwd, turns, redactions)
        ranked.append((score_session(session, args.cwd, terms, args.query), session))
    ranked.sort(key=lambda item: (item[0], item[1].mtime), reverse=True)

    rows = []
    for score, session in ranked[: args.limit]:
        last_user = next((turn.text for turn in reversed(session.turns) if turn.role == "user"), "")
        rows.append(
            {
                "score": score,
                "host": session.host,
                "updated": datetime.fromtimestamp(session.mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                "cwd": session.cwd.replace(str(Path.home()), "~") if session.cwd else None,
                "session": str(session.path).replace(str(Path.home()), "~"),
                "last_user": re.sub(r"\s+", " ", last_user)[:160],
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['score']:>3}  {row['host']:<7} {row['updated']}  {row['session']}")
            if row["cwd"]:
                print(f"     cwd: {row['cwd']}")
            if row["last_user"]:
                print(f"     last: {row['last_user']}")
    return 0 if rows else 1


def selected_turns(turns: list[Turn], query: str, maximum: int) -> list[Turn]:
    if not turns:
        return []
    terms = query_terms(query)
    user_matches = [
        index
        for index, turn in enumerate(turns)
        if turn.role == "user" and terms and any(term in turn.text.lower() for term in terms)
    ]
    user_indexes = [index for index, turn in enumerate(turns) if turn.role == "user"]
    anchor = user_matches[-1] if user_matches else (user_indexes[-1] if user_indexes else None)
    if anchor is None or anchor >= len(turns) - maximum:
        return turns[-maximum:]
    anchor_indexes = list(range(anchor, min(len(turns), anchor + min(2, maximum))))
    remaining = maximum - len(anchor_indexes)
    tail_indexes = list(range(max(anchor_indexes[-1] + 1, len(turns) - remaining), len(turns))) if remaining else []
    return [turns[index] for index in [*anchor_indexes, *tail_indexes]]


def render_session(args: argparse.Namespace) -> int:
    host, path = known_session(args.session)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        cwd, turns, redactions = parse_records(host, handle, keep=max(200, args.max_messages * 4))
    chosen = selected_turns(turns, args.query, args.max_messages)
    if not chosen:
        print("agent-session-recover: no visible turns found", file=sys.stderr)
        return 1

    header = [
        "# Session Recovery Extract",
        "",
        f"- Host: {host}",
        f"- Session: {str(path).replace(str(Path.home()), '~')}",
        f"- Working directory: {(cwd or 'unknown').replace(str(Path.home()), '~')}",
        f"- Redactions: {redactions}",
        "",
        "## Recent Relevant Turns",
        "",
    ]
    blocks: list[str] = []
    remaining = args.max_chars
    for index, turn in enumerate(chosen):
        turns_left = len(chosen) - index
        allowance = remaining // turns_left
        prefix = f"**{turn.role.title()}**\n\n"
        text = turn.text[: min(2400, max(0, allowance - len(prefix) - 1))]
        if not text:
            continue
        block = f"{prefix}{text}\n"
        blocks.append(block)
        remaining -= len(block)
    output = "\n".join([*header, *blocks]).rstrip() + "\n"

    if args.out:
        destination = Path(args.out).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_temp = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        temp = Path(raw_temp)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(output)
            temp.chmod(0o600)
            temp.replace(destination)
        finally:
            if temp.exists():
                temp.unlink()
        print(destination)
    else:
        print(output, end="")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    find_parser = commands.add_parser("find")
    find_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    find_parser.add_argument("--query", default="")
    find_parser.add_argument("--since-days", type=int, default=14)
    find_parser.add_argument("--max-files", type=int, default=400)
    find_parser.add_argument("--limit", type=int, default=5)
    find_parser.add_argument("--json", action="store_true")
    find_parser.set_defaults(handler=find_sessions)

    render_parser = commands.add_parser("render")
    render_parser.add_argument("session", type=Path)
    render_parser.add_argument("--query", default="")
    render_parser.add_argument("--max-messages", type=int, default=18)
    render_parser.add_argument("--max-chars", type=int, default=12_000)
    render_parser.add_argument("--out")
    render_parser.set_defaults(handler=render_session)
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "since_days", 1) < 0 or getattr(args, "limit", 1) < 1 or getattr(args, "max_files", 1) < 1:
        raise ValueError("search limits must be positive")
    if hasattr(args, "max_messages") and (args.max_messages < 1 or args.max_chars < 1000):
        raise ValueError("render limits are too small")
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"agent-session-recover: {exc}", file=sys.stderr)
        raise SystemExit(1)
