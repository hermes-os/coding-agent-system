"""Canonical host hook shapes and timeout budgets."""

from __future__ import annotations


DISPATCH_PREFIX = '"$HOME/.agents/hooks/dispatch.py" --host '
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
