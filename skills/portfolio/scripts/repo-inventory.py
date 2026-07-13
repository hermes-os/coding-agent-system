#!/usr/bin/env python3
"""Build a read-only inventory of Git repositories and active project plans."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys


SKIP_DIRS = {
    ".cache",
    ".Trash",
    ".venv",
    "Library",
    "node_modules",
    "Pods",
    "vendor",
}
CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


@dataclass
class Repository:
    path: str
    branch: str | None
    head: str | None
    upstream: str | None
    ahead: int | None
    behind: int | None
    staged: int
    unstaged: int
    untracked: int
    conflicts: int
    plans: list[str]
    last_commit: str | None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def run(repo: Path, *args: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode:
        return None, result.stderr.strip() or f"git {' '.join(args)} exited {result.returncode}"
    return result.stdout.rstrip(), None


def discover(root: Path, max_depth: int) -> list[Path]:
    if not root.is_dir():
        return []
    root = root.resolve()
    repositories: list[Path] = []
    for current, dirs, _files in os.walk(root, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIRS and not (name.startswith(".") and name != ".git")
        ]
        if ".git" in dirs or (current_path / ".git").is_file():
            repositories.append(current_path)
            dirs[:] = []
            continue
        if depth >= max_depth:
            dirs[:] = []
    return repositories


def status_counts(value: str) -> tuple[int, int, int, int]:
    staged = unstaged = untracked = conflicts = 0
    for line in value.splitlines():
        if len(line) < 2:
            continue
        code = line[:2]
        if code == "??":
            untracked += 1
            continue
        if code in CONFLICT_CODES:
            conflicts += 1
        if code[0] != " ":
            staged += 1
        if code[1] != " ":
            unstaged += 1
    return staged, unstaged, untracked, conflicts


def inspect(repo: Path) -> Repository:
    branch, branch_error = run(repo, "branch", "--show-current")
    head, head_error = run(repo, "rev-parse", "--short=12", "HEAD")
    upstream, _ = run(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    status, status_error = run(repo, "status", "--porcelain=v1", "--untracked-files=all")
    staged, unstaged, untracked, conflicts = status_counts(status or "")

    ahead = behind = None
    if upstream:
        counts, _ = run(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        if counts:
            left, right = counts.split()
            ahead, behind = int(left), int(right)

    plan_root = repo / "docs" / "plan"
    plans = [str(path.relative_to(repo)) for path in sorted(plan_root.glob("*.md"))] if plan_root.is_dir() else []
    last_commit, _ = run(repo, "log", "-1", "--format=%cs %h %s")
    errors = [error for error in (branch_error, head_error, status_error) if error]
    return Repository(
        path=str(repo),
        branch=branch or None,
        head=head,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        conflicts=conflicts,
        plans=plans,
        last_commit=last_commit,
        error="; ".join(errors) or None,
    )


def main() -> int:
    args = parse_args()
    if args.max_depth < 0:
        print("--max-depth must be non-negative", file=sys.stderr)
        return 2
    roots = args.root or [Path.cwd()]
    found: set[Path] = set()
    for root in roots:
        found.update(discover(root.expanduser(), args.max_depth))
    repositories = [inspect(path) for path in sorted(found, key=str)]
    report = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "roots": [str(root.expanduser().resolve()) for root in roots],
        "repositories": [asdict(repo) for repo in repositories],
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Repositories: {len(repositories)}")
    for repo in repositories:
        dirty = f"S{repo.staged}/M{repo.unstaged}/?{repo.untracked}/!{repo.conflicts}"
        sync = "no-upstream" if repo.upstream is None else f"+{repo.ahead}/-{repo.behind}"
        plan = ",".join(repo.plans) if repo.plans else "none"
        branch = repo.branch or "detached"
        print(f"- {repo.path} [{branch} {sync} {dirty}] plan={plan}")
        if repo.error:
            print(f"  error: {repo.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
