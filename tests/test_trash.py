import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
TRASH = SYSTEM_ROOT / "bin" / "agent-trash"


def load_trash_module():
    loader = importlib.machinery.SourceFileLoader("agent_trash_fixture", str(TRASH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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

    def test_rejects_symlinked_ancestor_but_moves_final_symlink_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            work = root / "work"
            home.mkdir()
            work.mkdir()
            ancestor = work / "ancestor"
            ancestor.symlink_to(root, target_is_directory=True)
            final_link = work / "home-link"
            final_link.symlink_to(home, target_is_directory=True)
            env = {**os.environ, "HOME": str(home)}

            refused = subprocess.run(
                [str(TRASH), str(ancestor / "home")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("refusing protected path", refused.stderr)
            self.assertTrue(home.is_dir())

            moved = subprocess.run(
                [str(TRASH), str(final_link)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(moved.returncode, 0, moved.stderr)
            self.assertTrue(home.is_dir())
            trash = home / ".Trash" if sys.platform == "darwin" else home / ".local" / "share" / "Trash" / "files"
            self.assertTrue((trash / "home-link").is_symlink())

    def test_linux_xdg_permissions_and_metadata_failure_ordering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            data_home = root / "private-data"
            work = root / "work"
            home.mkdir()
            work.mkdir()
            env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(data_home)}
            module = load_trash_module()

            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(module.sys, "platform", "linux"):
                trash = module.trash_root()
                source = work / "recoverable.txt"
                source.write_text("recoverable\n", encoding="utf-8")
                with module.trash_lock(trash):
                    module.move_to_trash(source, trash / source.name)
                info = data_home / "Trash" / "info" / "recoverable.txt.trashinfo"
                self.assertEqual(trash, data_home / "Trash" / "files")
                self.assertEqual(stat.S_IMODE(trash.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(info.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(info.stat().st_mode), 0o600)

                metadata_failure = work / "metadata-failure.txt"
                metadata_failure.write_text("still here\n", encoding="utf-8")
                with mock.patch.object(module, "stage_trashinfo", side_effect=OSError("fixture")):
                    with self.assertRaises(OSError):
                        module.move_to_trash(metadata_failure, trash / metadata_failure.name)
                self.assertTrue(metadata_failure.exists())

                move_failure = work / "move-failure.txt"
                move_failure.write_text("still here\n", encoding="utf-8")
                move_info = data_home / "Trash" / "info" / "move-failure.txt.trashinfo"
                with mock.patch.object(module.shutil, "move", side_effect=OSError("fixture")):
                    with self.assertRaises(OSError):
                        module.move_to_trash(move_failure, trash / move_failure.name)
                self.assertTrue(move_failure.exists())
                self.assertFalse(move_info.exists())

                with self.assertRaisesRegex(ValueError, "refusing protected path"):
                    module.guarded_source(str(data_home), work, trash)


if __name__ == "__main__":
    unittest.main()
