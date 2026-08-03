import re
import tomllib
import unittest

from lib.host_contract import expected_kimi_hooks, is_managed_kimi_hook_command
from lib.kimi_config import (
    BLOCK_BEGIN,
    BLOCK_END,
    contains_expected_kimi_hooks,
    edit_kimi_config,
    remove_kimi_hooks,
)


BUDGETS = {"Stop": 330, "PreToolUse": 600}


class KimiConfigTests(unittest.TestCase):
    def test_preserves_user_content_and_is_idempotent(self):
        original = (
            '# operator comment\n'
            'default_model = "chosen-at-runtime"\n\n'
            '[[hooks]]\n'
            'event = "SessionStart"\n'
            'command = "operator-hook"\n'
            'timeout = 5\n'
        )
        first = edit_kimi_config(original, BUDGETS)
        second = edit_kimi_config(first, BUDGETS)
        self.assertEqual(second, first)
        self.assertIn('# operator comment\n', first)
        self.assertIn('default_model = "chosen-at-runtime"', first)
        self.assertIn('command = "operator-hook"', first)
        self.assertEqual(first.count(BLOCK_BEGIN), 1)
        self.assertTrue(contains_expected_kimi_hooks(first, BUDGETS))
        managed = [
            hook
            for hook in tomllib.loads(first)["hooks"]
            if is_managed_kimi_hook_command(hook.get("command"))
        ]
        self.assertEqual(managed, expected_kimi_hooks(BUDGETS))
        by_event = {hook["event"]: hook for hook in managed}
        self.assertEqual(by_event["PreToolUse"]["matcher"], "^Shell$")
        self.assertIsNotNone(re.search(by_event["PreToolUse"]["matcher"], "Shell"))
        self.assertIsNone(re.search(by_event["PreToolUse"]["matcher"], "ReadFile"))
        self.assertEqual(
            by_event["UserPromptSubmit"]["command"],
            '"$HOME/.agents/kimi/session-guard.py" --hook',
        )

    def test_accepts_exact_hooks_after_kimi_rewrites_comments(self):
        marked = edit_kimi_config("", BUDGETS)
        rewritten = marked.replace(f"{BLOCK_BEGIN}\n", "").replace(
            f"{BLOCK_END}\n",
            "",
        )
        self.assertTrue(contains_expected_kimi_hooks(rewritten, BUDGETS))
        self.assertEqual(edit_kimi_config(rewritten, BUDGETS), rewritten)
        self.assertEqual(remove_kimi_hooks(rewritten, BUDGETS), "")

    def test_removes_marked_hooks_without_touching_operator_hook(self):
        original = (
            '[[hooks]]\n'
            'event = "SessionStart"\n'
            'command = "operator-hook"\n'
            'timeout = 5\n'
        )
        installed = edit_kimi_config(original, BUDGETS)
        removed = remove_kimi_hooks(installed, BUDGETS)
        self.assertEqual(tomllib.loads(removed)["hooks"][0]["command"], "operator-hook")
        self.assertFalse(contains_expected_kimi_hooks(removed, BUDGETS))

    def test_rejects_altered_dispatch_hook(self):
        text = (
            '[[hooks]]\n'
            'event = "Stop"\n'
            'command = "\\"$HOME/.agents/hooks/dispatch.py\\" --host kimi Stop"\n'
        )
        with self.assertRaisesRegex(ValueError, "stale or altered"):
            edit_kimi_config(text, BUDGETS)

    def test_rejects_malformed_marker_ownership(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            edit_kimi_config(f"{BLOCK_BEGIN}\n", BUDGETS)


if __name__ == "__main__":
    unittest.main()
