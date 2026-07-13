#!/usr/bin/env python3
"""Install generated host configuration without duplicating canonical policy."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
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
    args = parser.parse_args()
    home = Path(os.environ.get("HOME", "~")).expanduser().resolve()
    policy = (args.system_root / "AGENTS.md").read_text(encoding="utf-8")
    configure_claude(home)
    configure_codex_hooks(home)
    configure_codex_toml(home)
    configure_cursor(home, policy)
    for name in (".zshrc", ".bashrc", ".bash_profile", ".profile"):
        configure_shell_rc(home / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
