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


if __name__ == "__main__":
    unittest.main()
