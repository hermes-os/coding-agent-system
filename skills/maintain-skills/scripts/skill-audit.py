#!/usr/bin/env python3
"""Audit skill structure, duplicates, hook manifests, and metadata budget."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MODEL_PATTERNS = {
    "--model": re.compile(r"(?<![\w-])--model(?:\s|=)"),
    "anthropic_model": re.compile(r"\banthropic_model\b"),
    "claude-haiku": re.compile(r"\bclaude-haiku\b"),
    "claude-opus": re.compile(r"\bclaude-opus\b"),
    "claude-sonnet": re.compile(r"\bclaude-sonnet\b"),
    "gpt-": re.compile(r"\bgpt-[a-z0-9]"),
}


@dataclass(frozen=True)
class Skill:
    source: Path
    real: Path
    name: str
    description: str
    text: str
    body: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--live", action="store_true", help="scan standard active host roots")
    parser.add_argument(
        "--all-caches",
        action="store_true",
        help="also scan plugin caches for storage and duplicate forensics",
    )
    parser.add_argument(
        "--codex-visible",
        action="store_true",
        help="measure the exact skill list rendered by `codex debug prompt-input`",
    )
    parser.add_argument("--check", action="store_true", help="fail on validation errors")
    parser.add_argument("--strict", action="store_true", help="also fail on warnings")
    parser.add_argument(
        "--model-neutral",
        action="store_true",
        help="warn on execution-model pins in the scanned catalog",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", dest="list_skills")
    parser.add_argument("--context-window", type=int, default=272000)
    parser.add_argument("--budget-percent", type=float, default=2.0)
    return parser.parse_args()


def live_roots(home: Path, cwd: Path) -> list[Path]:
    return [
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
        cwd / ".agents" / "skills",
    ]


def cache_roots(home: Path) -> list[Path]:
    return [
        home / ".codex" / "plugins" / "cache",
        home / ".claude" / "plugins" / "cache",
    ]


def discover(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    stack = [root]
    visited: set[Path] = set()
    while stack:
        directory = stack.pop()
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in visited:
            continue
        visited.add(resolved)
        skill_file = directory / "SKILL.md"
        if skill_file.is_file():
            found.append(skill_file)
            continue
        try:
            children = sorted(
                (child for child in directory.iterdir() if child.is_dir()),
                key=lambda child: child.name,
                reverse=True,
            )
        except OSError:
            continue
        stack.extend(children)
    return found


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def frontmatter(path: Path, text: str) -> tuple[dict[str, str], str, list[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, [f"{path}: frontmatter must start on line 1"]
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}, text, [f"{path}: frontmatter is unterminated"]

    values: dict[str, str] = {}
    frontmatter_lines = lines[1:end]
    index = 0
    while index < len(frontmatter_lines):
        line = frontmatter_lines[index]
        if not line or line[0].isspace() or ":" not in line:
            index += 1
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value in {"|", "|-", ">", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(frontmatter_lines):
                candidate = frontmatter_lines[index]
                if candidate and not candidate[0].isspace():
                    break
                if candidate.strip():
                    block.append(candidate.strip())
                index += 1
            values[key.strip()] = " ".join(block)
            continue
        values[key.strip()] = unquote(value)
        index += 1
    return values, "\n".join(lines[end + 1 :]).strip(), errors


def load_skill(path: Path) -> tuple[Skill | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        real = path.resolve()
    except (OSError, UnicodeError) as exc:
        return None, [f"{path}: cannot read: {exc}"], []

    values, body, parse_errors = frontmatter(path, text)
    errors.extend(parse_errors)
    name = values.get("name", "").strip()
    description = values.get("description", "").strip()
    if not name:
        errors.append(f"{path}: missing name")
    elif not NAME_RE.fullmatch(name):
        errors.append(f"{path}: invalid name {name!r}")
    if not description:
        errors.append(f"{path}: missing description")
    if description.startswith("[TODO") or any(line.strip().startswith("[TODO") for line in text.splitlines()):
        errors.append(f"{path}: unresolved TODO placeholder")
    if name and name != real.parent.name:
        warnings.append(f"{path}: name {name!r} differs from canonical folder {real.parent.name!r}")
    if len(description) > 240:
        warnings.append(f"{path}: description is {len(description)} characters; target <= 240")
    if len(text.splitlines()) > 500:
        warnings.append(f"{path}: SKILL.md is over 500 lines; move conditional detail to references")

    skill = Skill(path, real, name, description, text, body)
    hook_errors = validate_hooks(skill)
    errors.extend(hook_errors)
    return skill, errors, warnings


def validate_hooks(skill: Skill) -> list[str]:
    manifest_path = skill.real.parent / "hooks.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: invalid JSON: {exc}"]
    events = manifest.get("events") if isinstance(manifest, dict) else None
    if not isinstance(events, dict):
        return [f"{manifest_path}: events must be an object"]

    errors: list[str] = []
    skill_dir = skill.real.parent.resolve()
    for event, entries in events.items():
        if not isinstance(event, str) or not isinstance(entries, list):
            errors.append(f"{manifest_path}: each event must map to a list")
            continue
        for index, entry in enumerate(entries):
            command = entry.get("command") if isinstance(entry, dict) else None
            if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
                errors.append(f"{manifest_path}: {event}[{index}] command must be a non-empty string list")
                continue
            executable = Path(command[0])
            if executable.is_absolute():
                errors.append(f"{manifest_path}: {event}[{index}] executable must be skill-relative")
                continue
            resolved = (skill_dir / executable).resolve()
            if resolved != skill_dir and skill_dir not in resolved.parents:
                errors.append(f"{manifest_path}: {event}[{index}] executable escapes the skill")
            elif not resolved.is_file():
                errors.append(f"{manifest_path}: {event}[{index}] executable is missing: {executable}")
            elif not os.access(resolved, os.X_OK):
                errors.append(f"{manifest_path}: {event}[{index}] executable is not executable: {executable}")
            timeout = entry.get("timeoutSeconds", 300) if isinstance(entry, dict) else 300
            if not isinstance(timeout, int) or timeout <= 0:
                errors.append(f"{manifest_path}: {event}[{index}] timeoutSeconds must be positive")
    return errors


def normalized(value: str) -> str:
    return " ".join(value.lower().split())


def duplicate_warnings(skills: list[Skill]) -> list[str]:
    warnings: list[str] = []
    by_name: dict[str, list[Skill]] = defaultdict(list)
    by_description: dict[str, list[Skill]] = defaultdict(list)
    by_body: dict[str, list[Skill]] = defaultdict(list)
    for skill in skills:
        by_name[skill.name].append(skill)
        by_description[normalized(skill.description)].append(skill)
        digest = hashlib.sha256(normalized(skill.body).encode()).hexdigest()
        by_body[digest].append(skill)

    for label, groups in (("name", by_name), ("description", by_description), ("body", by_body)):
        for value, matches in groups.items():
            if value and len(matches) > 1:
                paths = ", ".join(str(skill.source) for skill in matches)
                warnings.append(f"duplicate skill {label}: {paths}")

    near_limit = 20
    for index, left in enumerate(skills):
        if len(warnings) >= near_limit:
            break
        for right in skills[index + 1 :]:
            left_desc = normalized(left.description)
            right_desc = normalized(right.description)
            if left_desc == right_desc or min(len(left_desc), len(right_desc)) < 40:
                continue
            if SequenceMatcher(None, left_desc, right_desc).ratio() >= 0.92:
                warnings.append(f"near-duplicate descriptions: {left.source}, {right.source}")
                if len(warnings) >= near_limit:
                    break
    return warnings


def codex_visible_skills() -> tuple[list[dict[str, str]], str | None]:
    executable = shutil.which("codex")
    if not executable:
        return [], "codex is not available on PATH"
    try:
        result = subprocess.run(
            [executable, "debug", "prompt-input"],
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if result.returncode:
        return [], result.stderr.strip() or f"codex exited {result.returncode}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return [], f"codex returned invalid JSON: {exc}"

    texts: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for block in item.get("content", []):
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    text = block["text"]
                    if "<skills_instructions>" in text:
                        texts.append(text)

    entries: list[dict[str, str]] = []
    for text in texts:
        in_skills = False
        for line in text.splitlines():
            if line.strip() == "### Available skills":
                in_skills = True
                continue
            if not in_skills:
                continue
            if line.startswith("</skills_instructions>") or (line.startswith("### ") and entries):
                break
            if not line.startswith("- ") or " (file: " not in line or not line.endswith(")"):
                continue
            rendered, path = line[2:].rsplit(" (file: ", 1)
            if ": " not in rendered:
                continue
            name, description = rendered.split(": ", 1)
            entries.append(
                {
                    "name": name,
                    "description": description,
                    "path": path[:-1],
                    "rendered": line,
                }
            )
    if not entries:
        return [], "no model-visible skill entries found"
    return entries, None


def main() -> int:
    args = parse_args()
    script_skill_root = Path(__file__).resolve().parents[2]
    roots = list(args.root)
    if args.live:
        roots.extend(live_roots(Path.home(), Path.cwd()))
    if args.all_caches:
        roots.extend(cache_roots(Path.home()))
    if not roots:
        roots = [script_skill_root]

    discovered: list[Path] = []
    for root in roots:
        discovered.extend(discover(root.expanduser().resolve()))

    aliases = 0
    seen: set[Path] = set()
    skills: list[Skill] = []
    errors: list[str] = []
    warnings: list[str] = []
    for path in sorted(discovered, key=str):
        try:
            real = path.resolve()
        except OSError:
            real = path
        if real in seen:
            aliases += 1
            continue
        seen.add(real)
        skill, skill_errors, skill_warnings = load_skill(path)
        errors.extend(skill_errors)
        warnings.extend(skill_warnings)
        if skill:
            skills.append(skill)

    skills.sort(key=lambda item: (item.name, str(item.source)))
    if args.model_neutral:
        for skill in skills:
            lowered = skill.text.lower()
            for marker, pattern in MODEL_PATTERNS.items():
                if pattern.search(lowered):
                    warnings.append(f"{skill.source}: possible model pin marker {marker!r}")
    warnings.extend(duplicate_warnings(skills))

    metadata_bytes = sum(
        len(f"- {skill.name}: {skill.description} (file: {skill.source})\n".encode("utf-8"))
        for skill in skills
    )
    metadata_tokens = (metadata_bytes + 3) // 4
    budget_tokens = int(args.context_window * args.budget_percent / 100)
    if metadata_tokens > budget_tokens:
        warnings.append(
            f"metadata estimate {metadata_tokens} tokens exceeds {budget_tokens}-token "
            f"budget ({args.budget_percent:g}% of {args.context_window})"
        )

    visible_skills: list[dict[str, str]] = []
    visible_error: str | None = None
    visible_tokens: int | None = None
    if args.codex_visible:
        visible_skills, visible_error = codex_visible_skills()
        if visible_skills:
            visible_bytes = sum(len((skill["rendered"] + "\n").encode("utf-8")) for skill in visible_skills)
            visible_tokens = (visible_bytes + 3) // 4
            if visible_tokens > budget_tokens:
                warnings.append(
                    f"Codex-visible metadata estimate {visible_tokens} tokens exceeds "
                    f"{budget_tokens}-token budget"
                )

    report = {
        "roots": [str(root.expanduser().resolve()) for root in roots],
        "skills": [
            {"name": skill.name, "description": skill.description, "path": str(skill.source)}
            for skill in skills
        ],
        "uniqueSkillCount": len(skills),
        "aliasCount": aliases,
        "metadataTokensEstimate": metadata_tokens,
        "metadataBudgetTokens": budget_tokens,
        "codexVisibleSkills": visible_skills,
        "codexVisibleSkillCount": len(visible_skills),
        "codexVisibleMetadataTokensEstimate": visible_tokens,
        "codexVisibleError": visible_error,
        "errors": errors,
        "warnings": warnings,
    }
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Skills: {len(skills)} unique ({aliases} alias paths ignored)")
        print(f"Metadata estimate: {metadata_tokens}/{budget_tokens} tokens")
        if args.codex_visible:
            if visible_error:
                print(f"Codex-visible probe: unavailable ({visible_error})")
            else:
                print(
                    f"Codex-visible skills: {len(visible_skills)} "
                    f"({visible_tokens}/{budget_tokens} metadata tokens)"
                )
        if args.list_skills:
            for skill in skills:
                print(f"- {skill.name}: {skill.description}")
        if errors:
            print("Errors:", file=sys.stderr)
            for error in errors[:50]:
                print(f"- {error}", file=sys.stderr)
            if len(errors) > 50:
                print(f"- {len(errors) - 50} more error(s) omitted; use --json for all", file=sys.stderr)
        if warnings:
            print("Warnings:")
            for warning in warnings[:50]:
                print(f"- {warning}")
            if len(warnings) > 50:
                print(f"- {len(warnings) - 50} more warning(s) omitted; use --json for all")

    if args.strict and (errors or warnings):
        return 1
    if args.check and errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
