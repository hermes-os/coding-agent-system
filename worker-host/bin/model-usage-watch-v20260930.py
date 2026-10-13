#!/usr/bin/env python3
"""Model usage watch: read both subscription windows, publish the live model
routing for the Ashwren coordinator, resume limit-killed workers, and wake the
coordinator when anything changes.

Stdout is one status line per tick (saved locally by the scheduler).
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

PROFILE = Path("/home/hermes/.hermes/profiles/cal")
os.environ.setdefault("HERMES_HOME", str(PROFILE))
sys.path.insert(0, "/home/hermes/.hermes/hermes-agent")

WORKSPACE = PROFILE / "workspace"
REPO_WORKER = WORKSPACE / "scripts/repo-worker"
ROUTING_PATH = WORKSPACE / "state/model-routing-live.json"
STATE_DIR = WORKSPACE / "state/model-usage-watch"
WORKER_HOMES = Path("/var/lib/agent-worker/.hermes-worker")
RUN_STREAMS = Path("/var/lib/agent-worker/.local/state/agent-workers/runs")
COORDINATOR_JOB = "e43229262cb4"
CHICAGO = ZoneInfo("America/Chicago")

# Codex answered "You've hit your usage limit ... try again at Nov 1st" at
# 2026-10-02 13:44 CDT, so the OpenAI window closed early.
OPENAI_EXPIRES = dt.datetime(2026, 10, 2, 13, 44, tzinfo=CHICAGO)

CLOSED_AT = 99.0          # percent used at which a window counts as closed
RESUME_LOOKBACK = dt.timedelta(hours=36)
MAX_RESUMES_PER_TICK = 3
MAX_RESUME_HOPS = 6
RESUME_COOLDOWN = dt.timedelta(minutes=15)
STALE_ACTIVITY_SECONDS = 1800

LIMIT_SIGNAL = re.compile(
    r"\b429\b|rate[_ ]limit|hit your (?:session |usage |weekly )?limit|usage limit|"
    r"session limit|overloaded_error|\b529\b|usage_limit_reached",
    re.IGNORECASE,
)
FALLBACK_LINE = re.compile(r"^(\S+ \S+) .*Fallback activated: (\S+) \u2192 (\S+) \((\S+)\)")

RESUME_MESSAGE = (
    "Resume after a provider usage-limit interruption. Your worktree and session are intact. "
    "Continue your original task from where you stopped, to its original success criteria. "
    "Do not redo finished work. Keep heavy test runs to one at a time."
)


def route(model, effort):
    return {"agent": "hermes", "model": model, "effort": effort}


# Owner order 2026-10-07: Sonnet 5.5 xhigh builds and authors, Opus 5.5 medium
# takes tough coding, Opus 5.5 high reviews and edits. No usage-burn targets.
# Owner order 2026-10-08: review-fix rounds run on the Opus medium fixer, reviews
# on Opus high, and a review's NIT findings go to a scoped Sonnet medium pass.
SONNET = route("claude-sonnet-5-5", "xhigh")
SONNET_NITS = route("claude-sonnet-5-5", "medium")
OPUS_TOUGH = route("claude-opus-5.5", "medium")
OPUS_REVIEW = route("claude-opus-5.5", "high")
HOLD = None
KINDS = (
    "implementation", "tough_implementation", "guide_authoring",
    "professor_review", "code_review", "nit_cleanup",
)


def decide(anthropic):
    """Pick the model per work kind. Unknown usage counts as closed so no lane
    launches blind; a closed window holds work rather than substituting a weaker model."""
    if anthropic.get("open") is not True:
        return "hold-anthropic-closed", {kind: HOLD for kind in KINDS}
    return "owner-plan", {
        "implementation": SONNET,
        "tough_implementation": OPUS_TOUGH,
        "guide_authoring": SONNET,
        "professor_review": OPUS_REVIEW,
        "code_review": OPUS_REVIEW,
        "nit_cleanup": SONNET_NITS,
    }


def read_usage():
    from agent.account_usage import fetch_account_usage

    def windows(provider):
        snap = fetch_account_usage(provider)
        if snap is None or getattr(snap, "unavailable_reason", None):
            return None, ()
        return snap, tuple(snap.windows)

    anth_snap, anth_windows = windows("anthropic")
    oai_snap, oai_windows = windows("openai-codex")
    anthropic = {"open": None}
    if anth_snap is not None:
        by = {w.label.lower(): w for w in anth_windows}
        session, week = by.get("current session"), by.get("current week")
        if session is not None and week is not None:
            anthropic = {
                "open": session.used_percent < CLOSED_AT and week.used_percent < CLOSED_AT,
                "session_used": session.used_percent,
                "session_reset": session.reset_at,
                "week_used": week.used_percent,
                "week_reset": week.reset_at,
            }
    openai = {"open": None}
    if oai_snap is not None and oai_windows:
        worst = max(oai_windows, key=lambda w: w.used_percent)
        banked = 0
        for line in getattr(oai_snap, "details", ()) or ():
            found = re.search(r"You have (\d+) reset", line)
            if found:
                banked = int(found.group(1))
        openai = {
            "open": worst.used_percent < CLOSED_AT,
            "used": worst.used_percent,
            "reset": worst.reset_at,
            "banked_resets": banked,
            "windows": {w.label: w.used_percent for w in oai_windows},
        }
    return anthropic, openai


def hourly_rate(history, key, reset_at):
    """Percent-per-hour over the last hour within the current window, or None."""
    marker = reset_at.isoformat() if reset_at else None
    points = [
        (dt.datetime.fromisoformat(h["ts"]), h[key])
        for h in history[-30:]
        if h.get(key) is not None and h.get(key + "_reset") == marker
    ]
    if len(points) < 2:
        return None
    cutoff = points[-1][0] - dt.timedelta(minutes=60)
    window = [p for p in points if p[0] >= cutoff]
    (t0, v0), (t1, v1) = window[0], window[-1]
    hours = (t1 - t0).total_seconds() / 3600
    if hours < 0.15:
        return None
    return round(max(0.0, (v1 - v0) / hours), 2)


def list_runs():
    result = subprocess.run(
        [str(REPO_WORKER), "--list"], capture_output=True, text=True, timeout=180, cwd=WORKSPACE,
    )
    if result.returncode:
        raise RuntimeError("repo-worker --list failed: " + result.stderr.strip()[:200])
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else data.get("runs", [])


def sudo_read(path, *, tail_bytes=None, offset=None):
    if offset is not None:
        command = ["sudo", "-n", "tail", "-c", f"+{offset + 1}", str(path)]
    else:
        command = ["sudo", "-n", "tail", "-c", str(tail_bytes or 20000), str(path)]
    result = subprocess.run(command, capture_output=True, timeout=30)
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""


def sudo_size(path):
    result = subprocess.run(["sudo", "-n", "stat", "-c", "%s", str(path)], capture_output=True, text=True, timeout=15)
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else None


def parse_time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def limit_killed(run):
    """True when the run's own evidence shows a provider usage limit ended it."""
    if LIMIT_SIGNAL.search(str(run.get("failureDetail") or "")):
        return True
    texts = [sudo_read(RUN_STREAMS / run["runId"] / "stream.log", tail_bytes=8000)]
    if run.get("agent") == "hermes":
        home = WORKER_HOMES / (run.get("runtimeRunId") or run["runId"])
        texts.append(sudo_read(home / "logs/errors.log", tail_bytes=12000))
    return any(LIMIT_SIGNAL.search(text) for text in texts)


def resume_hops(run, by_id):
    hops, current = 0, run
    while current and current.get("resumedFrom"):
        hops += 1
        current = by_id.get(current["resumedFrom"])
    return hops


def resumable_now(run, anthropic, openai, now):
    anth_open = anthropic.get("open") is True
    oai_open = openai.get("open") is True and now < OPENAI_EXPIRES
    if run.get("agent") == "claude":
        return anth_open
    if run.get("agent") == "codex":
        return oai_open
    if run.get("access") == "read":
        return anth_open or oai_open
    return True


def find_resumable(runs, anthropic, openai, now, ledger):
    by_id = {r["runId"]: r for r in runs}
    superseded = {r.get("resumedFrom") for r in runs if r.get("resumedFrom")}
    candidates, waiting = [], []
    for run in runs:
        if run.get("status") != "failed" or run["runId"] in superseded:
            continue
        if run["runId"] in ledger["resumed"] or run["runId"] in ledger["not_limit"]:
            continue
        created = parse_time(run.get("createdAt"))
        if created is None or now - created > RESUME_LOOKBACK:
            continue
        if resume_hops(run, by_id) >= MAX_RESUME_HOPS:
            continue
        failed_at = parse_time(run.get("updatedAt")) or created
        if run.get("resumedFrom") and now - failed_at < RESUME_COOLDOWN:
            # A resume that died again at once waits, so an exhausted chain cannot spin.
            continue
        if not limit_killed(run):
            ledger["not_limit"].append(run["runId"])
            continue
        (candidates if resumable_now(run, anthropic, openai, now) else waiting).append(run)
    candidates.sort(key=lambda r: r.get("createdAt") or "")
    return candidates, waiting


def resume(run):
    result = subprocess.run(
        [str(REPO_WORKER), "--resume-run", run["runId"], "--task", RESUME_MESSAGE],
        capture_output=True, text=True, timeout=240, cwd=WORKSPACE,
    )
    if result.returncode:
        return None, (result.stderr or result.stdout).strip()[-300:]
    try:
        return json.loads(result.stdout).get("runId"), None
    except ValueError:
        return None, result.stdout.strip()[-300:]


def scan_fallbacks(runs, ledger):
    """New 'Fallback activated' lines from running Hermes workers since the last tick."""
    found = []
    for run in runs:
        if run.get("status") != "running" or not run.get("active") or run.get("agent") != "hermes":
            continue
        home = run.get("runtimeRunId") or run["runId"]
        log = WORKER_HOMES / home / "logs/agent.log"
        size = sudo_size(log)
        if size is None:
            continue
        start = ledger["log_offsets"].get(home)
        if start is None or start > size:
            start = max(0, size - 400_000)
        if size > start:
            for line in sudo_read(log, offset=start).splitlines():
                match = FALLBACK_LINE.match(line)
                if match:
                    found.append({
                        "runId": run["runId"], "role": (run.get("role") or "")[:80],
                        "at": match.group(1), "from": match.group(2),
                        "to": match.group(3), "provider": match.group(4),
                    })
        ledger["log_offsets"][home] = size
    return found


def stale_runs(runs, ledger, now):
    """Active Hermes runs whose own agent log has been silent too long.

    The broker's activity age only moves on stream events, which a long
    single-turn worker emits rarely, so the log's modification time is the signal."""
    stale = []
    for run in runs:
        if run.get("status") != "running" or not run.get("active") or run.get("agent") != "hermes":
            continue
        if run["runId"] in ledger["stale_reported"]:
            continue
        log = WORKER_HOMES / (run.get("runtimeRunId") or run["runId"]) / "logs/agent.log"
        result = subprocess.run(["sudo", "-n", "stat", "-c", "%Y", str(log)], capture_output=True, text=True, timeout=15)
        if result.returncode or not result.stdout.strip().isdigit():
            continue
        idle = now.timestamp() - int(result.stdout.strip())
        if idle > STALE_ACTIVITY_SECONDS:
            stale.append({"runId": run["runId"], "role": (run.get("role") or "")[:80], "idleMinutes": int(idle // 60)})
            ledger["stale_reported"].append(run["runId"])
    return stale


def maybe_redeem_openai(openai, now, dry_run):
    if dry_run or now >= OPENAI_EXPIRES or openai.get("open") is not False or not openai.get("banked_resets"):
        return None
    from agent.account_usage import redeem_codex_reset_credit

    outcome = redeem_codex_reset_credit()
    return {"status": outcome.status, "message": outcome.message[:200]}


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_history(path, limit=200):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def wake_coordinator():
    # trigger_job force-resumes a paused job; a paused coordinator stays paused.
    from cron.jobs import get_job, trigger_job

    if (get_job(COORDINATOR_JOB) or {}).get("enabled"):
        trigger_job(COORDINATOR_JOB)


def label(plan_route):
    return "HOLD" if plan_route is None else f"{plan_route['model']}/{plan_route['effort']}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="observe only: no resume, redeem, or wake")
    args = parser.parse_args(argv)
    now = dt.datetime.now(tz=CHICAGO)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ledger = load_json(STATE_DIR / "ledger.json", {})
    for key, empty in (("resumed", {}), ("not_limit", []), ("log_offsets", {}), ("stale_reported", [])):
        ledger.setdefault(key, empty)
    history_path = STATE_DIR / "usage-history.jsonl"

    anthropic, openai = read_usage()
    point = {
        "ts": now.isoformat(),
        "anth_session": anthropic.get("session_used"),
        "anth_session_reset": anthropic["session_reset"].isoformat() if anthropic.get("session_reset") else None,
        "anth_week": anthropic.get("week_used"),
        "oai_used": openai.get("used"),
        "oai_used_reset": openai["reset"].isoformat() if openai.get("reset") else None,
    }
    if not args.dry_run:
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(point) + "\n")
    history = read_history(history_path)
    phase, plan = decide(anthropic)
    previous = load_json(ROUTING_PATH, {})
    events = []

    plan_labels = {kind: label(r) for kind, r in plan.items()}
    if previous.get("planLabels") != plan_labels or previous.get("phase") != phase:
        events.append({"type": "routing-change", "phase": phase, "plan": plan_labels, "was": previous.get("planLabels")})

    runs = list_runs()
    candidates, waiting = find_resumable(runs, anthropic, openai, now, ledger)
    resumed = []
    for run in candidates[:MAX_RESUMES_PER_TICK]:
        if args.dry_run:
            resumed.append({"runId": run["runId"], "newRunId": "(dry-run)", "role": (run.get("role") or "")[:80]})
            continue
        new_id, error = resume(run)
        if new_id:
            ledger["resumed"][run["runId"]] = new_id
            resumed.append({"runId": run["runId"], "newRunId": new_id, "role": (run.get("role") or "")[:80]})
        else:
            events.append({"type": "resume-failed", "runId": run["runId"], "error": error})
        time.sleep(8)
    if resumed:
        events.append({"type": "resumed", "runs": resumed})
    fallbacks = [] if args.dry_run else scan_fallbacks(runs, ledger)
    if fallbacks:
        events.append({"type": "fallback-activated", "switches": fallbacks})
    stale = [] if args.dry_run else stale_runs(runs, ledger, now)
    if stale:
        events.append({"type": "stale-workers", "runs": stale})
    redeemed = maybe_redeem_openai(openai, now, args.dry_run)
    if redeemed:
        events.append({"type": "openai-reset-redeemed", **redeemed})

    running = [r for r in runs if r.get("status") == "running" and r.get("active")]
    routing = {
        "updatedAt": now.isoformat(),
        "phase": phase,
        "plan": plan,
        "planLabels": plan_labels,
        "anthropic": {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in anthropic.items()},
        "openai": {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in openai.items()},
        "runningWorkers": len(running),
        "waitingForWindow": [{"runId": r["runId"], "role": (r.get("role") or "")[:80]} for r in waiting],
        "deadlines": {
            "openaiExpires": OPENAI_EXPIRES.isoformat(),
        },
        "recentEvents": ([{"at": now.isoformat(), **e} for e in events] + previous.get("recentEvents", []))[:15],
    }
    if not args.dry_run:
        write_json(ROUTING_PATH, routing)
        write_json(STATE_DIR / "ledger.json", ledger)
        if events:
            with (STATE_DIR / "events.jsonl").open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps({"at": now.isoformat(), **event}, default=str) + "\n")
            wake_coordinator()
    summary = (
        f"{now:%H:%M} {phase} anth={anthropic.get('session_used')}%/{anthropic.get('week_used')}%wk "
        f"oai={openai.get('used')}% running={len(running)} resumed={len(resumed)} "
        f"waiting={len(waiting)} fallbacks={len(fallbacks)} events={len(events)} "
        f"impl={plan_labels['implementation']} tough={plan_labels['tough_implementation']} "
        f"author={plan_labels['guide_authoring']} "
        f"prof={plan_labels['professor_review']} code={plan_labels['code_review']}"
    )
    if args.dry_run:
        print(json.dumps(routing, indent=1, default=str)[:4000])
    print(summary)


if __name__ == "__main__":
    main()
