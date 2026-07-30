import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from lib.host_contract import kimi_agent_spec
from lib.kimi_config import edit_kimi_config


SYSTEM_ROOT = Path(__file__).parents[1]
SCRIPT = SYSTEM_ROOT / "skills" / "capabilities" / "scripts" / "agent-capabilities.py"
BUDGETS = {"Stop": 330, "PreToolUse": 600}


class CapabilitiesTests(unittest.TestCase):
    def write_skill(self, root: Path, name: str) -> None:
        skill = root / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Fixture {name}.\n---\n# {name}\n",
            encoding="utf-8",
        )

    def test_reports_scoped_skills_without_environment_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            repo = root / "repo"
            self.write_skill(home / ".agents" / "skills", "global-demo")
            self.write_skill(repo / ".agents" / "skills", "repo-demo")
            (home / ".agents" / "kimi").mkdir(parents=True)
            policy = (SYSTEM_ROOT / "AGENTS.md").read_text(encoding="utf-8")
            (home / ".agents" / "AGENTS.md").write_text(policy, encoding="utf-8")
            (home / ".agents" / "kimi" / "agent.yaml").write_text(
                kimi_agent_spec(policy),
                encoding="utf-8",
            )
            session_guard = home / ".agents" / "kimi" / "session-guard.py"
            session_guard.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            session_guard.chmod(0o755)
            (home / ".kimi").mkdir()
            (home / ".kimi" / "config.toml").write_text(
                edit_kimi_config("", BUDGETS),
                encoding="utf-8",
            )
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            kimi = local_bin / "kimi"
            kimi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            kimi.chmod(0o755)
            launcher = local_bin / "agent-kimi"
            launcher.write_text(
                "#!/bin/sh\nexit 0\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            result = subprocess.run(
                [str(SCRIPT), "--home", str(home), "--repo", str(repo), "--json"],
                env={
                    **os.environ,
                    "PATH": f"{local_bin}:{os.environ.get('PATH', '')}",
                    "DO_NOT_PRINT_THIS_SECRET": "sensitive-value",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("sensitive-value", result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual([skill["name"] for skill in report["globalSkills"]], ["global-demo"])
            self.assertEqual([skill["name"] for skill in report["repositorySkills"]], ["repo-demo"])
            self.assertTrue(report["hosts"]["kimi"])
            self.assertEqual(report["tools"]["agents"]["kimi"], str(kimi))

            launcher.chmod(0o644)
            unavailable = subprocess.run(
                [str(SCRIPT), "--home", str(home), "--json"],
                env={**os.environ, "PATH": f"{local_bin}:{os.environ.get('PATH', '')}"},
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertFalse(json.loads(unavailable.stdout)["hosts"]["kimi"])


if __name__ == "__main__":
    unittest.main()
