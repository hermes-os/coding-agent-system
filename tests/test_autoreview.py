import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
AUTOREVIEW = SYSTEM_ROOT / "skills" / "review" / "scripts" / "agent-autoreview.py"


def run(*args, cwd, check=True):
    return subprocess.run(
        [str(AUTOREVIEW), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def load_autoreview_module():
    spec = importlib.util.spec_from_file_location("agent_autoreview_fixture", AUTOREVIEW)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AutoreviewTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[str, str]:
        git(root, "init")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.test")
        git(root, "remote", "add", "origin", "https://github.com/example/review-fixture.git")
        (root / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        git(root, "add", "app.py")
        git(root, "commit", "-m", "initial")
        base = git(root, "rev-parse", "HEAD")
        (root / "app.py").write_text(
            "def value():\n    scope_secrets = secret_findings('intent')\n    return 2\n",
            encoding="utf-8",
        )
        git(root, "add", "app.py")
        git(root, "commit", "-m", "change value")
        return base, git(root, "rev-parse", "HEAD")

    def test_prepare_validate_record_and_check_exact_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, head = self.make_repo(root)
            bundle = root / ".review-bundle"
            prepared = run(
                "prepare",
                "--base",
                base,
                "--intent",
                "Return the updated value",
                "--out",
                str(bundle),
                cwd=root,
            )
            self.assertEqual(Path(prepared.stdout.strip()), bundle.resolve())
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["head_sha"], head)
            self.assertEqual(manifest["repository"], "example/review-fixture")
            self.assertEqual(manifest["changed_files"][0]["path"], "app.py")
            self.assertEqual(
                (bundle / "files" / "app.py").read_text(encoding="utf-8"),
                "def value():\n    scope_secrets = secret_findings('intent')\n    return 2\n",
            )

            result = json.loads((bundle / "result-template.json").read_text(encoding="utf-8"))
            result["reviewer_provenance"] = "independent fixture reviewer"
            result["residual_risk"] = "none observed"
            result_path = bundle / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            validated = run(
                "validate",
                "--bundle",
                str(bundle),
                "--result",
                str(result_path),
                "--record",
                cwd=root,
            )
            self.assertEqual(json.loads(validated.stdout)["verdict"], "pass")
            checked = run("check", "--bundle", str(bundle), cwd=root)
            self.assertTrue(json.loads(checked.stdout)["valid"])

    def test_findings_exit_nonzero_and_secret_like_patch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, _ = self.make_repo(root)
            bundle = root / ".review-bundle"
            run(
                "prepare",
                "--base",
                base,
                "--intent",
                "Return the updated value",
                "--out",
                str(bundle),
                cwd=root,
            )
            result = json.loads((bundle / "result-template.json").read_text(encoding="utf-8"))
            result.update(
                {
                    "reviewer_provenance": "independent fixture reviewer",
                    "verdict": "findings",
                    "findings": [
                        {
                            "severity": "P2",
                            "classification": "blocker",
                            "file": "app.py",
                            "line": 2,
                            "title": "Unexpected value",
                            "impact": "Callers receive the wrong result.",
                            "evidence": "The candidate changes the return value.",
                            "correction": "Return the required value.",
                        }
                    ],
                }
            )
            result_path = bundle / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            findings = run(
                "validate",
                "--bundle",
                str(bundle),
                "--result",
                str(result_path),
                cwd=root,
                check=False,
            )
            self.assertEqual(findings.returncode, 2)

            shutil.rmtree(bundle)
            secret_base = git(root, "rev-parse", "HEAD")
            secret = "".join(("actual", "secret", "value", "123"))
            (root / "config.txt").write_text("SERVICE_API_KEY=" + secret + "\n", encoding="utf-8")
            git(root, "add", "config.txt")
            git(root, "commit", "-m", "add secret fixture")
            blocked = run(
                "prepare",
                "--base",
                secret_base,
                "--intent",
                "Add configuration",
                cwd=root,
                check=False,
            )
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("secret-like patch content blocked", blocked.stderr)
            self.assertNotIn(secret, blocked.stderr)

    def test_authorization_header_credentials_fail_closed(self):
        for scheme_parts in (("Bea", "rer"), ("Ba", "sic")):
            with self.subTest(scheme="".join(scheme_parts)), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.make_repo(root)
                base = git(root, "rev-parse", "HEAD")
                header = "".join(("Author", "ization"))
                scheme = "".join(scheme_parts)
                credential = "".join(("opaque", "review", scheme.lower(), "987654"))
                (root / "request.txt").write_text(
                    f'"{header}": "{scheme} {credential}"\n',
                    encoding="utf-8",
                )
                git(root, "add", "request.txt")
                git(root, "commit", "-m", "add request fixture")
                blocked = run(
                    "prepare",
                    "--base",
                    base,
                    "--intent",
                    "Add request fixture",
                    cwd=root,
                    check=False,
                )
                self.assertEqual(blocked.returncode, 1)
                self.assertIn("secret-like patch content blocked", blocked.stderr)
                self.assertNotIn(credential, blocked.stderr)

    def test_lowercase_and_structured_credentials_fail_closed(self):
        fixtures = (("pass", "word", False), ("API", "_KEY", True))
        for first, second, structured in fixtures:
            with self.subTest(structured=structured), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.make_repo(root)
                base = git(root, "rev-parse", "HEAD")
                key = first + second
                credential = "".join(("opaque", "structured", "value", "24680"))
                value = f'"{key}": "{credential}"\n' if structured else f"{key} = {credential}\n"
                (root / "settings.txt").write_text(value, encoding="utf-8")
                git(root, "add", "settings.txt")
                git(root, "commit", "-m", "add settings fixture")
                blocked = run(
                    "prepare",
                    "--base",
                    base,
                    "--intent",
                    "Add settings fixture",
                    cwd=root,
                    check=False,
                )
                self.assertEqual(blocked.returncode, 1)
                self.assertIn("secret-like patch content blocked", blocked.stderr)
                self.assertNotIn(credential, blocked.stderr)

    def test_bundle_inventory_and_diff_identity_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            base, _ = self.make_repo(root)
            first = Path(temp) / "review-first"
            second = Path(temp) / "review-second"
            run(
                "prepare",
                "--base",
                base,
                "--intent",
                "Return the updated value",
                "--out",
                str(first),
                cwd=root,
            )
            first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            first_patch = (first / "patch.diff").read_bytes()

            git(root, "config", "color.ui", "always")
            git(root, "config", "diff.algorithm", "histogram")
            git(root, "config", "diff.context", "0")
            git(root, "config", "diff.noprefix", "true")
            git(root, "config", "diff.renames", "false")
            git(root, "config", "core.abbrev", "7")
            order_file = root / ".git" / "diff-order"
            order_file.write_text("other.py\napp.py\n", encoding="utf-8")
            attributes_file = root / ".git" / "global-attributes"
            attributes_file.write_text("app.py binary\n", encoding="utf-8")
            git(root, "config", "diff.orderFile", str(order_file))
            git(root, "config", "core.attributesFile", str(attributes_file))
            run(
                "prepare",
                "--base",
                base,
                "--intent",
                "Return the updated value",
                "--out",
                str(second),
                cwd=root,
            )
            second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((second / "patch.diff").read_bytes(), first_patch)
            self.assertEqual(second_manifest["fingerprint"], first_manifest["fingerprint"])

            result = json.loads((first / "result-template.json").read_text(encoding="utf-8"))
            result["reviewer_provenance"] = "independent fixture reviewer"
            result_path = first / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            tampered = {**first_manifest, "snapshots": []}
            (first / "manifest.json").write_text(json.dumps(tampered), encoding="utf-8")
            rejected = run(
                "validate",
                "--bundle",
                str(first),
                "--result",
                str(result_path),
                cwd=root,
                check=False,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("snapshot inventory is incomplete", rejected.stderr)

            (first / "manifest.json").write_text(json.dumps(first_manifest), encoding="utf-8")
            source = first / "files" / "app.py"
            original = source.read_bytes()
            source.write_bytes(original + b"tampered\n")
            rejected = run(
                "validate",
                "--bundle",
                str(first),
                "--result",
                str(result_path),
                cwd=root,
                check=False,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("snapshot size mismatch", rejected.stderr)

            module = load_autoreview_module()
            self.assertNotEqual(
                module.status_context({"fingerprint": "a" * 64}),
                module.status_context({"fingerprint": "b" * 64}),
            )


if __name__ == "__main__":
    unittest.main()
