"""Shared direct-child layout contract for active skill roots."""

from __future__ import annotations

from pathlib import Path


def direct_skill_files(root: Path) -> tuple[list[Path], list[str]]:
    if not root.is_dir():
        return [], []

    found: list[Path] = []
    errors: list[str] = []
    try:
        children = sorted((child for child in root.iterdir() if child.is_dir()), key=lambda child: child.name)
    except OSError as exc:
        return [], [f"{root}: cannot list skill root: {exc}"]

    for directory in children:
        skill_file = directory / "SKILL.md"
        hook_file = directory / "hooks.json"
        if hook_file.exists() and not skill_file.is_file():
            errors.append(f"{hook_file}: hooks require an adjacent SKILL.md")
        if skill_file.is_file():
            found.append(skill_file)
        if directory.is_symlink():
            continue
        try:
            nested = sorted(path for path in directory.rglob("SKILL.md") if path != skill_file)
        except OSError as exc:
            errors.append(f"{directory}: cannot inspect nested skill layout: {exc}")
            continue
        for path in nested:
            errors.append(f"{path}: active skills must be direct children of {root}")
    return found, errors
