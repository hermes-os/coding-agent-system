#!/usr/bin/env python3
"""Install generated host configuration without duplicating canonical policy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

from lib.codex_config import edit_codex_config
from lib.host_contract import (
    cursor_rule,
    expected_cursor_hooks,
    expected_grouped_hooks,
    hook_budgets,
    is_managed_dispatch_command,
)


CLAUDE_MODEL_ENV_KEYS = {
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_MODEL",
    "CLAUDE_CODE_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
}

SHELL_BLOCK_BEGIN = "# >>> global agent invocation defaults >>>"
SHELL_BLOCK_END = "# <<< global agent invocation defaults <<<"
SHELL_BLOCK = (
    f"{SHELL_BLOCK_BEGIN}\n"
    '[ -r "$HOME/.agents/shell/default-invocations.sh" ] && '
    '. "$HOME/.agents/shell/default-invocations.sh"\n'
    f"{SHELL_BLOCK_END}\n"
)


def atomic_write(path, content, mode=0o644):
    if path.is_symlink():
        raise SystemExit(f"Refusing to replace symlinked configuration file: {path}")
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(content)
        temp = Path(handle.name)
    try:
        temp.chmod(mode)
        if path.is_symlink():
            raise SystemExit(f"Refusing to replace symlinked configuration file: {path}")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected JSON object in {path}")
    return value


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, sort_keys=False) + "\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_catalog(system_root):
    path = system_root / "system.json"
    catalog = read_json(path)
    if catalog.get("schemaVersion") != 1:
        raise SystemExit(f"Unsupported catalog schema in {path}")
    return catalog


def resolve_coordination_repo(system_root, agents_home, explicit):
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
    else:
        existing = read_json(agents_home / "config.json")
        persisted = existing.get("coordinationRepo")
        if persisted is not None and not isinstance(persisted, str):
            raise SystemExit("Existing coordinationRepo must be a string")
        candidate = Path(persisted).expanduser().resolve() if persisted else system_root.resolve()
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(f"Coordination repository is not a Git checkout: {candidate}")
    root = Path(result.stdout.strip()).resolve()
    if root != candidate:
        raise SystemExit(f"Coordination repository must be a Git root: {candidate}")
    return root


def configure_agent_home(agents_home, coordination_repo, host_integration, shell_rc_paths):
    path = agents_home / "config.json"
    config = read_json(path)
    config["coordinationRepo"] = str(coordination_repo)
    config["hostIntegrationRoot"] = str(host_integration)
    config["shellRcPaths"] = [str(path) for path in shell_rc_paths]
    write_json(path, config)


def resolve_host_integration(system_root, explicit):
    root = (explicit or system_root / "host" / "local").expanduser().resolve()
    required = (
        root / "bin" / "agent-claude",
        root / "bin" / "agent-codex",
        root / "shell" / "default-invocations.sh",
    )
    missing = [path for path in required if not path.is_file()]
    symlinks = [path for path in required if path.is_symlink()]
    non_executable = [path for path in required[:2] if path.is_file() and not os.access(path, os.X_OK)]
    shell_adapter = required[2]
    unreadable = (
        [shell_adapter]
        if shell_adapter.is_file() and not os.access(shell_adapter, os.R_OK)
        else []
    )
    if missing or symlinks or non_executable or unreadable:
        problems = [
            *(f"missing {path}" for path in missing),
            *(f"symlinked source {path}" for path in symlinks),
            *(f"not executable {path}" for path in non_executable),
            *(f"not readable {path}" for path in unreadable),
        ]
        raise SystemExit("Invalid host integration:\n" + "\n".join(f"- {problem}" for problem in problems))
    return root


def legacy_catalog_sources(root, catalog):
    skills = catalog.get("skills")
    binaries = catalog.get("binaries")
    if not isinstance(skills, list) or not isinstance(binaries, list):
        raise SystemExit(f"Invalid legacy catalog entries in {root / 'system.json'}")

    required = [
        root / "system.json",
        root / "AGENTS.md",
        root / "hooks" / "dispatch.py",
        root / "bin" / "agent-claude",
        root / "bin" / "agent-codex",
        root / "shell" / "default-invocations.sh",
    ]
    skill_names = set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise SystemExit(f"Invalid legacy skill entry in {root / 'system.json'}")
        name = skill.get("name")
        command = skill.get("command")
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) is None
            or name in skill_names
            or not isinstance(command, bool)
        ):
            raise SystemExit(f"Invalid legacy skill entry in {root / 'system.json'}")
        skill_names.add(name)
        required.append(root / "skills" / name / "SKILL.md")

    binary_names = set()
    for binary in binaries:
        if not isinstance(binary, dict):
            raise SystemExit(f"Invalid legacy binary entry in {root / 'system.json'}")
        name = binary.get("name")
        source = binary.get("source")
        source_path = Path(source) if isinstance(source, str) else None
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) is None
            or name in binary_names
            or source_path is None
            or source_path.is_absolute()
            or ".." in source_path.parts
        ):
            raise SystemExit(f"Invalid legacy binary entry in {root / 'system.json'}")
        binary_names.add(name)
        required.append(root / source_path)
    return required


def resolve_migration_root(explicit, system_root):
    if explicit is None:
        return None, None
    candidate = explicit.expanduser()
    if candidate.is_symlink():
        raise SystemExit(f"Legacy system root must not be a symlink: {candidate}")
    root = candidate.resolve()
    if root == system_root:
        raise SystemExit("Legacy system root must differ from the new system root")
    catalog_path = root / "system.json"
    if (
        not catalog_path.is_file()
        or catalog_path.is_symlink()
        or catalog_path.resolve() != catalog_path
    ):
        raise SystemExit(f"Legacy system root lacks a regular catalog: {catalog_path}")
    catalog = load_catalog(root)
    required = legacy_catalog_sources(root, catalog)
    missing = [path for path in required if not path.is_file()]
    symlinks = [
        path
        for path in required
        if path.exists() and (path.is_symlink() or path.resolve() != path)
    ]
    if missing or symlinks:
        problems = [
            *(f"missing {path}" for path in missing),
            *(f"symlinked source {path}" for path in symlinks),
        ]
        raise SystemExit(
            "Invalid legacy system root:\n" + "\n".join(f"- {problem}" for problem in problems)
        )

    repository = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if repository.returncode:
        raise SystemExit(f"Legacy system root is not in a Git checkout: {root}")
    git_root = Path(repository.stdout.strip()).resolve()
    try:
        pathspec = str(root.relative_to(git_root)) or "."
    except ValueError as exc:
        raise SystemExit(f"Legacy system root escapes its Git checkout: {root}") from exc
    required_paths = [path.relative_to(git_root).as_posix() for path in required]
    tracked = subprocess.run(
        ["git", "-C", str(git_root), "ls-files", "--", *required_paths],
        text=True,
        capture_output=True,
        check=False,
    )
    tracked_paths = set(tracked.stdout.splitlines())
    if tracked.returncode or tracked_paths != set(required_paths):
        raise SystemExit(f"Legacy system root contains untracked required files: {root}")
    status = subprocess.run(
        [
            "git",
            "-C",
            str(git_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored=matching",
            "--",
            pathspec,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode or status.stdout.strip():
        raise SystemExit(f"Legacy system root must be tracked and clean: {root}")
    return root, catalog


def managed_entries(home, agents_home, system_root, host_integration, catalog, policy):
    entries = {}

    def symlink(path, target):
        entries[str(path)] = {"kind": "symlink", "target": str(target)}

    def copied(path, source):
        entries[str(path)] = {
            "kind": "copy",
            "source": str(source),
            "sha256": sha256_file(source),
        }

    def generated(path, content):
        entries[str(path)] = {
            "kind": "generated",
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    symlink(agents_home / "AGENTS.md", system_root / "AGENTS.md")
    symlink(agents_home / "hooks" / "dispatch.py", system_root / "hooks" / "dispatch.py")
    symlink(
        agents_home / "shell" / "default-invocations.sh",
        host_integration / "shell" / "default-invocations.sh",
    )
    for adapter in (
        home / ".codex" / "AGENTS.md",
        home / ".claude" / "CLAUDE.md",
        home / ".claude" / "AGENTS.md",
    ):
        symlink(adapter, system_root / "AGENTS.md")

    for binary in catalog.get("binaries", []):
        source = system_root / binary["source"]
        for destination in (
            agents_home / "bin" / binary["name"],
            home / ".local" / "bin" / binary["name"],
        ):
            symlink(destination, source)

    for name in ("agent-claude", "agent-codex"):
        source = host_integration / "bin" / name
        for destination in (agents_home / "bin" / name, home / ".local" / "bin" / name):
            symlink(destination, source)

    for skill in catalog.get("skills", []):
        name = skill["name"]
        source = system_root / "skills" / name
        symlink(agents_home / "skills" / name, source)
        symlink(home / ".claude" / "skills" / name, source)
        if skill.get("command") is True:
            skill_file = source / "SKILL.md"
            symlink(home / ".codex" / "prompts" / f"{name}.md", skill_file)
            symlink(home / ".claude" / "commands" / f"{name}.md", skill_file)
            copied(home / ".cursor" / "commands" / f"{name}.md", skill_file)
    generated(home / ".cursor" / "rules" / "global-engineering.mdc", cursor_rule(policy))
    return entries


def matches_managed(path, entry):
    if entry.get("kind") == "symlink":
        target = entry.get("target")
        return (
            isinstance(target, str)
            and path.is_symlink()
            and path.resolve(strict=False) == Path(target).resolve(strict=False)
        )
    if entry.get("kind") in {"copy", "generated"}:
        return path.is_file() and not path.is_symlink() and sha256_file(path) == entry.get("sha256")
    return False


def contained_by(path, roots):
    return any(path == root or root in path.parents for root in roots)


def managed_root(path, roots):
    canonical = path.parent.resolve(strict=False) / path.name
    return next(
        (
            root
            for root in roots
            if canonical == root.resolve(strict=False) or root.resolve(strict=False) in canonical.parents
        ),
        None,
    )


def legacy_generated_entry(previous, path):
    if path.name != "global-engineering.mdc" or path.parent.name != "rules":
        return None
    source_root = previous.get("sourceRoot")
    if not isinstance(source_root, str):
        return None
    policy = Path(source_root) / "AGENTS.md"
    try:
        content = cursor_rule(policy.read_text(encoding="utf-8"))
    except OSError:
        return None
    return {
        "kind": "generated",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def preflight_managed(manifest_path, desired, allowed_roots, adopted=None):
    previous = read_json(manifest_path)
    old_paths = previous.get("paths", {}) if isinstance(previous.get("paths"), dict) else {}
    adopted = adopted or {}
    collisions = []
    for raw_path, entry in desired.items():
        path = Path(raw_path)
        root = managed_root(path, allowed_roots)
        if not path.is_absolute() or root is None:
            collisions.append(f"destination is outside managed roots: {path}")
            continue
        resolved_root = root.resolve(strict=False)
        resolved_parent = path.parent.resolve(strict=False)
        if not contained_by(resolved_parent, (resolved_root,)):
            collisions.append(f"destination parent escapes through a symlink: {path}")
            continue
        if not (path.exists() or path.is_symlink()) or matches_managed(path, entry):
            continue
        previous_entry = old_paths.get(raw_path) or legacy_generated_entry(previous, path)
        if isinstance(previous_entry, dict) and matches_managed(path, previous_entry):
            continue
        adopted_entry = adopted.get(raw_path)
        if isinstance(adopted_entry, dict) and matches_managed(path, adopted_entry):
            continue
        collisions.append(f"unowned or modified destination: {path}")
    for raw_path, entry in adopted.items():
        if raw_path in desired:
            continue
        path = Path(raw_path)
        root = managed_root(path, allowed_roots)
        if not path.is_absolute() or root is None:
            collisions.append(f"legacy destination is outside managed roots: {path}")
            continue
        resolved_root = root.resolve(strict=False)
        resolved_parent = path.parent.resolve(strict=False)
        if not contained_by(resolved_parent, (resolved_root,)):
            collisions.append(f"legacy destination parent escapes through a symlink: {path}")
            continue
        if (path.exists() or path.is_symlink()) and not matches_managed(path, entry):
            collisions.append(f"unowned or modified legacy destination: {path}")
    if collisions:
        detail = "\n".join(f"- {collision}" for collision in collisions)
        raise SystemExit(f"Managed-path preflight failed; no managed paths changed:\n{detail}")


def retire_adopted(adopted, desired, allowed_roots):
    retired = 0
    for raw_path, entry in adopted.items():
        if raw_path in desired:
            continue
        path = Path(raw_path)
        if not (path.exists() or path.is_symlink()):
            continue
        root = managed_root(path, allowed_roots)
        if (
            root is None
            or not contained_by(path.parent.resolve(strict=False), (root.resolve(strict=False),))
            or not matches_managed(path, entry)
        ):
            raise SystemExit(f"Legacy destination changed after preflight: {path}")
        path.unlink()
        retired += 1
    if retired:
        print(f"Retired {retired} legacy managed path(s)")


def install_managed(desired):
    installed = 0
    for raw_path, entry in desired.items():
        path = Path(raw_path)
        if matches_managed(path, entry):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("kind") == "symlink":
            target = entry["target"]
            descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            os.close(descriptor)
            temporary = Path(raw_temporary)
            try:
                temporary.unlink()
                temporary.symlink_to(target)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        elif entry.get("kind") == "copy":
            source = Path(entry["source"])
            atomic_write(path, source.read_text(encoding="utf-8"), mode=0o644)
        elif entry.get("kind") == "generated":
            atomic_write(path, entry["content"], mode=0o644)
        else:
            raise SystemExit(f"Unknown managed path kind for {path}")
        installed += 1
    if installed:
        print(f"Installed {installed} managed path(s)")


def prune_stale_managed(manifest_path, desired, allowed_roots):
    previous = read_json(manifest_path)
    old_paths = previous.get("paths", {}) if isinstance(previous.get("paths"), dict) else {}
    orphaned = [
        path
        for path in previous.get("orphanedPaths", [])
        if isinstance(path, str) and Path(path).exists()
    ]
    for raw_path, entry in old_paths.items():
        if raw_path in desired or not isinstance(entry, dict):
            continue
        path = Path(raw_path)
        root = managed_root(path, allowed_roots)
        canonical_parent = path.parent.resolve(strict=False)
        if (
            not path.is_absolute()
            or root is None
            or not contained_by(canonical_parent, (root.resolve(strict=False),))
        ):
            orphaned.append(raw_path)
            print(f"Preserved retired path outside managed roots: {path}", file=sys.stderr)
            continue
        if matches_managed(path, entry):
            path.unlink()
            continue
        if path.exists() or path.is_symlink():
            orphaned.append(raw_path)
            print(f"Preserved modified retired managed path: {path}", file=sys.stderr)
    return sorted(set(orphaned))


def merge_grouped_hooks(existing, expected, label):
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        raise SystemExit(f"{label} hooks must be an object")
    merged = dict(existing)
    for event, managed_groups in expected.items():
        groups = existing.get(event, [])
        if not isinstance(groups, list):
            raise SystemExit(f"{label} hooks.{event} must be a list")
        preserved = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                preserved.append(group)
                continue
            hooks = [
                hook
                for hook in group["hooks"]
                if not (isinstance(hook, dict) and is_managed_dispatch_command(hook.get("command")))
            ]
            if hooks:
                updated = dict(group)
                updated["hooks"] = hooks
                preserved.append(updated)
            elif len(hooks) == len(group["hooks"]):
                preserved.append(group)
        merged[event] = [*preserved, *managed_groups]
    return merged


def merge_cursor_hooks(existing, expected):
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        raise SystemExit("Cursor hooks must be an object")
    merged = dict(existing)
    for event, managed_entries_for_event in expected.items():
        entries = existing.get(event, [])
        if not isinstance(entries, list):
            raise SystemExit(f"Cursor hooks.{event} must be a list")
        preserved = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and is_managed_dispatch_command(entry.get("command")))
        ]
        merged[event] = [*preserved, *managed_entries_for_event]
    return merged


def preflight_configuration_paths(paths):
    symlinks = sorted(path for path in paths if path.is_symlink())
    if symlinks:
        detail = "\n".join(f"- {path}" for path in symlinks)
        raise SystemExit(
            "Host-configuration preflight failed; no host configuration changed. "
            f"Replace or retarget these symlinks explicitly:\n{detail}"
        )


def preflight_host_documents(home, budgets, shell_paths):
    codex_config = home / ".codex" / "config.toml"
    text = codex_config.read_text(encoding="utf-8") if codex_config.exists() else ""
    try:
        edit_codex_config(text)
    except ValueError as exc:
        raise SystemExit(f"Cannot safely update {codex_config}: {exc}") from exc

    claude = read_json(home / ".claude" / "settings.json")
    merge_grouped_hooks(
        claude.get("hooks"), expected_grouped_hooks("claude", budgets), "Claude"
    )
    codex = read_json(home / ".codex" / "hooks.json")
    merge_grouped_hooks(codex.get("hooks"), expected_grouped_hooks("codex", budgets), "Codex")
    cursor_path = home / ".cursor" / "hooks.json"
    cursor = read_json(cursor_path)
    version = cursor.get("version")
    if version not in (None, 1):
        raise SystemExit(f"Unsupported Cursor hook schema version in {cursor_path}: {version}")
    merge_cursor_hooks(cursor.get("hooks"), expected_cursor_hooks(budgets))
    for path in shell_paths:
        if path.exists():
            try:
                path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SystemExit(f"Cannot safely update shell startup file {path}: {exc}") from exc


def configure_claude(home, budgets):
    path = home / ".claude" / "settings.json"
    settings = read_json(path)
    env = settings.get("env")
    if not isinstance(env, dict):
        env = {}
        settings["env"] = env
    for key in CLAUDE_MODEL_ENV_KEYS:
        env.pop(key, None)
    settings.pop("model", None)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    settings["autoMemoryEnabled"] = False
    settings["autoDreamEnabled"] = False
    permissions = settings.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
        settings["permissions"] = permissions
    permissions["defaultMode"] = "bypassPermissions"
    settings["skipDangerousModePermissionPrompt"] = True
    settings["hooks"] = merge_grouped_hooks(
        settings.get("hooks"), expected_grouped_hooks("claude", budgets), "Claude"
    )
    write_json(path, settings)


def configure_codex_hooks(home, budgets):
    path = home / ".codex" / "hooks.json"
    document = read_json(path)
    document["hooks"] = merge_grouped_hooks(
        document.get("hooks"), expected_grouped_hooks("codex", budgets), "Codex"
    )
    write_json(path, document)


def configure_codex_toml(home):
    path = home / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        updated = edit_codex_config(text)
    except ValueError as exc:
        raise SystemExit(f"Cannot safely update {path}: {exc}") from exc
    atomic_write(path, updated)


def configure_shell_rc(path):
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(
        rf"(?ms)^{re.escape(SHELL_BLOCK_BEGIN)}\n.*?^{re.escape(SHELL_BLOCK_END)}\n?"
    )
    content = pattern.sub("", content).rstrip()
    if content:
        content += "\n\n"
    atomic_write(path, content + SHELL_BLOCK)


def shell_rc_paths(home):
    login_candidates = [home / ".bash_profile", home / ".bash_login", home / ".profile"]
    login = next(
        (path for path in login_candidates if path.exists() or path.is_symlink()),
        login_candidates[0],
    )
    return [home / ".zshrc", home / ".bashrc", login]


def configure_cursor(home, budgets):
    hooks_path = home / ".cursor" / "hooks.json"
    document = read_json(hooks_path)
    version = document.get("version")
    if version not in (None, 1):
        raise SystemExit(f"Unsupported Cursor hook schema version in {hooks_path}: {version}")
    document["version"] = 1
    document["hooks"] = merge_cursor_hooks(
        document.get("hooks"), expected_cursor_hooks(budgets)
    )
    write_json(hooks_path, document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-root", required=True, type=Path)
    parser.add_argument("--coordination-repo", type=Path)
    parser.add_argument("--host-integration", type=Path)
    parser.add_argument("--migrate-from-system-root", type=Path)
    args = parser.parse_args()
    home = Path(os.environ.get("HOME", "~")).expanduser().resolve()
    system_root = args.system_root.expanduser().resolve()
    agents_home = Path(os.environ.get("AGENTS_HOME", home / ".agents")).expanduser().resolve()
    catalog = load_catalog(system_root)
    host_integration = resolve_host_integration(system_root, args.host_integration)
    migration_root, migration_catalog = resolve_migration_root(
        args.migrate_from_system_root, system_root
    )
    try:
        budgets = hook_budgets(catalog)
    except ValueError as exc:
        raise SystemExit(f"Invalid hook budget catalog: {exc}") from exc
    coordination_repo = resolve_coordination_repo(system_root, agents_home, args.coordination_repo)
    policy = (system_root / "AGENTS.md").read_text(encoding="utf-8")
    manifest_path = agents_home / "managed-install.json"
    selected_shell_rc_paths = shell_rc_paths(home)
    configuration_paths = (
        home / ".codex" / "config.toml",
        home / ".claude" / "settings.json",
        home / ".codex" / "hooks.json",
        home / ".cursor" / "hooks.json",
        agents_home / "config.json",
        manifest_path,
        *selected_shell_rc_paths,
    )
    preflight_configuration_paths(configuration_paths)
    entries = managed_entries(
        home, agents_home, system_root, host_integration, catalog, policy
    )
    adopted = None
    if migration_root is not None:
        legacy_policy = (migration_root / "AGENTS.md").read_text(encoding="utf-8")
        adopted = managed_entries(
            home,
            agents_home,
            migration_root,
            migration_root,
            migration_catalog,
            legacy_policy,
        )
    allowed_roots = (
        agents_home,
        home / ".codex",
        home / ".claude",
        home / ".cursor",
        home / ".local" / "bin",
    )
    preflight_managed(manifest_path, entries, allowed_roots, adopted=adopted)
    preflight_host_documents(home, budgets, selected_shell_rc_paths)

    configure_codex_toml(home)
    configure_claude(home, budgets)
    configure_codex_hooks(home, budgets)
    configure_cursor(home, budgets)
    for path in selected_shell_rc_paths:
        configure_shell_rc(path)
    install_managed(entries)
    retire_adopted(adopted or {}, entries, allowed_roots)
    configure_agent_home(
        agents_home, coordination_repo, host_integration, selected_shell_rc_paths
    )
    orphaned = prune_stale_managed(manifest_path, entries, allowed_roots)
    write_json(
        manifest_path,
        {
            "version": 1,
            "sourceRoot": str(system_root),
            "catalogSha256": sha256_file(system_root / "system.json"),
            "paths": {
                path: {key: value for key, value in entry.items() if key != "content"}
                for path, entry in entries.items()
            },
            "orphanedPaths": orphaned,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
