"""Behaviour required by the two-axis review of the first kb version."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from tests.helpers import CliTestCase, ROOT


class AutoFacetTest(CliTestCase):
    def refs(self, *args):
        return {h["ref"] for h in self.kb_json("search", *args)}

    def test_facets_include_automatic_ones(self):
        facets = self.kb_json("facets")
        self.assertEqual(facets["base"]["ux"], 3)          # names, validation, inline-errors
        self.assertEqual(facets["tier"]["proven"], 3)      # contrast, untagged, default-model
        self.assertEqual(facets["fresh"]["expired"], 2)    # brand/color sections
        self.assertEqual(facets["source"]["GOV.UK Design System"], 3)

    def test_facet_filter_on_automatic_facets(self):
        self.assertEqual(self.refs("contrast", "--facet", "base=brand"), {"brand/color#contrast"})
        self.assertEqual(self.refs("contrast", "--facet", "tier=advisory"), set())
        self.assertIn("ux/forms#names", self.refs("name", "--facet", "source=GOV.UK Design System"))

    def test_unknown_facet_is_an_error_not_an_empty_result(self):
        self.run_kb("search", "name", "--facet", "colour=red", expect=2)


class QuerySynonymTest(CliTestCase):
    def test_synonym_reaches_rules_in_untagged_sections(self):
        # "colour" is a synonym of the topic value "color"; the untagged rule says "color".
        with open(os.path.join(self.kb_root, "brand", "notes.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n"
                    "## Loose notes\n- Pick one accent color per screen. [n]\n")
        refs = [h["ref"] for h in self.kb_json("search", "colour", "accent")]
        self.assertIn("brand/notes#loose-notes", refs)


class LintScopeTest(CliTestCase):
    def test_lint_defaults_to_global_scope(self):
        with open(os.path.join(self.projects, "alpha", ".claude", "knowledge", "palette.md"), "a") as f:
            f.write("\n## Bad\n<!-- tags: topic=pizza -->\n- x. [s]\n")
        self.assertEqual(self.kb_json("lint")["errors"], [])
        self.assertTrue(self.kb_json("lint", "--project", "alpha", expect=1)["errors"])


class OutputTest(CliTestCase):
    def test_index_json(self):
        out = self.kb_json("index")
        self.assertTrue(out["index"].endswith("index.db"))

    def test_text_output_marks_truncation(self):
        with open(os.path.join(self.kb_root, "brand", "long.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n## Long\n- longword "
                    + "filler " * 80 + "[s]\n")
        line = self.run_kb("search", "longword").stdout.splitlines()[0]
        self.assertIn("…", line)


class DiscoveryTest(CliTestCase):
    def test_repos_with_the_same_name_do_not_collide(self):
        twin = os.path.join(self.projects, "work", "alpha", ".claude", "knowledge")
        os.makedirs(twin)
        with open(os.path.join(twin, "notes.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n## Twin\n- Twin repo rule. [t]\n")
        refs = {h["ref"] for h in self.kb_json("search", "twin", "--all")}
        self.assertTrue(refs)
        palette = {h["ref"] for h in self.kb_json("search", "sage", "--all")}
        self.assertTrue(palette)
        self.assertNotEqual(refs, palette)

    def test_nested_templates_folder_is_indexed(self):
        nested = os.path.join(self.kb_root, "brand", "templates")
        os.makedirs(nested)
        with open(os.path.join(nested, "deck.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\n---\n\n## Deck\n- Decks use the brand grid. [d]\n")
        self.assertIn("brand/templates/deck#deck",
                      {h["ref"] for h in self.kb_json("search", "brand grid")})

    def test_root_templates_folder_is_still_skipped(self):
        self.assertEqual(self.kb_json("search", "placeholder"), [])


class RebuildTest(CliTestCase):
    def test_index_is_rebuilt_after_kb_code_changes(self):
        copy = os.path.join(self.tmp, "kbcopy")
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
        env = dict(os.environ, KB_ROOT=self.kb_root, KB_PROJECTS_ROOT=self.projects,
                   KB_INDEX=os.path.join(self.tmp, "copy.db"), KB_TODAY=self.today)
        run = lambda: subprocess.run([sys.executable, os.path.join(copy, "bin", "kb"), "search",
                                      "contrast"], env=env, capture_output=True, text=True)
        run()
        before = os.stat(env["KB_INDEX"]).st_mtime_ns
        time.sleep(0.05)
        run()
        self.assertEqual(os.stat(env["KB_INDEX"]).st_mtime_ns, before)   # nothing changed
        with open(os.path.join(copy, "kb", "parser.py"), "a") as f:
            f.write("\n# code change\n")
        time.sleep(0.05)
        run()
        self.assertGreater(os.stat(env["KB_INDEX"]).st_mtime_ns, before)


class ConcurrencyTest(CliTestCase):
    def test_parallel_runs_do_not_break_the_index(self):
        env = dict(os.environ, KB_ROOT=self.kb_root, KB_PROJECTS_ROOT=self.projects,
                   KB_INDEX=os.path.join(self.tmp, "par.db"), KB_TODAY=self.today)
        procs = [subprocess.Popen([sys.executable, os.path.join(ROOT, "bin", "kb"), "index"],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(6)]
        codes = [p.wait() for p in procs]
        self.assertEqual(codes, [0] * 6)
        self.assertTrue(self.kb_json("search", "contrast"))


if __name__ == "__main__":
    unittest.main()
