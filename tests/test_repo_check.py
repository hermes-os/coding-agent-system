from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
REPO_CHECK = SYSTEM_ROOT / "bin" / "agent-repo-check"
POINTER = "READ ~/.agents/AGENTS.md BEFORE ANYTHING (skip if missing).\n"


class RepositoryCheckTests(unittest.TestCase):
    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text(POINTER + "\n# Fixture\n", encoding="utf-8")
        (root / "CLAUDE.md").symlink_to("AGENTS.md")

    def run_check(self, root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [str(REPO_CHECK), "--repo", str(root), "--strict", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(result.stdout)

    def commit_index(self, root: Path, message: str = "fixture") -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.com",
                "commit",
                "-qm",
                message,
            ],
            check=True,
        )

    def test_valid_repository_contract_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            plan = root / "docs" / "plan" / "fixture.md"
            plan.parent.mkdir(parents=True)
            sections = "\n".join(f"## {name}\n\nFixture.\n" for name in (
                "Status",
                "Problem",
                "Goals",
                "Non-Goals",
                "Decisions",
                "Milestones",
                "Verification",
                "Open Questions",
            ))
            plan.write_text(
                "---\nsummary: Fixture plan.\nread_when:\n  - Testing repository checks.\n---\n\n"
                "# Fixture\n\n"
                + sections,
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["warnings"], [])

    def test_rejects_duplicate_instructions_secrets_bad_plans_and_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            (root / "CODEX.md").write_text("duplicate policy\n", encoding="utf-8")
            (root / ".env.production").write_text("SECRET=value\n", encoding="utf-8")
            plan = root / "docs" / "plan" / "broken.md"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                "---\nsummary: Broken plan.\nread_when:\n  - Testing failures.\n---\n"
                "# Broken\n\n## Status\n\nActive.\n",
                encoding="utf-8",
            )
            skill = root / ".agents" / "skills" / "broken"
            hook = skill / "hooks" / "check.sh"
            hook.parent.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: broken\ndescription: Broken fixture.\n---\n# Broken\n",
                encoding="utf-8",
            )
            hook.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            hook.chmod(0o755)
            (skill / "hooks.json").write_text(
                json.dumps({"version": 2, "events": {"Stop": [{"command": ["hooks/check.sh"]}]}}),
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(root), "add", "-Af"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            joined = "\n".join(report["errors"])
            self.assertIn("host-specific instruction", joined)
            self.assertIn("credential-shaped", joined)
            self.assertIn("missing plan sections", joined)
            self.assertIn("repository skill audit failed", joined)

    def test_product_system_json_does_not_bypass_global_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "system.json").write_text("{}\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Product\n", encoding="utf-8")
            (root / "CLAUDE.md").symlink_to("AGENTS.md")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("canonical global pointer" in error for error in report["errors"]))

    def test_rejects_managed_root_and_nested_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.init_repo(root)
            external_docs = base / "external-docs"
            external_docs.mkdir()
            (external_docs / "outside.md").write_text("outside\n", encoding="utf-8")
            (root / "docs").symlink_to(external_docs, target_is_directory=True)
            agents = root / ".agents"
            agents.mkdir()
            (agents / "skills").symlink_to(base, target_is_directory=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            joined = "\n".join(report["errors"])
            self.assertIn("documentation path must not be a symlink", joined)
            self.assertIn("repository skill path must not be a symlink", joined)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.init_repo(root)
            skill = root / ".agents" / "skills" / "fixture"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: fixture\ndescription: Fixture skill.\n---\n",
                encoding="utf-8",
            )
            (skill / "references").symlink_to(base, target_is_directory=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("repository skill path" in error for error in report["errors"]))

    def test_rejects_dangling_document_and_skill_root_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            self.init_repo(root)
            (root / "docs").symlink_to(base / "missing-docs", target_is_directory=True)
            (root / ".agents").symlink_to(base / "missing-agents", target_is_directory=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            joined = "\n".join(report["errors"])
            self.assertIn("documentation path must not be a symlink", joined)
            self.assertIn("repository skill path must not be a symlink", joined)

    def test_deleted_tracked_credential_path_still_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            secret = root / ".env.production"
            secret.write_text("SECRET=value\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-Af"], check=True)
            secret.unlink()
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                any("tracked credential-shaped file: .env.production" in error for error in report["errors"])
            )

    def test_assistant_workspace_policy_allows_only_governed_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "kind": "assistant-workspace",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "-A"],
                check=True,
            )
            self.commit_index(root, "workspace without memory policy")

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "assistant-workspace requires tracked MEMORY_POLICY.md",
                report["errors"],
            )

            (root / "MEMORY_POLICY.md").write_text(
                "# Memory Policy\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(root), "add", "MEMORY_POLICY.md"],
                check=True,
            )
            self.commit_index(root, "add memory policy")
            result, report = self.run_check(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["repositoryKind"], "assistant-workspace")

            journal = root / "docs" / "journals" / "session.md"
            journal.parent.mkdir(parents=True)
            journal.write_text("Legacy session journal.\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "docs/journals/session.md"],
                check=True,
            )
            secret = root / ".env.production"
            secret.write_text("SECRET=value\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-f", ".env.production"], check=True)
            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "legacy persistent context path: docs/journals/session.md",
                report["errors"],
            )
            self.assertIn(
                "tracked credential-shaped file: .env.production",
                report["errors"],
            )

    def test_untracked_repository_policy_cannot_bypass_memory_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text(
                "# Memory Policy\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(root), "add", "-A"],
                check=True,
            )
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "repository policy must be tracked: .agents/repository.json",
                report["errors"],
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_staged_only_workspace_declaration_cannot_authorize_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "repository HEAD must resolve to a commit",
                report["errors"],
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_uncommitted_repository_policy_replacement_cannot_authorize_memory(self):
        for staged in (False, True):
            with self.subTest(staged=staged), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(
                    '{"schemaVersion": 999, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
                (root / "MEMORY_POLICY.md").write_text(
                    "# Memory Policy\n",
                    encoding="utf-8",
                )
                subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
                self.commit_index(root, "invalid workspace policy")
                policy.write_text(
                    '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                if staged:
                    subprocess.run(
                        ["git", "-C", str(root), "add", ".agents/repository.json"],
                        check=True,
                    )

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "repository policy must match its committed contents: "
                    ".agents/repository.json",
                    report["errors"],
                )
                self.assertIn(
                    "legacy persistent context path: MEMORY.md",
                    report["errors"],
                )

    def test_git_replacement_ref_cannot_authorize_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "base")

            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            tree = subprocess.run(
                ["git", "-C", str(root), "write-tree"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            replacement = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.com",
                    "commit-tree",
                    tree,
                    "-p",
                    "HEAD",
                    "-m",
                    "replacement",
                ],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(root), "replace", "HEAD", replacement],
                check=True,
            )
            replaced_paths = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-tree",
                    "--name-only",
                    "HEAD",
                    "--",
                    ".agents/repository.json",
                    "MEMORY_POLICY.md",
                    "MEMORY.md",
                ],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.splitlines()
            true_paths = subprocess.run(
                [
                    "git",
                    "--no-replace-objects",
                    "-C",
                    str(root),
                    "ls-tree",
                    "--name-only",
                    "HEAD",
                    "--",
                    ".agents/repository.json",
                    "MEMORY_POLICY.md",
                    "MEMORY.md",
                ],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.splitlines()
            self.assertEqual(
                replaced_paths,
                [".agents/repository.json", "MEMORY.md", "MEMORY_POLICY.md"],
            )
            self.assertEqual(true_paths, [])

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "repository policy must be committed: .agents/repository.json",
                report["errors"],
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_tree_valued_head_cannot_authorize_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            tree = subprocess.run(
                ["git", "-C", str(root), "write-tree"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(root), "update-ref", "refs/tags/treehead", tree],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/tags/treehead"],
                check=True,
            )

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "repository HEAD must resolve to a commit",
                report["errors"],
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_repository_policy_rejects_duplicate_keys(self):
        policies = (
            '{"schemaVersion": 1, "kind": "code", "kind": "assistant-workspace"}\n',
            '{"schemaVersion": 999, "schemaVersion": 1, '
            '"kind": "assistant-workspace"}\n',
        )
        for policy_text in policies:
            with self.subTest(policy=policy_text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(policy_text, encoding="utf-8")
                (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
                (root / "MEMORY_POLICY.md").write_text(
                    "# Memory Policy\n",
                    encoding="utf-8",
                )
                subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
                self.commit_index(root, "duplicate policy key")

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    any("duplicate key" in error for error in report["errors"])
                )
                self.assertIn(
                    "legacy persistent context path: MEMORY.md",
                    report["errors"],
                )

    def test_repository_policy_requires_integer_schema_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": true, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "boolean schema")

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                any("unsupported repository policy schema" in error for error in report["errors"])
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_invalid_utf8_repository_policy_returns_json_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_bytes(b"\xff\xfe")
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "invalid encoding")

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["repositoryKind"], "code")
            self.assertTrue(
                any("invalid repository policy" in error for error in report["errors"])
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_memory_policy_must_be_a_tracked_regular_file(self):
        for gitlink in (False, True):
            with self.subTest(gitlink=gitlink), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(
                    '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
                if gitlink:
                    memory_policy = root / "MEMORY_POLICY.md"
                    memory_policy.mkdir()
                    subprocess.run(["git", "init", "-q", str(memory_policy)], check=True)
                    (memory_policy / "README.md").write_text("Fixture.\n", encoding="utf-8")
                    subprocess.run(
                        ["git", "-C", str(memory_policy), "add", "README.md"],
                        check=True,
                    )
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(memory_policy),
                            "-c",
                            "user.name=Fixture",
                            "-c",
                            "user.email=fixture@example.com",
                            "commit",
                            "-qm",
                            "fixture",
                        ],
                        check=True,
                    )
                else:
                    (root / "outside-policy.md").write_text("External.\n", encoding="utf-8")
                    (root / "MEMORY_POLICY.md").symlink_to("outside-policy.md")
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "add",
                        ".agents/repository.json",
                        "MEMORY.md",
                        "MEMORY_POLICY.md",
                    ],
                    capture_output=True,
                    check=True,
                    text=True,
                )
                self.commit_index(root, "non-regular memory policy")

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    any(
                        "assistant-workspace memory policy must be a committed regular file: "
                        "MEMORY_POLICY.md" in error
                        for error in report["errors"]
                    )
                )
                self.assertIn(
                    "legacy persistent context path: MEMORY.md",
                    report["errors"],
                )

    def test_memory_policy_must_be_valid_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_bytes(b"\xff\xfe")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "invalid memory policy encoding")

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                any("invalid MEMORY_POLICY.md" in error for error in report["errors"])
            )
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_governed_memory_files_must_match_committed_bytes(self):
        for path, staged in (
            ("MEMORY_POLICY.md", False),
            ("MEMORY_POLICY.md", True),
            ("MEMORY.md", False),
            ("MEMORY.md", True),
        ):
            with (
                self.subTest(path=path, staged=staged),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(
                    '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
                (root / "MEMORY_POLICY.md").write_text(
                    "# Memory Policy\n",
                    encoding="utf-8",
                )
                subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
                self.commit_index(root, "valid workspace")
                (root / path).write_text("Changed.\n", encoding="utf-8")
                if staged:
                    subprocess.run(["git", "-C", str(root), "add", path], check=True)

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    any("must match its committed contents" in error for error in report["errors"])
                )
                self.assertIn(
                    "legacy persistent context path: MEMORY.md",
                    report["errors"],
                )

    def test_staged_memory_deletion_cannot_authorize_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text("Curated memory.\n", encoding="utf-8")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "valid workspace")
            subprocess.run(
                ["git", "-C", str(root), "rm", "-q", "MEMORY.md"],
                check=True,
            )

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "assistant-workspace memory must match its committed contents: MEMORY.md",
                report["errors"],
            )

    def test_staged_workspace_declaration_deletion_cannot_pass_as_code(self):
        for governed_memory in (False, True):
            with (
                self.subTest(governed_memory=governed_memory),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(
                    '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                (root / "MEMORY_POLICY.md").write_text(
                    "# Memory Policy\n",
                    encoding="utf-8",
                )
                governed_paths = [".agents/repository.json", "MEMORY_POLICY.md"]
                if governed_memory:
                    (root / "MEMORY.md").write_text(
                        "Curated memory.\n",
                        encoding="utf-8",
                    )
                    governed_paths.append("MEMORY.md")
                subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
                self.commit_index(root, "valid workspace")
                subprocess.run(
                    ["git", "-C", str(root), "rm", "-q", *governed_paths],
                    check=True,
                )

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "repository policy must match its committed contents: "
                    ".agents/repository.json",
                    report["errors"],
                )

    def test_governed_file_modes_must_match_committed_state(self):
        governed_paths = (".agents/repository.json", "MEMORY_POLICY.md", "MEMORY.md")
        for path in governed_paths:
            for committed_mode in (0o644, 0o755):
                with (
                    self.subTest(path=path, committed_mode=oct(committed_mode)),
                    tempfile.TemporaryDirectory() as temp,
                ):
                    root = Path(temp)
                    self.init_repo(root)
                    policy = root / ".agents" / "repository.json"
                    policy.parent.mkdir(parents=True)
                    policy.write_text(
                        '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                        encoding="utf-8",
                    )
                    (root / "MEMORY_POLICY.md").write_text(
                        "# Memory Policy\n",
                        encoding="utf-8",
                    )
                    (root / "MEMORY.md").write_text(
                        "Curated memory.\n",
                        encoding="utf-8",
                    )
                    for governed_path in governed_paths:
                        (root / governed_path).chmod(committed_mode)
                    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
                    self.commit_index(root, "valid workspace")
                    changed_mode = 0o755 if committed_mode == 0o644 else 0o654
                    (root / path).chmod(changed_mode)

                    result, report = self.run_check(root)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(
                        any(
                            "mode must match its committed contents" in error
                            for error in report["errors"]
                        )
                    )

    def test_workspace_memory_must_be_valid_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.init_repo(root)
            policy = root / ".agents" / "repository.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_bytes(b"\xff\xfe")
            (root / "MEMORY_POLICY.md").write_text("# Memory Policy\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            self.commit_index(root, "invalid memory encoding")

            result, report = self.run_check(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any("invalid MEMORY.md" in error for error in report["errors"]))
            self.assertIn(
                "legacy persistent context path: MEMORY.md",
                report["errors"],
            )

    def test_workspace_memory_must_be_a_committed_regular_file(self):
        for gitlink in (False, True):
            with self.subTest(gitlink=gitlink), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.init_repo(root)
                policy = root / ".agents" / "repository.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(
                    '{"schemaVersion": 1, "kind": "assistant-workspace"}\n',
                    encoding="utf-8",
                )
                (root / "MEMORY_POLICY.md").write_text(
                    "# Memory Policy\n",
                    encoding="utf-8",
                )
                if gitlink:
                    memory = root / "MEMORY.md"
                    memory.mkdir()
                    subprocess.run(["git", "init", "-q", str(memory)], check=True)
                    (memory / "README.md").write_text("Fixture.\n", encoding="utf-8")
                    subprocess.run(
                        ["git", "-C", str(memory), "add", "README.md"],
                        check=True,
                    )
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(memory),
                            "-c",
                            "user.name=Fixture",
                            "-c",
                            "user.email=fixture@example.com",
                            "commit",
                            "-qm",
                            "fixture",
                        ],
                        check=True,
                    )
                else:
                    (root / "outside-memory.md").write_text("External.\n", encoding="utf-8")
                    (root / "MEMORY.md").symlink_to("outside-memory.md")
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "add",
                        ".agents/repository.json",
                        "MEMORY_POLICY.md",
                        "MEMORY.md",
                    ],
                    capture_output=True,
                    check=True,
                    text=True,
                )
                self.commit_index(root, "non-regular memory")

                result, report = self.run_check(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    any(
                        "assistant-workspace memory must be a committed regular file: "
                        "MEMORY.md" in error
                        for error in report["errors"]
                    )
                )
                self.assertIn(
                    "legacy persistent context path: MEMORY.md",
                    report["errors"],
                )


if __name__ == "__main__":
    unittest.main()
