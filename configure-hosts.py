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

from lib.codex_config import edit_codex_config
from lib.host_contract import (
    cursor_rule,
    expected_cursor_hooks,
    expected_grouped_hooks,
    hook_budgets,
    is_managed_dispatch_command,
)


LEGACY_CODEX_PLUGINS = {
    "andrej-karpathy-skills@karpathy-skills",
    "claude-code-setup@claude-plugins-official",
    "claude-md-management@claude-plugins-official",
    "code-review@claude-plugins-official",
    "code-simplifier@claude-plugins-official",
    "superpowers@claude-plugins-official",
}

LEGACY_CLAUDE_PLUGINS = LEGACY_CODEX_PLUGINS | {
    "coderabbit@claude-plugins-official",
    "ralph-loop@claude-plugins-official",
}

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
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(content)
        temp = Path(handle.name)
    temp.chmod(mode)
    temp.replace(path)


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


def configure_agent_home(agents_home, coordination_repo, shell_rc_paths):
    path = agents_home / "config.json"
    config = read_json(path)
    config["coordinationRepo"] = str(coordination_repo)
    config["shellRcPaths"] = [str(path) for path in shell_rc_paths]
    write_json(path, config)


def managed_entries(home, agents_home, system_root, catalog, policy):
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
        system_root / "shell" / "default-invocations.sh",
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


def preflight_managed(manifest_path, desired, allowed_roots):
    previous = read_json(manifest_path)
    old_paths = previous.get("paths", {}) if isinstance(previous.get("paths"), dict) else {}
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
        collisions.append(f"unowned or modified destination: {path}")
    if collisions:
        detail = "\n".join(f"- {collision}" for collision in collisions)
        raise SystemExit(f"Managed-path preflight failed; no managed paths changed:\n{detail}")


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
    enabled = settings.get("enabledPlugins")
    if isinstance(enabled, dict):
        for plugin, is_enabled in list(enabled.items()):
            if plugin in LEGACY_CLAUDE_PLUGINS or is_enabled is not True:
                enabled.pop(plugin, None)
    marketplaces = settings.get("extraKnownMarketplaces")
    if isinstance(marketplaces, dict):
        marketplaces.pop("karpathy-skills", None)
    write_json(path, settings)

    marketplace_path = home / ".claude" / "plugins" / "known_marketplaces.json"
    if marketplace_path.exists():
        known_marketplaces = read_json(marketplace_path)
        known_marketplaces.pop("karpathy-skills", None)
        write_json(marketplace_path, known_marketplaces)


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
    login = next((path for path in login_candidates if path.exists()), login_candidates[0])
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
    args = parser.parse_args()
    home = Path(os.environ.get("HOME", "~")).expanduser().resolve()
    system_root = args.system_root.expanduser().resolve()
    agents_home = Path(os.environ.get("AGENTS_HOME", home / ".agents")).expanduser().resolve()
    catalog = load_catalog(system_root)
    try:
        budgets = hook_budgets(catalog)
    except ValueError as exc:
        raise SystemExit(f"Invalid hook budget catalog: {exc}") from exc
    coordination_repo = resolve_coordination_repo(system_root, agents_home, args.coordination_repo)
    policy = (system_root / "AGENTS.md").read_text(encoding="utf-8")
    manifest_path = agents_home / "managed-install.json"
    entries = managed_entries(home, agents_home, system_root, catalog, policy)
    allowed_roots = (
        agents_home,
        home / ".codex",
        home / ".claude",
        home / ".cursor",
        home / ".local" / "bin",
    )
    preflight_managed(manifest_path, entries, allowed_roots)

    configure_codex_toml(home)
    configure_claude(home, budgets)
    configure_codex_hooks(home, budgets)
    configure_cursor(home, budgets)
    selected_shell_rc_paths = shell_rc_paths(home)
    for path in selected_shell_rc_paths:
        configure_shell_rc(path)
    install_managed(entries)
    configure_agent_home(agents_home, coordination_repo, selected_shell_rc_paths)
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
