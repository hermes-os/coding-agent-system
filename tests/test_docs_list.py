from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "bin" / "docs-list"


def load_script():
    loader = importlib.machinery.SourceFileLoader("docs_list", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DocsListTests(unittest.TestCase):
    def test_reads_summary_and_read_when(self):
        module = load_script()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "guide.md"
            path.write_text(
                "---\nsummary: 'Billing guide'\nread_when:\n  - Changing checkout.\n---\n# Guide\n",
                encoding="utf-8",
            )
            summary, read_when, error = module.metadata(path)
        self.assertEqual(summary, "Billing guide")
        self.assertEqual(read_when, ["Changing checkout."])
        self.assertIsNone(error)

    def test_reports_missing_frontmatter(self):
        module = load_script()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "guide.md"
            path.write_text("# Guide\n", encoding="utf-8")
            self.assertEqual(module.metadata(path), (None, [], "missing frontmatter"))


if __name__ == "__main__":
    unittest.main()
