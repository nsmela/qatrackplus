"""The tests table fits a narrow card without sideways scrolling (round 3, R9).

At an 800px window (nav sidebar open) the tests card is about 460px wide. Two
tighter container-query steps (560px and 420px cards) let values wrap, trim
paddings and minimum widths, and keep the last column (action icons, or the
Reference & Tolerance pencil in machine mode) in view. These tests read the
builder's inline style block.
"""
import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase

ASSETS = 'admin/qa/testlist/testlist_assets.html'


def _style():
    html = render_to_string(ASSETS, {})
    return re.search(r'<style[^>]*>(.*?)</style>', html, re.S).group(1)


def _container_block(css, max_width):
    """Body of `@container tlb-table (max-width: <max_width>px) { ... }` (brace-matched)."""
    head = '@container tlb-table (max-width: %spx) {' % max_width
    start = css.index(head) + len(head)
    depth = 1
    i = start
    while depth:
        if css[i] == '{':
            depth += 1
        elif css[i] == '}':
            depth -= 1
        i += 1
    return css[start:i - 1]


def _rule(block, selector):
    """Declarations of the rule in `block` whose selector list is exactly `selector`."""
    for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', block):
        sel = re.sub(r'/\*.*?\*/', '', sel, flags=re.S)
        if ' '.join(sel.split()) == selector:
            return body
    raise AssertionError('no rule for %r' % selector)


def _px(body, prop):
    return int(re.search(r'(?:^|[;\s])%s:\s*(\d+)px' % re.escape(prop), body).group(1))


class TestNarrowCardSteps(SimpleTestCase):

    def setUp(self):
        self.css = _style()
        self.step560 = _container_block(self.css, 560)
        self.step420 = _container_block(self.css, 420)

    def test_steps_come_after_the_900px_step(self):
        """Later steps must follow the 900px one, or its min-widths would win."""
        i900 = self.css.index('@container tlb-table (max-width: 900px)')
        i560 = self.css.index('@container tlb-table (max-width: 560px)')
        i420 = self.css.index('@container tlb-table (max-width: 420px)')
        self.assertLess(i900, i560)
        self.assertLess(i560, i420)

    def test_smaller_test_column_minimums(self):
        self.assertLessEqual(_px(_rule(self.step560, '.tl-th-test'), 'min-width'), 90)
        self.assertLessEqual(_px(_rule(self.step420, '.tl-th-test'), 'min-width'), 80)

    def test_type_value_wraps_instead_of_holding_the_column_open(self):
        body = _rule(self.step560, '.tl-type-value')
        self.assertIn('white-space: normal', body)
        self.assertIn('overflow-wrap: anywhere', body)
        self.assertIn('-webkit-line-clamp: 3', body)

    def test_reftol_has_no_fixed_minimum(self):
        self.assertIn('min-width: 0', _rule(self.step560, '.tl-cell-reftol'))

    def test_action_icons_two_per_line_then_stacked(self):
        two = _rule(self.step560, '.tl-cell-actions')
        self.assertEqual(_px(two, 'min-width'), 56)
        self.assertEqual(_px(two, 'max-width'), 64)
        one = _rule(self.step420, '.tl-cell-actions')
        self.assertLessEqual(_px(one, 'max-width'), 28)

    def test_tap_targets_stay_24px(self):
        for selector in ('.tl-cell-actions .tl-action-icon', '.tlb-table .tl-machine-edit'):
            body = _rule(self.step560, selector)
            self.assertEqual(_px(body, 'min-width'), 24, selector)
            self.assertEqual(_px(body, 'min-height'), 24, selector)
            self.assertIn('box-sizing: border-box', body, selector)

    def test_no_column_is_hidden(self):
        for block in (self.step560, self.step420):
            self.assertNotIn('display: none', block)

    def test_wide_layout_untouched(self):
        """The base (wide card) widths are still the same as before."""
        self.assertIn('.tl-th-test { min-width: 260px; }', self.css)
        self.assertIn('.tl-th-actions { width: 90px; text-align: right !important; }', self.css)
