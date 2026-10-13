#!/usr/bin/env python3
"""Show a repo-worker run live, read-only, so Hermes can watch it in a herdr pane.

Usage: sudo -n python3 watch-worker.py <runId>
Reads the run's metadata and its Hermes session database in read-only mode.
It never writes to the run, so it cannot disturb the worker.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

RUNS = Path("/var/lib/agent-worker/.local/state/agent-workers/runs")
HOMES = Path("/var/lib/agent-worker/.hermes-worker")
DONE = {"completed", "failed", "blocked", "interrupted", "cancelled", "stopped"}

DIM, BOLD, CYAN, GREEN, YELLOW, RED, RESET = (
    "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def short(text, width=110, lines=3):
    out = []
    for line in str(text).splitlines():
        line = line.rstrip()
        if line:
            out.append(line[:width] + ("…" if len(line) > width else ""))
        if len(out) >= lines:
            out.append("…")
            break
    return out


def meta(run):
    try:
        return json.loads((RUNS / run / "metadata.json").read_text())
    except (OSError, ValueError):
        return {}


def describe_call(call):
    fn = call.get("function", {})
    name = fn.get("name", "?")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        args = {}
    for key in ("command", "path", "pattern", "query", "url", "code", "old_string"):
        if key in args:
            return name, str(args[key])
    return name, json.dumps(args)[:200]


def tool_text(content):
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return content or ""
    if isinstance(data, dict):
        if data.get("error"):
            return f"error: {data['error']}"
        for key in ("output", "content", "result"):
            if key in data:
                return data[key]
    return content


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: watch-worker.py <runId>")
    run = sys.argv[1]
    m = meta(run)
    print(f"{BOLD}{run}{RESET}")
    print(f"{DIM}{m.get('role', '?')} · {m.get('model', '?')} {m.get('effort', '')} · "
          f"{m.get('access', '?')} · {m.get('repo', '?')}{RESET}\n")
    runtime = HOMES / str(m.get("runtimeRunId", run))
    last = 0
    status = None
    while True:
        m = meta(run)
        if m.get("status") != status:
            status = m.get("status")
            print(f"{YELLOW}[status] {status}{RESET}")
        db = runtime / "state.db"
        if db.exists():
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
                rows = con.execute(
                    "select id, role, content, tool_calls, tool_name, timestamp from messages "
                    "where id > ? order by id", (last,)).fetchall()
                con.close()
            except sqlite3.Error:
                rows = []
            for mid, role, content, calls, tool_name, ts in rows:
                last = mid
                try:
                    stamp = time.strftime("%H:%M:%S", time.localtime(float(ts)))
                except (TypeError, ValueError):
                    stamp = time.strftime("%H:%M:%S")
                if role == "assistant":
                    for line in short(content or "", lines=6):
                        print(f"{BOLD}{line}{RESET}")
                    for call in json.loads(calls) if calls else []:
                        name, arg = describe_call(call)
                        first = short(arg, lines=2)
                        print(f"{DIM}{stamp}{RESET} {CYAN}▸ {name}{RESET} {first[0] if first else ''}")
                        for extra in first[1:]:
                            print(f"           {extra}")
                elif role == "tool":
                    for line in short(tool_text(content), lines=3):
                        print(f"{DIM}    {line}{RESET}")
        if status in DONE:
            out = RUNS / run / "final.txt"
            print(f"\n{GREEN if status == 'completed' else RED}{BOLD}[finished: {status}]{RESET}")
            if out and out.exists():
                print(out.read_text()[-4000:])
            print(f"{DIM}Pane stays open. Foreman closes it after reading the result.{RESET}")
            return
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
