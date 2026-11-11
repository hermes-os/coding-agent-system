"""Claude Code and Codex skip a skill whose header they cannot read, without a word."""

from pathlib import Path
import re
import unittest


SKILLS = Path(__file__).resolve().parents[1] / "skills"
HEADER = re.compile(r'\A---\nname: (\S+)\ndescription: "([^"\n]+)"\n---\n')


class SkillsTest(unittest.TestCase):
    def test_every_skill_has_a_readable_header_named_after_its_folder(self):
        folders = sorted(path for path in SKILLS.iterdir())
        self.assertTrue(folders)
        for folder in folders:
            with self.subTest(skill=folder.name):
                header = HEADER.match((folder / "SKILL.md").read_text(encoding="utf-8"))
                self.assertIsNotNone(header, "SKILL.md must open with name and a quoted one-line description")
                self.assertEqual(header.group(1), folder.name)


if __name__ == "__main__":
    unittest.main()
