"""Canonical host hook shapes and timeout budgets."""

from __future__ import annotations

import hashlib
import textwrap


DISPATCH_PREFIX = '"$HOME/.agents/hooks/dispatch.py" --host '
KIMI_SESSION_GUARD_COMMAND = '"$HOME/.agents/kimi/session-guard.py" --hook'
KIMI_POLICY_MARKER_PREFIX = "managed-policy-sha256:"
HOST_TIMEOUT_MARGIN_SECONDS = 30


def hook_budgets(catalog: dict) -> dict[str, int]:
    events = catalog.get("hookEvents")
    budgets = catalog.get("hookBudgetsSeconds")
    if not isinstance(events, list) or not isinstance(budgets, dict):
        raise ValueError("catalog must define hook events and budgets")
    if set(budgets) != set(events):
        raise ValueError("hook budget keys must match hook events")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in budgets.values()):
        raise ValueError("hook budgets must be positive integers")
    return budgets


def is_managed_dispatch_command(value: object) -> bool:
    return isinstance(value, str) and value.startswith(DISPATCH_PREFIX)


def is_managed_kimi_hook_command(value: object) -> bool:
    return is_managed_dispatch_command(value) or value == KIMI_SESSION_GUARD_COMMAND


def expected_grouped_hooks(host: str, budgets: dict[str, int]) -> dict:
    return {
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{DISPATCH_PREFIX}{host} Stop",
                        "timeout": budgets["Stop"] + HOST_TIMEOUT_MARGIN_SECONDS,
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
                        "command": f"{DISPATCH_PREFIX}{host} PreToolUse",
                        "timeout": budgets["PreToolUse"] + HOST_TIMEOUT_MARGIN_SECONDS,
                    }
                ],
            }
        ],
    }


def expected_cursor_hooks(budgets: dict[str, int]) -> dict:
    return {
        "stop": [
            {
                "command": f"{DISPATCH_PREFIX}cursor Stop",
                "timeout": budgets["Stop"] + HOST_TIMEOUT_MARGIN_SECONDS,
            }
        ],
        "preToolUse": [
            {
                "matcher": "Shell",
                "command": f"{DISPATCH_PREFIX}cursor PreToolUse",
                "timeout": budgets["PreToolUse"] + HOST_TIMEOUT_MARGIN_SECONDS,
            }
        ],
    }


def expected_kimi_hooks(budgets: dict[str, int]) -> list[dict]:
    dispatch_hooks = [
        {
            "event": event,
            "command": f"{DISPATCH_PREFIX}kimi {event}",
            "matcher": "^Shell$" if event == "PreToolUse" else "",
            "timeout": min(
                budgets[event] + HOST_TIMEOUT_MARGIN_SECONDS,
                600,
            ),
        }
        for event in ("Stop", "PreToolUse")
    ]
    return [
        *dispatch_hooks,
        {
            "event": "UserPromptSubmit",
            "command": KIMI_SESSION_GUARD_COMMAND,
            "matcher": "",
            "timeout": 10,
        },
    ]


def cursor_rule(policy: str) -> str:
    return (
        "---\n"
        "description: Canonical global engineering policy\n"
        "alwaysApply: true\n"
        "---\n\n"
        "Generated from the canonical agent system. Edit the source, then rerun the installer.\n\n"
        + policy.rstrip()
        + "\n"
    )


def kimi_agent_spec(policy: str) -> str:
    """Render the canonical policy into Kimi's default-agent extension point."""
    marker = kimi_policy_marker(policy)
    indented_policy = textwrap.indent(
        f"{marker}\n\n{policy.rstrip()}",
        "      ",
    )
    return (
        "version: 1\n"
        "agent:\n"
        "  extend: default\n"
        "  name: coding-worker\n"
        "  subagents: {}\n"
        "  system_prompt_args:\n"
        "    ROLE_ADDITIONAL: |-\n"
        f"{indented_policy}\n"
    )


def kimi_policy_marker(policy: str) -> str:
    digest = hashlib.sha256(policy.rstrip().encode("utf-8")).hexdigest()
    return f"{KIMI_POLICY_MARKER_PREFIX}{digest}"
