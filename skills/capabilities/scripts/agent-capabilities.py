#!/usr/bin/env python3
"""Report available host tools and scoped skills without reading secret values."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil


TOOL_GROUPS = {
    "core": ("git", "gh", "rg", "jq", "curl", "ssh", "tmux", "make"),
    "runtimes": ("node", "npm", "npx", "pnpm", "yarn", "bun", "python3", "ruby", "go", "rustc", "swift"),
    "agents": ("codex", "claude", "cursor-agent"),
    "agent_system": ("agent-autoreview", "agent-lease", "agent-session-recover", "agent-trash"),
    "platforms": ("vercel", "wrangler", "prisma", "docker"),
    "browser_gui": ("playwright", "agent-browser", "peekaboo"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def skill_metadata(path: Path) -> tuple[str, str] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    values: dict[str, str] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == "---":
            break
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            if value in {"|", "|-", ">", ">-"}:
                block: list[str] = []
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if candidate.strip() == "---" or (candidate and not candidate[0].isspace()):
                        break
                    if candidate.strip():
                        block.append(candidate.strip())
                    index += 1
                values[key.strip()] = " ".join(block)
                continue
            values[key.strip()] = unquote(value)
        index += 1
    name = values.get("name", "").strip()
    description = values.get("description", "").strip()
    return (name, description) if name else None


def skills(root: Path) -> list[dict[str, str]]:
    if not root.is_dir():
        return []
    found: list[dict[str, str]] = []
    seen: set[Path] = set()
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            real = skill_file.resolve()
        except OSError:
            real = skill_file
        if real in seen:
            continue
        seen.add(real)
        metadata = skill_metadata(skill_file)
        if metadata:
            name, description = metadata
            found.append({"name": name, "description": description, "path": str(skill_file)})
    return found


def configured_hosts(home: Path) -> dict[str, bool]:
    return {
        "codex": (home / ".codex" / "AGENTS.md").is_file() and (home / ".codex" / "hooks.json").is_file(),
        "claude": (home / ".claude" / "CLAUDE.md").is_file() and (home / ".claude" / "settings.json").is_file(),
        "cursor": (home / ".cursor" / "rules" / "global-engineering.mdc").is_file()
        and (home / ".cursor" / "hooks.json").is_file(),
    }


def main() -> int:
    args = parse_args()
    home = args.home.expanduser().resolve()
    repo = args.repo.expanduser().resolve() if args.repo else None
    tools = {
        group: {name: path for name in names if (path := shutil.which(name))}
        for group, names in TOOL_GROUPS.items()
    }
    report = {
        "system": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "shell": Path(os.environ.get("SHELL", "")).name or None,
        },
        "hosts": configured_hosts(home),
        "tools": tools,
        "globalSkills": skills(home / ".agents" / "skills"),
        "repositorySkills": skills(repo / ".agents" / "skills") if repo else [],
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
        return 0

    system = report["system"]
    print(f"System: {system['platform']} {system['architecture']} shell={system['shell'] or 'unknown'}")
    print("Hosts: " + ", ".join(f"{name}={'ready' if ready else 'missing'}" for name, ready in report["hosts"].items()))
    for group, entries in tools.items():
        values = ", ".join(f"{name}={path}" for name, path in entries.items()) or "none"
        print(f"{group}: {values}")
    global_names = ", ".join(skill["name"] for skill in report["globalSkills"]) or "none"
    repo_names = ", ".join(skill["name"] for skill in report["repositorySkills"]) or "none"
    print(f"Global skills: {global_names}")
    print(f"Repository skills: {repo_names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
