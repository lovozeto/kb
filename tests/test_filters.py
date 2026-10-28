import os
import unittest

from tests.helpers import CliTestCase


class FilterTest(CliTestCase):
    def refs(self, *args, **kw):
        return {h["ref"] for h in self.kb_json("search", *args, **kw)}

    def test_base_filter(self):
        self.assertEqual(self.refs("a11y", "--base", "brand"), {"brand/color#contrast"})

    def test_tag_filter_accepts_synonyms(self):
        refs = self.refs("errors", "--tag", "accessibility")
        self.assertTrue(refs)
        self.assertTrue(all(r.startswith("ux/forms#validation") for r in refs))

    def test_facet_filter_is_exact_per_facet(self):
        self.assertEqual(self.refs("name", "--facet", "platform=iphone"), {"ux/forms#names"})

    def test_tier_filter(self):
        self.assertEqual(self.refs("contrast", "--tier", "advisory"), set())
        self.assertEqual(self.refs("contrast", "--tier", "proven"), {"brand/color#contrast"})

    def test_fresh_excludes_expired_files(self):
        # brand/color review_by 2026-02-10 is past "today" (2026-10-27)
        self.assertEqual(self.refs("contrast", "--fresh"), set())


class ProjectScopeTest(CliTestCase):
    def refs(self, *args, **kw):
        return {h["ref"] for h in self.kb_json("search", *args, **kw)}

    def test_other_projects_are_hidden_by_default(self):
        self.assertNotIn("alpha:palette#wedding-palette", self.refs("palette"))

    def test_project_flag_includes_that_project(self):
        self.assertIn("alpha:palette#wedding-palette", self.refs("palette", "--project", "alpha"))

    def test_current_repo_knowledge_is_included(self):
        alpha = os.path.join(self.projects, "alpha")
        self.assertIn("alpha:palette#wedding-palette", self.refs("palette", cwd=alpha))

    def test_all_flag(self):
        self.assertIn("alpha:palette#wedding-palette", self.refs("sage green", "--all"))


if __name__ == "__main__":
    unittest.main()
