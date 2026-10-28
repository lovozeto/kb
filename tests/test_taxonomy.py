import unittest

from kb.parser import parse_taxonomy

TAXONOMY = """# Taxonomy

Free text is ignored.

## topic
- forms: formulario, form
- validation: errors, error messages

## concern
- a11y: accessibility, accesibilidad
"""


class ParseTaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.tax = parse_taxonomy(TAXONOMY)

    def test_facets_and_values(self):
        self.assertEqual(sorted(self.tax.facets), ["concern", "topic"])
        self.assertEqual(self.tax.facets["topic"], ["forms", "validation"])

    def test_synonym_resolves_to_canonical_value(self):
        self.assertEqual(self.tax.canonical("Accesibilidad"), ("concern", "a11y"))
        self.assertEqual(self.tax.canonical("a11y"), ("concern", "a11y"))
        self.assertIsNone(self.tax.canonical("pizza"))

    def test_expand_terms_adds_canonical_values(self):
        self.assertIn("a11y", self.tax.expand(["accessibility"]))
        self.assertIn("accesibilidad", self.tax.expand(["a11y"]))


if __name__ == "__main__":
    unittest.main()
