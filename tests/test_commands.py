import os
import time
import unittest

from tests.helpers import CliTestCase


class GetTest(CliTestCase):
    def test_get_returns_only_that_section(self):
        out = self.run_kb("get", "ux/forms#validation").stdout
        self.assertIn("## Validation", out)
        self.assertIn("summary at the top", out)
        self.assertNotIn("## Names", out)
        self.assertNotIn("### Inline errors", out)

    def test_get_child_section(self):
        out = self.run_kb("get", "ux/forms#validation/inline-errors").stdout
        self.assertIn("Enter your full name", out)

    def test_get_without_anchor_lists_the_outline(self):
        outline = self.kb_json("get", "ux/forms")
        self.assertEqual([s["anchor"] for s in outline],
                         ["names", "validation", "validation/inline-errors"])
        self.assertEqual(outline[0]["rules"], 2)

    def test_get_unknown_ref_fails(self):
        self.run_kb("get", "nope/nothing#x", expect=1)


class FacetsTest(CliTestCase):
    def test_counts_sections_per_value(self):
        facets = self.kb_json("facets")
        # by hand from the fixture: a11y = validation, its child inline-errors, contrast;
        # forms = names, validation, inline-errors, delegation#default-model
        self.assertEqual(facets["concern"]["a11y"], 3)
        self.assertEqual(facets["topic"]["forms"], 4)


class StaleTest(CliTestCase):
    def test_lists_expired_files(self):
        refs = [s["ref"] for s in self.kb_json("stale")]
        self.assertEqual(refs, ["brand/color"])


class LintTest(CliTestCase):
    def test_clean_vocabulary_has_only_warnings(self):
        report = self.kb_json("lint")
        self.assertEqual(report["errors"], [])
        warnings = " ".join(report["warnings"])
        self.assertIn("brand/color#untagged-section", warnings)
        self.assertIn("no source", warnings)

    def test_unknown_tag_value_is_an_error(self):
        path = os.path.join(self.kb_root, "ux", "forms.md")
        with open(path, "a") as f:
            f.write("\n## Bad\n<!-- tags: topic=pizza; mood=happy -->\n- x. [src]\n")
        report = self.kb_json("lint", expect=1)
        errors = " ".join(report["errors"])
        self.assertIn("pizza", errors)
        self.assertIn("mood", errors)


class ReindexTest(CliTestCase):
    def test_index_follows_file_changes(self):
        self.assertEqual(self.kb_json("search", "zebra"), [])
        time.sleep(0.01)
        path = os.path.join(self.kb_root, "brand", "color.md")
        with open(path, "a") as f:
            f.write("\n## Zebra stripes\n- Zebra stripes are high contrast. [zoo]\n")
        refs = [h["ref"] for h in self.kb_json("search", "zebra")]
        self.assertIn("brand/color#zebra-stripes", refs)


if __name__ == "__main__":
    unittest.main()


class CodeChangeReindexTest(CliTestCase):
    def test_index_rebuilds_when_kb_code_version_changes(self):
        import sqlite3
        self.kb_json("search", "contrast")
        db = sqlite3.connect(self.tmp + "/index.db")
        db.execute("UPDATE meta SET value = 'stale-fingerprint' WHERE key = 'fingerprint'")
        db.execute("DELETE FROM rules_fts")
        db.commit()
        db.close()
        self.assertTrue(self.kb_json("search", "contrast"))
