import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "capabilities" / "scripts" / "agent-capabilities.py"


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
            result = subprocess.run(
                [str(SCRIPT), "--home", str(home), "--repo", str(repo), "--json"],
                env={**os.environ, "DO_NOT_PRINT_THIS_SECRET": "sensitive-value"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("sensitive-value", result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual([skill["name"] for skill in report["globalSkills"]], ["global-demo"])
            self.assertEqual([skill["name"] for skill in report["repositorySkills"]], ["repo-demo"])


if __name__ == "__main__":
    unittest.main()
