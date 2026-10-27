import re

from django.template.loader import get_template
from django.test import SimpleTestCase


class TestHoveredRowGreyContrast(SimpleTestCase):
    """Quiet grey text inside builder table rows stays readable (WCAG AA, 4.5:1) when the
    row turns #f5f7fa on hover. The #6d7787 / #6e7785 meta greys are only 4.22:1 there,
    so text in those rows uses #5f6773 instead. Icons in the same rows only need 3:1."""

    WHITE, ROW_HOVER = '#ffffff', '#f5f7fa'

    # text that sits in a `.tlb-table tbody tr` (test rows and sublist table rows)
    HOVERED_ROW_TEXT = ('.tl-machine-unused', '.tl-machine-hint', '.tl-empty-sublist-msg')
    # icon-only rules in the same rows: non-text contrast, 3:1
    HOVERED_ROW_ICONS = ('.tl-drag-handle', '.tl-test-desc > i', '.tl-cell-actions .tl-action-icon',
                         '.tl-lock-icon', '.tl-caret-icon', '.tl-editlink')

    @staticmethod
    def _luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def _ratio(self, fg, bg):
        hi, lo = sorted((self._luminance(fg), self._luminance(bg)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def _style(self):
        origin = get_template('admin/qa/testlist/testlist_assets.html').origin
        with open(origin.name, encoding='utf-8') as f:
            source = f.read()
        style = source[source.index('<style>'):source.index('</style>')]
        return re.sub(r'/\*.*?\*/', '', style, flags=re.S)

    def _colour(self, style, selector):
        """The literal `color` in a rule whose selector list includes `selector` as one of its items."""
        rules = re.findall(
            r'(?:^|[},])\s*%s\s*(?:,[^{}]*)?\{([^}]*)\}' % re.escape(selector), style, flags=re.M,
        )
        self.assertTrue(rules, selector)
        for body in rules:
            value = re.search(r'(?<![\w-])color:\s*(#[0-9a-fA-F]{6})', body)
            if value:
                return value.group(1).lower()
        self.fail('%s { color } not found' % selector)

    def test_ratio_helper(self):
        self.assertAlmostEqual(self._ratio('#6d7787', self.ROW_HOVER), 4.22, places=2)
        self.assertAlmostEqual(self._ratio('#5f6773', self.ROW_HOVER), 5.33, places=2)

    def test_hovered_row_text_passes_on_white_and_hover(self):
        style = self._style()
        for selector in self.HOVERED_ROW_TEXT:
            colour = self._colour(style, selector)
            for bg in (self.WHITE, self.ROW_HOVER):
                self.assertGreaterEqual(self._ratio(colour, bg), 4.5, '%s %s on %s' % (selector, colour, bg))

    def test_hovered_row_icons_pass_non_text_contrast(self):
        style = self._style()
        for selector in self.HOVERED_ROW_ICONS:
            colour = self._colour(style, selector)
            self.assertGreaterEqual(self._ratio(colour, self.ROW_HOVER), 3.0, '%s %s' % (selector, colour))
