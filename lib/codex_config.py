"""Semantics-preserving edits for the Codex TOML configuration."""

from __future__ import annotations

from dataclasses import dataclass
import re
import tomllib


MARKER = "__coding_agent_system_marker__"


@dataclass
class ScanState:
    multiline: str | None = None
    square_depth: int = 0
    curly_depth: int = 0


@dataclass(frozen=True)
class LineContext:
    visible: str
    starts_top_level: bool
    ends_top_level: bool


@dataclass(frozen=True)
class Statement:
    kind: str
    path: tuple[str, ...]
    start: int
    end: int
    is_array_table: bool = False
    key_path: tuple[str, ...] = ()


def _unescaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 0


def _scan_line(line: str, state: ScanState) -> str:
    visible: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(line):
        if state.multiline:
            delimiter = state.multiline
            if line.startswith(delimiter, index) and (
                delimiter == "'''" or _unescaped(line, index)
            ):
                visible.append(delimiter)
                state.multiline = None
                index += 3
            else:
                visible.append(line[index])
                index += 1
            continue

        char = line[index]
        if quote:
            visible.append(char)
            if quote == '"' and char == "\\":
                if index + 1 < len(line):
                    visible.append(line[index + 1])
                    index += 2
                    continue
            if char == quote:
                quote = None
            index += 1
            continue

        if line.startswith('"""', index) or line.startswith("'''", index):
            delimiter = line[index : index + 3]
            visible.append(delimiter)
            state.multiline = delimiter
            index += 3
            continue
        if char in {'"', "'"}:
            quote = char
            visible.append(char)
            index += 1
            continue
        if char == "#":
            break
        if char == "[":
            state.square_depth += 1
        elif char == "]":
            state.square_depth = max(0, state.square_depth - 1)
        elif char == "{":
            state.curly_depth += 1
        elif char == "}":
            state.curly_depth = max(0, state.curly_depth - 1)
        visible.append(char)
        index += 1
    return "".join(visible)


def _line_contexts(lines: list[str]) -> list[LineContext]:
    state = ScanState()
    contexts: list[LineContext] = []
    for line in lines:
        starts_top = state.multiline is None and state.square_depth == 0 and state.curly_depth == 0
        visible = _scan_line(line, state)
        ends_top = state.multiline is None and state.square_depth == 0 and state.curly_depth == 0
        contexts.append(LineContext(visible, starts_top, ends_top))
    if state.multiline or state.square_depth or state.curly_depth:
        raise ValueError("Codex TOML contains an unterminated multiline value")
    return contexts


def _find_marker(value: object, path: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if child == MARKER:
                return (*path, key)
            found = _find_marker(child, (*path, key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_marker(child, path)
            if found is not None:
                return found
    return None


def _header(visible: str) -> tuple[tuple[str, ...], bool] | None:
    stripped = visible.strip()
    is_array = bool(re.fullmatch(r"\[\[.*]]", stripped, re.DOTALL))
    if not is_array and not re.fullmatch(r"\[.*]", stripped, re.DOTALL):
        return None
    try:
        parsed = tomllib.loads(f"{stripped}\n{MARKER} = \"{MARKER}\"\n")
    except tomllib.TOMLDecodeError:
        return None
    path = _find_marker(parsed)
    if path is None or not path or path[-1] != MARKER:
        return None
    return path[:-1], is_array


def _assignment_key(visible: str) -> tuple[str, ...] | None:
    quote: str | None = None
    escaped = False
    separator = None
    for index, char in enumerate(visible):
        if quote:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = None
            escaped = False
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "=":
            separator = index
            break
    if separator is None:
        return None
    key = visible[:separator].strip()
    if not key:
        return None
    try:
        parsed = tomllib.loads(f"{key} = \"{MARKER}\"\n")
    except tomllib.TOMLDecodeError:
        return None
    return _find_marker(parsed)


def statements(lines: list[str]) -> list[Statement]:
    contexts = _line_contexts(lines)
    result: list[Statement] = []
    table: tuple[str, ...] = ()
    index = 0
    while index < len(lines):
        context = contexts[index]
        if not context.starts_top_level:
            index += 1
            continue
        header = _header(context.visible)
        if header is not None:
            table, is_array = header
            result.append(Statement("table", table, index, index + 1, is_array))
            index += 1
            continue
        key = _assignment_key(context.visible)
        if key is None:
            index += 1
            continue
        end = index + 1
        while end <= len(lines) and not contexts[end - 1].ends_top_level:
            end += 1
        result.append(
            Statement(
                "assignment",
                (*table, *key),
                index,
                end,
                key_path=key,
            )
        )
        index = end
    return result


def _remove_spans(lines: list[str], spans: list[tuple[int, int]]) -> list[str]:
    removed = [False] * len(lines)
    for start, end in spans:
        for index in range(start, min(end, len(lines))):
            removed[index] = True
    return [line for index, line in enumerate(lines) if not removed[index]]


def _model_assignment(path: tuple[str, ...]) -> bool:
    return path == ("model",) or (len(path) >= 2 and path[0] == "profiles" and path[-1] == "model")


def _strip_owned_values(lines: list[str]) -> list[str]:
    parsed = statements(lines)
    spans: list[tuple[int, int]] = []
    for statement in parsed:
        if statement.kind == "assignment" and _model_assignment(statement.path):
            spans.append((statement.start, statement.end))
    result = _remove_spans(lines, spans)
    remaining = tomllib.loads("".join(result))
    pins = model_pin_paths(remaining)
    if pins:
        raise ValueError(
            "cannot safely remove model pins embedded in inline tables: "
            + ", ".join(pins)
        )
    return result


def _upsert(lines: list[str], table: tuple[str, ...], key: str, value: str) -> list[str]:
    target = (*table, key)
    parsed = statements(lines)
    for statement in parsed:
        if statement.kind == "assignment" and statement.path == target:
            assignment_key = ".".join(statement.key_path)
            return [
                *lines[: statement.start],
                f"{assignment_key} = {value}\n",
                *lines[statement.end :],
            ]

    if not table:
        first_header = next(
            (statement.start for statement in parsed if statement.kind == "table"),
            len(lines),
        )
        return [*lines[:first_header], f"{key} = {value}\n", *lines[first_header:]]

    header = next(
        (
            statement
            for statement in parsed
            if statement.kind == "table" and not statement.is_array_table and statement.path == table
        ),
        None,
    )
    if header is not None:
        return [*lines[: header.end], f"{key} = {value}\n", *lines[header.end :]]

    if lines and lines[-1].strip():
        lines = [*lines, "\n"]
    dotted = ".".join(table)
    return [*lines, f"[{dotted}]\n", f"{key} = {value}\n"]


def edit_codex_config(text: str) -> str:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid existing Codex TOML: {exc}") from exc

    lines = _strip_owned_values(text.splitlines(keepends=True))
    lines = _upsert(lines, (), "sandbox_mode", '"danger-full-access"')
    lines = _upsert(lines, (), "approval_policy", '"never"')
    lines = _upsert(lines, ("features",), "memories", "false")
    result = "".join(lines)
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"generated invalid Codex TOML: {exc}") from exc
    return result


def model_pin_paths(config: dict) -> list[str]:
    pins: list[str] = []
    if "model" in config:
        pins.append("model")

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                current = (*path, key)
                if key == "model":
                    pins.append(".".join(current))
                visit(child, current)

    profiles = config.get("profiles")
    if isinstance(profiles, dict):
        visit(profiles, ("profiles",))
    return sorted(set(pins))
