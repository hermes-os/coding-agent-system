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


def resolve_coordination_repo(system_root, explicit):
    candidate = Path(explicit).expanduser().resolve() if explicit else system_root.resolve()
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


def configure_agent_home(agents_home, coordination_repo):
    path = agents_home / "config.json"
    config = read_json(path)
    config["coordinationRepo"] = str(coordination_repo)
    write_json(path, config)


def managed_entries(home, agents_home, system_root, catalog):
    entries = {}

    def symlink(path, target):
        entries[str(path)] = {"kind": "symlink", "target": str(target)}

    def copied(path, source):
        entries[str(path)] = {"kind": "copy", "sha256": sha256_file(source)}

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
    return entries


def matches_managed(path, entry):
    if entry.get("kind") == "symlink":
        return path.is_symlink() and str(path.resolve(strict=False)) == entry.get("target")
    if entry.get("kind") == "copy":
        return path.is_file() and not path.is_symlink() and sha256_file(path) == entry.get("sha256")
    return False


def contained_by(path, roots):
    return any(path == root or root in path.parents for root in roots)


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
        canonical_path = path.parent.resolve(strict=False) / path.name
        if not path.is_absolute() or not contained_by(canonical_path, allowed_roots):
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


def configure_claude(home):
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
    settings["hooks"] = {
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$HOME/.agents/hooks/dispatch.py" --host claude Stop',
                        "timeout": 330,
                    }
                ],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$HOME/.agents/hooks/dispatch.py" --host claude PreToolUse',
                        "timeout": 630,
                    }
                ],
            }
        ],
    }
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


def configure_codex_hooks(home):
    write_json(
        home / ".codex" / "hooks.json",
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": '"$HOME/.agents/hooks/dispatch.py" --host codex Stop',
                                "timeout": 330,
                            }
                        ],
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": '"$HOME/.agents/hooks/dispatch.py" --host codex PreToolUse',
                                "timeout": 630,
                            }
                        ],
                    }
                ],
            }
        },
    )


def section_name(line):
    match = re.match(r"^\s*\[([^]]+)]\s*$", line)
    return match.group(1) if match else None


def remove_sections(lines, predicate):
    result = []
    skip = False
    for line in lines:
        name = section_name(line)
        if name is not None:
            skip = predicate(name)
        if not skip:
            result.append(line)
    return result


def set_feature(lines, key, value):
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        name = section_name(line)
        if name == "features":
            start = index
            continue
        if start is not None and name is not None:
            end = index
            break

    assignment = f"{key} = {value}\n"
    if start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(["[features]\n", assignment])
        return lines

    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(start + 1, end):
        if key_re.match(lines[index]):
            lines[index] = assignment
            return lines
    lines.insert(start + 1, assignment)
    return lines


def set_root_value(lines, key, value):
    end = next(
        (index for index, line in enumerate(lines) if section_name(line) is not None),
        len(lines),
    )
    assignment = f"{key} = {value}\n"
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(end):
        if key_re.match(lines[index]):
            lines[index] = assignment
            return lines

    lines.insert(end, assignment)
    return lines


def remove_codex_model_pins(lines):
    result = []
    section = None
    model_assignment = re.compile(r"^\s*model\s*=")
    for line in lines:
        name = section_name(line)
        if name is not None:
            section = name
        if model_assignment.match(line) and (
            section is None or section == "profiles" or section.startswith("profiles.")
        ):
            continue
        result.append(line)
    return result


def configure_codex_toml(home):
    path = home / ".codex" / "config.toml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []

    def obsolete(name):
        if name == "marketplaces.karpathy-skills" or name == "hooks.state" or name.startswith("hooks.state."):
            return True
        if name.startswith('plugins."') and name.endswith('"'):
            return name[len('plugins."') : -1] in LEGACY_CODEX_PLUGINS
        return False

    lines = remove_sections(lines, obsolete)
    lines = remove_codex_model_pins(lines)
    lines = set_root_value(lines, "sandbox_mode", '"danger-full-access"')
    lines = set_root_value(lines, "approval_policy", '"never"')
    lines = set_feature(lines, "memories", "false")
    atomic_write(path, "".join(lines))


def configure_shell_rc(path):
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(
        rf"(?ms)^{re.escape(SHELL_BLOCK_BEGIN)}\n.*?^{re.escape(SHELL_BLOCK_END)}\n?"
    )
    content = pattern.sub("", content).rstrip()
    if content:
        content += "\n\n"
    atomic_write(path, content + SHELL_BLOCK)


def configure_cursor(home, policy):
    write_json(
        home / ".cursor" / "hooks.json",
        {
            "version": 1,
            "hooks": {
                "stop": [
                    {
                        "command": '"$HOME/.agents/hooks/dispatch.py" --host cursor Stop',
                        "timeout": 330,
                    }
                ],
                "preToolUse": [
                    {
                        "matcher": "Shell",
                        "command": '"$HOME/.agents/hooks/dispatch.py" --host cursor PreToolUse',
                        "timeout": 630,
                    }
                ],
            },
        },
    )
    rule = (
        "---\n"
        "description: Canonical global engineering policy\n"
        "alwaysApply: true\n"
        "---\n\n"
        "Generated from the canonical agent system. Edit the source, then rerun the installer.\n\n"
        + policy.rstrip()
        + "\n"
    )
    atomic_write(home / ".cursor" / "rules" / "global-engineering.mdc", rule)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-root", required=True, type=Path)
    parser.add_argument("--coordination-repo", type=Path)
    args = parser.parse_args()
    home = Path(os.environ.get("HOME", "~")).expanduser().resolve()
    system_root = args.system_root.expanduser().resolve()
    agents_home = Path(os.environ.get("AGENTS_HOME", home / ".agents")).expanduser().resolve()
    catalog = load_catalog(system_root)
    coordination_repo = resolve_coordination_repo(system_root, args.coordination_repo)
    policy = (system_root / "AGENTS.md").read_text(encoding="utf-8")
    configure_claude(home)
    configure_codex_hooks(home)
    configure_codex_toml(home)
    configure_cursor(home, policy)
    for name in (".zshrc", ".bashrc", ".bash_profile", ".profile"):
        configure_shell_rc(home / name)
    configure_agent_home(agents_home, coordination_repo)
    manifest_path = agents_home / "managed-install.json"
    entries = managed_entries(home, agents_home, system_root, catalog)
    allowed_roots = tuple(
        path.resolve()
        for path in (
            agents_home,
            home / ".codex",
            home / ".claude",
            home / ".cursor",
            home / ".local" / "bin",
        )
    )
    orphaned = prune_stale_managed(manifest_path, entries, allowed_roots)
    write_json(
        manifest_path,
        {
            "version": 1,
            "sourceRoot": str(system_root),
            "catalogSha256": sha256_file(system_root / "system.json"),
            "paths": entries,
            "orphanedPaths": orphaned,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
