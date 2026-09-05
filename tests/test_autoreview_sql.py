import importlib.util
from pathlib import Path
import unittest


AUTOREVIEW = Path(__file__).resolve().parents[1] / "skills/review/scripts/agent-autoreview.py"
spec = importlib.util.spec_from_file_location("autoreview_sql_fixture", AUTOREVIEW)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fts_statement(option):
    return "CREATE VIRTUAL TABLE media_fts USING fts5(\n    title,\n    " + option + "\n);"


class SqlTokenizerSecretTests(unittest.TestCase):
    def test_known_sqlite_tokenizer_is_not_a_credential(self):
        statement = fts_statement("tokenize = 'unicode61 remove_diacritics 2'")
        self.assertEqual(module.secret_findings(statement), [])

    def test_diff_prefixed_sqlite_statement_is_not_a_credential(self):
        statement = fts_statement("tokenize = 'unicode61 remove_diacritics 2'")
        diff = "\n".join("+" + line for line in statement.splitlines())
        self.assertEqual(module.secret_findings(diff), [])

    def test_tokenizer_named_secret_is_still_blocked(self):
        value = "Ab19" * 8
        self.assertIn("assigned-tokenize", module.secret_findings(fts_statement("tokenize = '" + value + "'")))

    def test_generic_assignment_outside_sql_is_still_blocked(self):
        self.assertIn("assigned-tokenize", module.secret_findings("tokenize = 'unicode61 remove_diacritics 2'"))

    def test_other_credential_name_inside_sql_is_still_blocked(self):
        self.assertIn("assigned-api_token", module.secret_findings(fts_statement("API_TOKEN = 'unicode61 remove_diacritics 2'")))

    def test_known_token_pattern_inside_sql_is_still_blocked(self):
        value = "ghp_" + "A" * 30
        self.assertIn("github-token", module.secret_findings(fts_statement("tokenize = '" + value + "'")))

    def test_assignment_after_sql_statement_is_still_blocked(self):
        text = fts_statement("tokenize = 'unicode61'") + "\ntokenize = 'unicode61 remove_diacritics 2'"
        self.assertIn("assigned-tokenize", module.secret_findings(text))


if __name__ == "__main__":
    unittest.main()
