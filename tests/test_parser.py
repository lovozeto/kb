import unittest

from kb.parser import parse_markdown

DOC = """---
id: ux-forms
tier: advisory
last_verified: 2026-10-23
review_by: 2026-11-23
sources:
  - publisher: GOV.UK Design System
    url: https://design-system.service.gov.uk/patterns/names/
---

# Forms

## Names
<!-- tags: topic=forms; platform=web,ios; keywords=full name, given name -->
- Ask for a name only when the service needs it. [GOV.UK Design System: https://example.org/names]
- Prefer one full-name field. [GOV.UK Design System: https://example.org/names]

## Validation
<!-- tags: topic=forms,validation; concern=a11y -->
Intro paragraph that is not a rule.
- Show errors next to the field
  and in a summary at the top. [https://example.org/validation]

### Inline errors
- Use specific messages. [https://example.org/inline]
"""


class ParseMarkdownTest(unittest.TestCase):
    def setUp(self):
        self.doc = parse_markdown(DOC)

    def test_frontmatter_fields(self):
        self.assertEqual(self.doc.frontmatter["tier"], "advisory")
        self.assertEqual(self.doc.frontmatter["review_by"], "2026-11-23")
        self.assertEqual(self.doc.publishers, ["GOV.UK Design System"])

    def test_sections_with_anchors(self):
        self.assertEqual([s.anchor for s in self.doc.sections],
                         ["names", "validation", "validation/inline-errors"])

    def test_tags_are_multivalued(self):
        names = self.doc.sections[0]
        self.assertEqual(names.tags["platform"], ["web", "ios"])
        self.assertEqual(names.tags["keywords"], ["full name", "given name"])

    def test_child_section_inherits_parent_tags(self):
        inline = self.doc.sections[2]
        self.assertEqual(inline.tags["topic"], ["forms", "validation"])
        self.assertEqual(inline.tags["concern"], ["a11y"])

    def test_rules_are_bullets_with_their_source(self):
        validation = self.doc.sections[1]
        self.assertEqual(len(validation.rules), 1)
        rule = validation.rules[0]
        self.assertEqual(rule.text, "Show errors next to the field and in a summary at the top.")
        self.assertEqual(rule.source, "https://example.org/validation")

    def test_rule_source_keeps_publisher(self):
        self.assertEqual(self.doc.sections[0].rules[0].source,
                         "GOV.UK Design System: https://example.org/names")


if __name__ == "__main__":
    unittest.main()


class TitleTest(unittest.TestCase):
    def test_h1_becomes_the_document_title(self):
        doc = parse_markdown("# Dark patterns (deceptive design)\n\n## Sneaking\n- Hide costs. [x]\n")
        self.assertEqual(doc.title, "Dark patterns (deceptive design)")
