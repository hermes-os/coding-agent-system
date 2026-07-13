#!/usr/bin/env python3
"""Freeze a Git change, validate structured review, and record exact-head proof."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


SCHEMA_VERSION = 1
STATUS_CONTEXT = "agent-system/autoreview"
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_-]{16,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "stripe-key": re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    "authorization-header": re.compile(
        r"\bauthorization[\"']?\s*:\s*[\"']?\s*(?:bearer|basic)\s+[A-Za-z0-9+/_.~=-]{8,}",
        re.IGNORECASE,
    ),
}
ASSIGNMENT_RE = re.compile(
    r"(?m)^[+ -]?[^+\n]*?\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
    r"\s*[:=]\s*([\"']?)([^\s\"',;]+)"
)
PLACEHOLDERS = ("example", "placeholder", "redacted", "dummy", "process.env", "getenv", "${", "{{")


class ReviewError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(root: Path | None, *args: str, text: bool = True, check: bool = True):
    command = ["git"]
    if root is not None:
        command.extend(["-C", str(root)])
    command.extend(args)
    result = subprocess.run(command, text=text, capture_output=True, check=False)
    if check and result.returncode != 0:
        error = result.stderr if text else result.stderr.decode("utf-8", errors="replace")
        lines = [line.strip() for line in error.splitlines() if line.strip()]
        raise ReviewError(lines[-1][:240] if lines else "Git operation failed")
    return result


def repository_root(explicit: str | None = None) -> Path:
    start = Path(explicit).expanduser().resolve() if explicit else Path.cwd()
    output = git(start, "rev-parse", "--show-toplevel").stdout.strip()
    return Path(output).resolve()


def clean_candidate(root: Path) -> None:
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status.strip():
        raise ReviewError("candidate checkout is dirty; freeze a committed candidate before review")


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise ReviewError(f"unsafe changed path: {value!r}")
    return path


def sensitive_path(value: str) -> bool:
    path = PurePosixPath(value.lower())
    name = path.name
    if name in (".env.example", ".env.sample", ".env.template"):
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in ("auth.json", "credentials.json", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"):
        return True
    if path.suffix in (".pem", ".p12", ".pfx", ".key"):
        return True
    return any(part in ("secrets", "credentials") for part in path.parts)


def secret_findings(text: str) -> list[str]:
    findings = [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    for match in ASSIGNMENT_RE.finditer(text):
        quoted = bool(match.group(2))
        value = match.group(3)
        lowered = value.lower()
        if len(value) < 8 or any(marker in lowered for marker in PLACEHOLDERS):
            continue
        if any(marker in value for marker in ("(", "${", "{{")):
            continue
        if not quoted and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value) and (value.isalpha() or "_" in value or "." in value):
            continue
        classes = sum(
            (
                any(character.islower() for character in value),
                any(character.isupper() for character in value),
                any(character.isdigit() for character in value),
                any(not character.isalnum() for character in value),
            )
        )
        if quoted or classes >= 2:
            findings.append(f"assigned-{match.group(1).lower()}")
    return sorted(set(findings))


def changed_entries(root: Path, base: str, head: str) -> list[dict]:
    raw = git(root, "diff", "--name-status", "-z", "--find-renames", base, head).stdout
    parts = raw.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    entries: list[dict] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if not status:
            continue
        kind = status[0]
        if kind in ("R", "C"):
            if index + 1 >= len(parts):
                raise ReviewError("malformed rename entry from Git")
            old_path, path = parts[index], parts[index + 1]
            index += 2
            safe_relative(old_path)
            safe_relative(path)
            entries.append({"status": status, "old_path": old_path, "path": path})
        else:
            if index >= len(parts):
                raise ReviewError("malformed changed-path entry from Git")
            path = parts[index]
            index += 1
            safe_relative(path)
            entries.append({"status": status, "path": path})
    return entries


def object_bytes(root: Path, revision: str, path: str) -> bytes | None:
    spec = f"{revision}:{path}"
    if git(root, "cat-file", "-e", spec, check=False).returncode != 0:
        return None
    return git(root, "show", spec, text=False).stdout


def fingerprint(base: str, head: str, intent: str, evidence: list[str], patch: bytes) -> str:
    digest = hashlib.sha256()
    for value in (base, head, intent, json.dumps(evidence, sort_keys=True)):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    digest.update(patch)
    return digest.hexdigest()


def remote_slug(root: Path) -> str:
    url = git(root, "remote", "get-url", "origin").stdout.strip()
    match = re.search(r"github\.com(?::|/)([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
    if not match:
        raise ReviewError("origin is not a recognizable GitHub repository")
    return match.group(1).removesuffix(".git")


def repository_label(root: Path) -> str:
    try:
        return remote_slug(root)
    except ReviewError:
        return root.name


def prepare(args: argparse.Namespace) -> int:
    root = repository_root(args.repo)
    clean_candidate(root)
    if not args.intent.strip():
        raise ReviewError("intent is required to freeze review scope")
    scope_secrets = secret_findings(args.intent + "\n" + "\n".join(args.evidence))
    if scope_secrets:
        raise ReviewError("secret-like review context blocked: " + ", ".join(scope_secrets))

    if args.commit:
        head = git(root, "rev-parse", f"{args.commit}^{{commit}}").stdout.strip()
        base_ref = f"{head}^"
        base = git(root, "rev-parse", base_ref).stdout.strip()
        mode = "commit"
    else:
        head = git(root, "rev-parse", f"{args.head}^{{commit}}").stdout.strip()
        base_ref = args.base
        base = git(root, "merge-base", args.base, head).stdout.strip()
        mode = "branch"
    if base == head:
        raise ReviewError("candidate contains no committed changes")

    entries = changed_entries(root, base, head)
    if not entries:
        raise ReviewError("candidate contains no changed files")
    sensitive = sorted(
        path
        for entry in entries
        for path in (entry.get("old_path"), entry["path"])
        if path and sensitive_path(path)
    )
    if sensitive:
        raise ReviewError("sensitive paths cannot enter a review bundle: " + ", ".join(sensitive))

    patch = git(root, "diff", "--binary", "--no-ext-diff", "--find-renames", base, head, text=False).stdout
    if len(patch) > args.max_patch_bytes:
        raise ReviewError(f"patch exceeds bundle limit ({len(patch)} bytes)")
    patch_text = patch.decode("utf-8", errors="replace")
    secrets = secret_findings(patch_text)
    if secrets:
        raise ReviewError("secret-like patch content blocked: " + ", ".join(secrets))

    review_fingerprint = fingerprint(base, head, args.intent.strip(), args.evidence, patch)
    if args.out:
        destination = Path(args.out).expanduser().resolve()
        if destination.exists():
            raise ReviewError(f"bundle destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    else:
        build = Path(tempfile.mkdtemp(prefix=f"agent-autoreview-{review_fingerprint[:12]}-"))
        destination = build
    build.chmod(0o700)

    snapshot_bytes = 0
    snapshots: list[dict] = []
    try:
        for entry in entries:
            path = entry["path"]
            content = object_bytes(root, head, path)
            if content is None:
                continue
            snapshot_bytes += len(content)
            if snapshot_bytes > args.max_snapshot_bytes:
                raise ReviewError(f"source snapshots exceed bundle limit ({snapshot_bytes} bytes)")
            record = {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "binary": b"\0" in content,
            }
            snapshots.append(record)
            if not record["binary"]:
                snapshot_secrets = secret_findings(content.decode("utf-8", errors="replace"))
                if snapshot_secrets:
                    raise ReviewError(
                        f"secret-like source snapshot blocked in {path}: " + ", ".join(snapshot_secrets)
                    )
                output = build / "files" / Path(*safe_relative(path).parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                output.chmod(0o600)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "repository": repository_label(root),
            "mode": mode,
            "base_ref": base_ref,
            "base_sha": base,
            "head_sha": head,
            "fingerprint": review_fingerprint,
            "intent": args.intent.strip(),
            "evidence": args.evidence,
            "changed_files": entries,
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "patch_bytes": len(patch),
            "snapshots": snapshots,
        }
        (build / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (build / "patch.diff").write_bytes(patch)
        template = {
            "schema_version": SCHEMA_VERSION,
            "fingerprint": review_fingerprint,
            "reviewer_provenance": "",
            "verdict": "pass",
            "findings": [],
            "open_questions": [],
            "residual_risk": "",
        }
        (build / "result-template.json").write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        instructions = f"""# Frozen Review Candidate

Review only this bundle for the intent in `manifest.json`. Inspect `patch.diff`
and `files/`; do not infer quality from prior summaries. Verify concrete defects,
classify each as blocker, follow-up, or scope-break, and write `result.json`
matching `result-template.json`.

Each finding requires: `severity` (P0-P3), `classification`, `file`, `line`,
`title`, `impact`, `evidence`, and `correction`. A pass has no findings. Record
the actual reviewer in `reviewer_provenance`; identity is provenance only.

Candidate fingerprint: `{review_fingerprint}`
"""
        (build / "REVIEW.md").write_text(instructions, encoding="utf-8")
        for child in build.iterdir():
            if child.is_file():
                child.chmod(0o600)
        if destination != build:
            build.replace(destination)
    except Exception:
        if build.exists():
            import shutil

            shutil.rmtree(build)
        raise

    print(destination)
    return 0


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"{label} must be a JSON object")
    return value


def load_bundle(path: Path) -> tuple[Path, dict]:
    bundle = path.expanduser().resolve()
    manifest = load_json(bundle / "manifest.json", "bundle manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError("unsupported bundle schema")
    patch_path = bundle / "patch.diff"
    try:
        patch = patch_path.read_bytes()
    except OSError as exc:
        raise ReviewError("bundle patch is missing") from exc
    if hashlib.sha256(patch).hexdigest() != manifest.get("patch_sha256"):
        raise ReviewError("bundle patch hash does not match manifest")
    evidence = manifest.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ReviewError("bundle evidence must be a string list")
    expected = fingerprint(manifest["base_sha"], manifest["head_sha"], manifest["intent"], evidence, patch)
    if expected != manifest.get("fingerprint"):
        raise ReviewError("bundle fingerprint does not match contents")
    for snapshot in manifest.get("snapshots", []):
        if not isinstance(snapshot, dict) or snapshot.get("binary"):
            continue
        path_value = snapshot.get("path")
        if not isinstance(path_value, str):
            raise ReviewError("invalid source snapshot metadata")
        source = bundle / "files" / Path(*safe_relative(path_value).parts)
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise ReviewError(f"source snapshot missing: {path_value}") from exc
        if hashlib.sha256(content).hexdigest() != snapshot.get("sha256"):
            raise ReviewError(f"source snapshot hash mismatch: {path_value}")
    return bundle, manifest


def validate_result(manifest: dict, result: dict) -> str:
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError("unsupported result schema")
    if result.get("fingerprint") != manifest.get("fingerprint"):
        raise ReviewError("result does not match the frozen candidate")
    provenance = result.get("reviewer_provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ReviewError("reviewer_provenance is required")
    verdict = result.get("verdict")
    if verdict not in ("pass", "findings"):
        raise ReviewError("verdict must be pass or findings")
    findings = result.get("findings")
    if not isinstance(findings, list):
        raise ReviewError("findings must be a list")
    if verdict == "pass" and findings:
        raise ReviewError("a passing result cannot contain findings")
    if verdict == "findings" and not findings:
        raise ReviewError("a findings result must contain findings")
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ReviewError(f"finding {index} must be an object")
        if finding.get("severity") not in ("P0", "P1", "P2", "P3"):
            raise ReviewError(f"finding {index} has invalid severity")
        if finding.get("classification") not in ("blocker", "follow-up", "scope-break"):
            raise ReviewError(f"finding {index} has invalid classification")
        path = finding.get("file")
        if not isinstance(path, str):
            raise ReviewError(f"finding {index} requires a file")
        safe_relative(path)
        if not isinstance(finding.get("line"), int) or finding["line"] < 1:
            raise ReviewError(f"finding {index} requires a positive line")
        for field in ("title", "impact", "evidence", "correction"):
            value = finding.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ReviewError(f"finding {index} requires {field}")
    for field in ("open_questions",):
        if not isinstance(result.get(field), list) or not all(isinstance(item, str) for item in result[field]):
            raise ReviewError(f"{field} must be a string list")
    if not isinstance(result.get("residual_risk"), str):
        raise ReviewError("residual_risk must be a string")
    leaked = secret_findings(json.dumps(result))
    if leaked:
        raise ReviewError("secret-like review output blocked: " + ", ".join(leaked))
    return verdict


def receipt_path(root: Path, fingerprint_value: str) -> Path:
    git_dir = Path(git(root, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    return git_dir / "agent-system" / "autoreview" / f"{fingerprint_value}.json"


def validate_command(args: argparse.Namespace, *, quiet: bool = False) -> tuple[str, dict, dict]:
    _, manifest = load_bundle(Path(args.bundle))
    result = load_json(Path(args.result).expanduser().resolve(), "review result")
    verdict = validate_result(manifest, result)
    if getattr(args, "record", False):
        root = repository_root(args.repo)
        actual = git(root, "rev-parse", "HEAD").stdout.strip()
        if actual != manifest["head_sha"]:
            raise ReviewError("cannot record review: checkout no longer matches candidate head")
        receipt = receipt_path(root, manifest["fingerprint"])
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "fingerprint": manifest["fingerprint"],
                    "head_sha": manifest["head_sha"],
                    "verdict": verdict,
                    "validated_at": utc_now(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt.chmod(0o600)
    if not quiet:
        print(json.dumps({"fingerprint": manifest["fingerprint"], "head_sha": manifest["head_sha"], "verdict": verdict}, sort_keys=True))
    return verdict, manifest, result


def validate(args: argparse.Namespace) -> int:
    verdict, _, _ = validate_command(args)
    return 0 if verdict == "pass" else 2


def check(args: argparse.Namespace) -> int:
    _, manifest = load_bundle(Path(args.bundle))
    root = repository_root(args.repo)
    receipt = receipt_path(root, manifest["fingerprint"])
    value = load_json(receipt, "review receipt") if receipt.exists() else {}
    actual = git(root, "rev-parse", "HEAD").stdout.strip()
    valid = (
        value.get("fingerprint") == manifest["fingerprint"]
        and value.get("head_sha") == manifest["head_sha"]
        and value.get("verdict") == "pass"
        and actual == manifest["head_sha"]
    )
    print(json.dumps({"valid": valid, "fingerprint": manifest["fingerprint"], "head_sha": manifest["head_sha"]}, sort_keys=True))
    return 0 if valid else 1


def gh(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["gh", *args], cwd=root, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
        raise ReviewError(lines[-1][:240] if lines else "GitHub operation failed")
    return result


def existing_status(root: Path, manifest: dict) -> dict | None:
    slug = remote_slug(root)
    if slug != manifest["repository"]:
        raise ReviewError("bundle repository does not match the current GitHub checkout")
    result = gh(root, "api", f"repos/{slug}/commits/{manifest['head_sha']}/status")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewError("GitHub returned invalid status data") from exc
    statuses = value.get("statuses", []) if isinstance(value, dict) else []
    return next((item for item in statuses if isinstance(item, dict) and item.get("context") == STATUS_CONTEXT), None)


def status(args: argparse.Namespace) -> int:
    _, manifest = load_bundle(Path(args.bundle))
    root = repository_root(args.repo)
    item = existing_status(root, manifest)
    expected_suffix = manifest["fingerprint"][:12]
    matched = bool(item and expected_suffix in str(item.get("description", "")))
    output = {"matched": matched, "context": STATUS_CONTEXT, "head_sha": manifest["head_sha"]}
    if item:
        output["state"] = item.get("state")
        output["description"] = item.get("description")
    print(json.dumps(output, sort_keys=True))
    return 0 if matched else 1


def publish(args: argparse.Namespace) -> int:
    verdict, manifest, _ = validate_command(args, quiet=True)
    root = repository_root(args.repo)
    state = "success" if verdict == "pass" else "failure"
    description = f"{verdict} {manifest['fingerprint'][:12]}"
    current = existing_status(root, manifest)
    if current and current.get("state") == state and current.get("description") == description:
        print(json.dumps({"published": False, "reason": "already-current", "state": state}, sort_keys=True))
        return 0 if verdict == "pass" else 2
    command = [
        "api",
        "--method",
        "POST",
        f"repos/{manifest['repository']}/statuses/{manifest['head_sha']}",
        "-f",
        f"state={state}",
        "-f",
        f"context={STATUS_CONTEXT}",
        "-f",
        f"description={description}",
    ]
    if args.target_url:
        command.extend(["-f", f"target_url={args.target_url}"])
    gh(root, *command)
    print(json.dumps({"published": True, "state": state, "head_sha": manifest["head_sha"]}, sort_keys=True))
    return 0 if verdict == "pass" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser("prepare")
    target = prepare_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--base")
    target.add_argument("--commit")
    prepare_parser.add_argument("--head", default="HEAD")
    prepare_parser.add_argument("--intent", required=True)
    prepare_parser.add_argument("--evidence", action="append", default=[])
    prepare_parser.add_argument("--out")
    prepare_parser.add_argument("--repo")
    prepare_parser.add_argument("--max-patch-bytes", type=int, default=2_000_000)
    prepare_parser.add_argument("--max-snapshot-bytes", type=int, default=4_000_000)
    prepare_parser.set_defaults(handler=prepare)

    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--bundle", required=True)
    validate_parser.add_argument("--result", required=True)
    validate_parser.add_argument("--repo")
    validate_parser.add_argument("--record", action="store_true")
    validate_parser.set_defaults(handler=validate)

    check_parser = commands.add_parser("check")
    check_parser.add_argument("--bundle", required=True)
    check_parser.add_argument("--repo")
    check_parser.set_defaults(handler=check)

    status_parser = commands.add_parser("status")
    status_parser.add_argument("--bundle", required=True)
    status_parser.add_argument("--repo")
    status_parser.set_defaults(handler=status)

    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--bundle", required=True)
    publish_parser.add_argument("--result", required=True)
    publish_parser.add_argument("--repo")
    publish_parser.add_argument("--target-url")
    publish_parser.set_defaults(handler=publish)
    return root


def main() -> int:
    args = parser().parse_args()
    for field in ("max_patch_bytes", "max_snapshot_bytes"):
        if hasattr(args, field) and getattr(args, field) < 1:
            raise ReviewError(f"{field.replace('_', '-')} must be positive")
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ReviewError) as exc:
        print(f"agent-autoreview: {exc}", file=sys.stderr)
        raise SystemExit(1)
