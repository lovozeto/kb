import os
import unittest

from kb.parser import parse_markdown
from tests.helpers import CliTestCase

DECISIONS = """---
tier: advisory
review_by: 2027-01-01
kind: decisions
---

# Decisions

## Choices
<!-- tags: topic=forms -->
- Use month precision. 2026-07
- Use day precision. 2026-10-22
- Replaced rule. 2026-10-28 (replaces the old one)
- Undated rule with no source.
- Sourced rule. [somewhere]
"""


class ParserTest(unittest.TestCase):
    def test_frontmatter_exposes_kind(self):
        self.assertEqual(parse_markdown(DECISIONS).frontmatter["kind"], "decisions")

    def test_rule_knows_whether_it_ends_with_a_date(self):
        rules = parse_markdown(DECISIONS).sections[0].rules
        self.assertEqual([r.dated for r in rules], [True, True, True, False, False])


class LintDecisionsTest(CliTestCase):
    def write(self, name, body):
        with open(os.path.join(self.kb_root, "ux", name), "w") as f:
            f.write(body)

    def no_source_lines(self, ref_prefix):
        warnings = self.kb_json("lint")["warnings"]
        return [w for w in warnings if w.startswith(ref_prefix) and "no source" in w]

    def test_dated_rules_in_a_decisions_file_do_not_warn(self):
        self.write("choices.md", DECISIONS)
        warned = self.no_source_lines("ux/choices#")
        self.assertEqual(len(warned), 1)
        self.assertIn("line 14", warned[0])

    def test_dates_do_not_count_outside_a_decisions_file(self):
        self.write("choices.md", DECISIONS.replace("kind: decisions\n", ""))
        self.assertEqual(len(self.no_source_lines("ux/choices#")), 4)
