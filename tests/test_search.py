import unittest

from tests.helpers import CliTestCase


class SearchTest(CliTestCase):
    def test_finds_a_rule_by_its_words(self):
        hits = self.kb_json("search", "contrast ratio")
        self.assertEqual(hits[0]["ref"], "brand/color#contrast")
        self.assertIn("4.5:1", hits[0]["text"])
        self.assertEqual(hits[0]["source"], "WCAG: https://example.org/contrast")

    def test_keywords_find_rules_that_do_not_contain_the_word(self):
        refs = [h["ref"] for h in self.kb_json("search", "given name")]
        self.assertIn("ux/forms#names", refs)

    def test_synonyms_reach_the_canonical_tag(self):
        refs = {h["ref"] for h in self.kb_json("search", "accesibilidad")}
        self.assertIn("brand/color#contrast", refs)
        self.assertIn("ux/forms#validation", refs)

    def test_raw_templates_and_index_are_excluded_by_default(self):
        refs = [h["ref"] for h in self.kb_json("search", "full name")]
        self.assertFalse([r for r in refs if ".raw" in r or "templates" in r or "INDEX" in r])

    def test_raw_flag_includes_raw_sources(self):
        refs = [h["ref"] for h in self.kb_json("search", "raw capture", "--raw")]
        self.assertIn("ux/.raw/govuk#names", refs)


if __name__ == "__main__":
    unittest.main()


class PhraseTest(CliTestCase):
    def test_exact_phrase_ranks_before_scattered_words(self):
        import os
        path = os.path.join(self.kb_root, "ux", "patterns.md")
        with open(path, "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n"
                    "## Dark mode\n- Dark surfaces need softer patterns of contrast. [a]\n\n"
                    "## Deceptive design\n- Dark patterns trick users into choices. [b]\n")
        hits = self.kb_json("search", "dark", "patterns")
        self.assertEqual(hits[0]["ref"], "ux/patterns#deceptive-design")


class TitleSearchTest(CliTestCase):
    def test_file_title_words_find_its_rules(self):
        import os
        with open(os.path.join(self.kb_root, "ux", "deceptive.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n"
                    "# Dark patterns (deceptive design)\n\n"
                    "## Sneaking\n- Never add items to the basket silently. [a]\n")
        refs = [h["ref"] for h in self.kb_json("search", "dark", "patterns")]
        self.assertIn("ux/deceptive#sneaking", refs)
