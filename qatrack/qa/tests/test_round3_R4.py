"""Builder table rows align their cells to the top (round 3, R4).

A long name, description or type value makes a row taller; the other cells
(drag handle, chips, icons) should stay level with the test name's first line
instead of drifting to the middle of the row.
"""
import re

from django.template.loader import get_template
from django.test import SimpleTestCase

COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
RULE_RE = re.compile(r'([^{}]+)\{([^{}]*)\}')


def builder_css():
    """The builder's inline <style> block, without comments."""
    origin = get_template('admin/qa/testlist/testlist_assets.html').origin
    with open(origin.name, encoding='utf-8') as f:
        source = f.read()
    styles = re.findall(r'<style[^>]*>(.*?)</style>', source, re.S)
    assert styles, 'testlist_assets.html has no <style> block'
    return COMMENT_RE.sub('', '\n'.join(styles))


def declarations(css, selector):
    """Declarations ({property: value}) of every rule whose selector list includes `selector`."""
    found = []
    for selectors, body in RULE_RE.findall(css):
        names = [' '.join(s.split()) for s in selectors.split(',')]
        if selector in names:
            decls = {}
            for decl in body.split(';'):
                if ':' in decl:
                    prop, value = decl.split(':', 1)
                    decls[prop.strip()] = value.strip()
            found.append(decls)
    return found


class TestRowsAlignTop(SimpleTestCase):

    def setUp(self):
        self.css = builder_css()

    def test_table_cells_align_top(self):
        rules = declarations(self.css, '.tlb-table tbody td')
        self.assertTrue(rules, 'no `.tlb-table tbody td` rule found')
        values = [r['vertical-align'] for r in rules if 'vertical-align' in r]
        self.assertEqual(values, ['top'])

    def test_no_builder_cell_rule_centres_vertically(self):
        for selectors, body in RULE_RE.findall(self.css):
            if 'tlb-table' in selectors or 'tl-cell-' in selectors:
                self.assertNotRegex(body, r'vertical-align\s*:\s*middle', selectors.strip())

    def test_description_icon_sits_by_first_line(self):
        rules = declarations(self.css, '.tl-test-desc')
        self.assertIn('flex-start', [r.get('align-items') for r in rules])

    def test_sublist_header_aligns_top(self):
        rules = declarations(self.css, '.tl-sublist-header')
        self.assertIn('flex-start', [r.get('align-items') for r in rules])
        self.assertNotIn('center', [r.get('align-items') for r in rules])

    def test_changelist_rows_unchanged(self):
        rules = declarations(self.css, '#result_list tbody td')
        self.assertIn('middle', [r.get('vertical-align') for r in rules])
