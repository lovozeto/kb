import os
import unittest

from tests.helpers import CliTestCase

MARK = "<!-- kb router:"


class RouterTest(CliTestCase):
    def test_router_lists_every_file_with_its_summary(self):
        rows = self.kb_json("router")
        self.assertEqual([r["ref"] for r in rows], ["brand/color", "delegation", "ux/forms"])
        self.assertEqual(rows[2]["summary"], "Forms: names, validation and inline errors")
        self.assertEqual(rows[0]["summary"], "")

    def test_router_text_is_a_markdown_table(self):
        out = self.run_kb("router").stdout
        self.assertIn("| Base | File | What for |", out)
        self.assertIn("| ux | `ux/forms.md` | Forms: names, validation and inline errors |", out)
        self.assertIn("| brand | `brand/color.md` | (no summary) |", out)

    def test_write_keeps_the_head_and_regenerates_the_table(self):
        path = os.path.join(self.kb_root, "INDEX.md")
        with open(path, "w") as f:
            f.write("# My router\n\nHand-written intro.\n\n| Base | File | What for |\n|---|---|---|\n"
                    "| old | `old/gone.md` | dead |\n")
        self.run_kb("router", "--write")
        with open(path) as f:
            text = f.read()
        self.assertTrue(text.startswith("# My router\n\nHand-written intro.\n\n" + MARK))
        self.assertNotIn("old/gone.md", text)
        self.assertIn("`ux/forms.md`", text)
        # a second write is stable
        self.run_kb("router", "--write")
        with open(path) as f:
            self.assertEqual(f.read(), text)

    def test_write_creates_the_file_when_missing(self):
        path = os.path.join(self.kb_root, "INDEX.md")
        os.remove(path)
        self.run_kb("router", "--write")
        with open(path) as f:
            text = f.read()
        self.assertIn(MARK, text)
        self.assertIn("`brand/color.md`", text)


class LintRouterTest(CliTestCase):
    def test_fixture_index_is_clean(self):
        report = self.kb_json("lint")
        self.assertEqual([e for e in report["errors"] if e.startswith("INDEX.md")], [])
        self.assertEqual([w for w in report["warnings"] if w.startswith("INDEX.md")], [])

    def test_dead_entry_is_an_error(self):
        path = os.path.join(self.kb_root, "INDEX.md")
        with open(path, "a") as f:
            f.write("| react | `react/forms.md` | planned |\n")
        report = self.kb_json("lint", expect=1)
        self.assertTrue(any("`react/forms.md` does not exist" in e for e in report["errors"]))

    def test_unlisted_file_is_a_warning(self):
        with open(os.path.join(self.kb_root, "ux", "buttons.md"), "w") as f:
            f.write("---\ntier: advisory\nreview_by: 2027-01-01\nsummary: Buttons\n---\n\n"
                    "## Labels\n<!-- tags: topic=forms -->\n- Use verbs. [src]\n")
        report = self.kb_json("lint")
        self.assertTrue(any("`ux/buttons.md` is not listed" in w for w in report["warnings"]))
        self.run_kb("router", "--write")
        report = self.kb_json("lint")
        self.assertFalse(any("not listed" in w for w in report["warnings"]))

    def test_changed_summary_is_a_warning_until_rewritten(self):
        path = os.path.join(self.kb_root, "ux", "forms.md")
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("summary: Forms: names", "summary: Forms, renamed"))
        report = self.kb_json("lint")
        self.assertTrue(any("differs from the summaries" in w for w in report["warnings"]))
        self.run_kb("router", "--write")
        report = self.kb_json("lint")
        self.assertFalse(any("differs" in w for w in report["warnings"]))

    def test_missing_summary_is_a_warning(self):
        warnings = " ".join(self.kb_json("lint")["warnings"])
        self.assertIn("brand/color: no summary", warnings)
        self.assertNotIn("ux/forms: no summary", warnings)


class StatusTest(CliTestCase):
    def _set_status(self, value):
        path = os.path.join(self.kb_root, "ux", "forms.md")
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("tier: advisory", "tier: advisory\nstatus: " + value))

    def test_ambiguous_file_shows_in_stale(self):
        self._set_status("ambiguous")
        rows = {r["ref"]: r["reason"] for r in self.kb_json("stale")}
        self.assertEqual(rows["ux/forms"], "ambiguous")
        self.assertEqual(rows["brand/color"], "expired")

    def test_fresh_status_changes_nothing(self):
        self._set_status("fresh")
        self.assertEqual([r["ref"] for r in self.kb_json("stale")], ["brand/color"])

    def test_unknown_status_is_a_lint_error(self):
        self._set_status("maybe")
        report = self.kb_json("lint", expect=1)
        self.assertTrue(any("status 'maybe'" in e for e in report["errors"]))

    def test_stale_count_is_one_line(self):
        self._set_status("ambiguous")
        out = self.run_kb("stale", "--count").stdout.strip()
        self.assertEqual(out, "kb: 2 file(s) need review (1 expired, 0 without review_by,"
                              " 1 ambiguous)")
        data = self.kb_json("stale", "--count")
        self.assertEqual(data["total"], 2)


class FindHereTest(CliTestCase):
    def test_repo_outside_projects_root_is_found_from_inside_it(self):
        repo = os.path.join(self.tmp, "elsewhere", "beta")
        kdir = os.path.join(repo, ".claude", "knowledge")
        os.makedirs(os.path.join(repo, "src"))
        os.makedirs(kdir)
        with open(os.path.join(kdir, "notes.md"), "w") as f:
            f.write("---\ntier: proven\nreview_by: 2027-01-01\n---\n\n## Naming\n"
                    "<!-- tags: topic=forms -->\n- Call the mascot Quokka. [team]\n")
        hits = self.kb_json("search", "quokka", cwd=os.path.join(repo, "src"))
        self.assertEqual(hits[0]["ref"], "beta:notes#naming")
        # from outside that repo it is not in scope
        self.assertEqual(self.kb_json("search", "quokka"), [])

    def test_name_clash_with_a_projects_root_repo_uses_the_path(self):
        repo = os.path.join(self.tmp, "elsewhere", "alpha")
        kdir = os.path.join(repo, ".claude", "knowledge")
        os.makedirs(kdir)
        with open(os.path.join(kdir, "notes.md"), "w") as f:
            f.write("## Naming\n- Call the mascot Wombat. [team]\n")
        hits = self.kb_json("search", "wombat", cwd=repo)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["ref"].endswith("/elsewhere/alpha:notes#naming"))


if __name__ == "__main__":
    unittest.main()
