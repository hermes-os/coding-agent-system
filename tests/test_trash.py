import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
TRASH = SYSTEM_ROOT / "bin" / "agent-trash"


class TrashTests(unittest.TestCase):
    def test_moves_file_to_platform_trash_and_refuses_home(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            work = Path(temp) / "work"
            home.mkdir()
            work.mkdir()
            source = work / "obsolete.txt"
            source.write_text("recoverable\n", encoding="utf-8")
            env = {**os.environ, "HOME": str(home)}
            moved = subprocess.run(
                [str(TRASH), str(source)],
                cwd=work,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("trashed", moved.stdout)
            self.assertFalse(source.exists())
            trash = home / ".Trash" if sys.platform == "darwin" else home / ".local" / "share" / "Trash" / "files"
            self.assertEqual((trash / "obsolete.txt").read_text(encoding="utf-8"), "recoverable\n")

            refused = subprocess.run(
                [str(TRASH), str(home)],
                cwd=work,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("refusing protected path", refused.stderr)

    def test_allocates_distinct_destinations_for_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            home.mkdir()
            first.mkdir()
            second.mkdir()
            (first / "same.txt").write_text("first\n", encoding="utf-8")
            (second / "same.txt").write_text("second\n", encoding="utf-8")
            env = {**os.environ, "HOME": str(home)}
            subprocess.run(
                [str(TRASH), str(first / "same.txt"), str(second / "same.txt")],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            trash = home / ".Trash" if sys.platform == "darwin" else home / ".local" / "share" / "Trash" / "files"
            contents = sorted(path.read_text(encoding="utf-8") for path in trash.glob("same*.txt"))
            self.assertEqual(contents, ["first\n", "second\n"])

    def test_serializes_duplicate_names_across_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            home.mkdir()
            first.mkdir()
            second.mkdir()
            (first / "same.txt").write_text("first\n", encoding="utf-8")
            (second / "same.txt").write_text("second\n", encoding="utf-8")
            env = {**os.environ, "HOME": str(home)}
            processes = [
                subprocess.Popen(
                    [str(TRASH), str(directory / "same.txt")],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for directory in (first, second)
            ]
            results = [process.communicate(timeout=10) for process in processes]
            for process, (_, stderr) in zip(processes, results):
                self.assertEqual(process.returncode, 0, stderr)
            trash = home / ".Trash" if sys.platform == "darwin" else home / ".local" / "share" / "Trash" / "files"
            contents = sorted(path.read_text(encoding="utf-8") for path in trash.glob("same*.txt"))
            self.assertEqual(contents, ["first\n", "second\n"])


if __name__ == "__main__":
    unittest.main()
