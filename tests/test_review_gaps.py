import os
import unittest

from tests.helpers import CliTestCase


class SynonymRankingTest(CliTestCase):
    def test_rule_with_a_synonym_word_ranks_before_tag_only_matches(self):
        with open(os.path.join(self.kb_root, "ux", "notes.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n"
                    "## Focus\n<!-- tags: concern=a11y -->\n"
                    "- Keep focus visible. [a]\n- Never trap the keyboard. [b]\n"
                    "- Label every icon button. [c]\n\n"
                    "## Audit\n- Run an accessibility audit before launch. [d]\n")
        hits = self.kb_json("search", "accesibilidad")
        self.assertEqual(hits[0]["ref"], "ux/notes#audit")


class MissingKbTest(CliTestCase):
    def test_search_fails_when_the_kb_folder_is_missing(self):
        env_root = os.path.join(self.tmp, "nowhere")
        self.kb_root = env_root
        proc = self.run_kb("search", "contrast", expect=2)
        self.assertIn("no KB", proc.stderr)

    def test_lint_fails_when_the_kb_folder_is_missing(self):
        self.kb_root = os.path.join(self.tmp, "nowhere")
        proc = self.run_kb("lint", expect=1)
        self.assertIn("no KB", proc.stderr)


class EmptyQueryTest(CliTestCase):
    def test_empty_query_is_an_error(self):
        proc = self.run_kb("search", " ", expect=2)
        self.assertIn("empty", proc.stderr)


if __name__ == "__main__":
    unittest.main()
