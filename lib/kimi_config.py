"""Preserve a Kimi TOML config while managing one bounded hook block."""

from __future__ import annotations

import json
import re
import tomllib

from lib.host_contract import (
    DISPATCH_PREFIX,
    KIMI_SESSION_GUARD_COMMAND,
    expected_kimi_hooks,
    is_managed_kimi_hook_command,
)


BLOCK_BEGIN = "# >>> global agent skill hooks >>>"
BLOCK_END = "# <<< global agent skill hooks <<<"
BLOCK_PATTERN = re.compile(
    rf"(?ms)^{re.escape(BLOCK_BEGIN)}\n.*?^{re.escape(BLOCK_END)}\n?"
)


def _without_managed_block(text: str) -> tuple[str, bool]:
    starts = text.count(BLOCK_BEGIN)
    ends = text.count(BLOCK_END)
    if starts != ends or starts > 1:
        raise ValueError("malformed global agent hook marker block")
    if not starts:
        return text, False
    cleaned, replacements = BLOCK_PATTERN.subn("", text)
    if replacements != 1:
        raise ValueError("malformed global agent hook marker block")
    return cleaned, True


def _document(text: str) -> dict:
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Kimi configuration must be a TOML document")
    hooks = value.get("hooks", [])
    if not isinstance(hooks, list):
        raise ValueError("Kimi hooks must be an array of tables")
    return value


def _hook_toml(hook: dict) -> str:
    return (
        "[[hooks]]\n"
        f"event = {json.dumps(hook['event'])}\n"
        f"command = {json.dumps(hook['command'])}\n"
        f"matcher = {json.dumps(hook['matcher'])}\n"
        f"timeout = {hook['timeout']}\n"
    )


def edit_kimi_config(text: str, budgets: dict[str, int]) -> str:
    cleaned, had_marker = _without_managed_block(text)
    document = _document(cleaned)
    hooks = document.get("hooks", [])
    managed = [
        hook
        for hook in hooks
        if isinstance(hook, dict)
        and is_managed_kimi_hook_command(hook.get("command"))
    ]
    expected = expected_kimi_hooks(budgets)
    if managed:
        if had_marker or managed != expected:
            raise ValueError("stale or altered managed Kimi dispatch hook")
        return text
    prefix = cleaned.rstrip()
    if prefix:
        prefix += "\n\n"
    managed_text = "\n".join(_hook_toml(hook).rstrip() for hook in expected)
    updated = f"{prefix}{BLOCK_BEGIN}\n{managed_text}\n{BLOCK_END}\n"
    tomllib.loads(updated)
    return updated


def contains_expected_kimi_hooks(text: str, budgets: dict[str, int]) -> bool:
    starts = text.count(BLOCK_BEGIN)
    ends = text.count(BLOCK_END)
    if starts != ends or starts > 1:
        return False
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    hooks = document.get("hooks", []) if isinstance(document, dict) else []
    if not isinstance(hooks, list):
        return False
    managed = [
        hook
        for hook in hooks
        if isinstance(hook, dict)
        and is_managed_kimi_hook_command(hook.get("command"))
    ]
    return managed == expected_kimi_hooks(budgets)


def has_managed_kimi_hooks(text: str) -> bool:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return any(
            marker in text
            for marker in (
                BLOCK_BEGIN,
                BLOCK_END,
                DISPATCH_PREFIX,
                KIMI_SESSION_GUARD_COMMAND,
            )
        )
    hooks = document.get("hooks", []) if isinstance(document, dict) else []
    return (
        BLOCK_BEGIN in text
        or BLOCK_END in text
        or (
            isinstance(hooks, list)
            and any(
                isinstance(hook, dict)
                and is_managed_kimi_hook_command(hook.get("command"))
                for hook in hooks
            )
        )
    )


def remove_kimi_hooks(text: str, budgets: dict[str, int]) -> str:
    cleaned, had_marker = _without_managed_block(text)
    document = _document(cleaned)
    hooks = document.get("hooks", [])
    managed = [
        hook
        for hook in hooks
        if isinstance(hook, dict)
        and is_managed_kimi_hook_command(hook.get("command"))
    ]
    if had_marker:
        if managed:
            raise ValueError("managed Kimi hook exists outside its marker block")
        return cleaned.rstrip() + ("\n" if cleaned.strip() else "")
    if not managed:
        return text
    expected = expected_kimi_hooks(budgets)
    if managed != expected:
        raise ValueError("stale or altered managed Kimi dispatch hook")
    updated = text
    for hook in expected:
        block = _hook_toml(hook)
        if updated.count(block) != 1:
            raise ValueError(
                "cannot safely remove Kimi-rewritten managed hook formatting"
            )
        updated = updated.replace(block, "", 1)
    _document(updated)
    if has_managed_kimi_hooks(updated):
        raise ValueError("managed Kimi hooks remain after removal")
    return updated.rstrip() + ("\n" if updated.strip() else "")
