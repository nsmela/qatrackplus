"""Round 2, N9: the test list changelist header padding actually applies.

Django's changelists.css sets ``#changelist table thead th { padding: 0 }``,
which outranks ``#result_list thead th``, and base.css pads the header's inner
``.text > a`` / ``.text > span`` (8px 10px) instead. So the builder's header
spacing (7px 10px, as on ``.tl-table th`` in the design spec) has to go on that
inner element, with a selector that outranks Django's.
"""

import re

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase

ASSETS = 'admin/qa/testlist/testlist_assets.html'
INNER_SELECTORS = {'#result_list thead th .text > a', '#result_list thead th .text > span'}


def _parse_rules(css):
    """Return (at_rule, selectors, declarations) for each rule, in source order.

    A small brace-aware parser, enough for the builder's inline stylesheet:
    ``at_rule`` is the enclosing ``@media``/``@container`` prelude (or '').
    """
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules = []
    stack = []
    buf = ''
    for ch in css:
        if ch == '{':
            stack.append(buf.strip())
            buf = ''
        elif ch == '}':
            prelude = stack.pop() if stack else ''
            body = buf.strip()
            buf = ''
            if prelude.startswith('@') or not body and not prelude:
                continue
            decls = {}
            for decl in body.split(';'):
                if ':' in decl:
                    name, value = decl.split(':', 1)
                    decls[name.strip()] = value.strip()
            at_rule = next((p for p in reversed(stack) if p.startswith('@')), '')
            selectors = [' '.join(s.split()) for s in prelude.split(',')]
            rules.append((at_rule, selectors, decls))
        else:
            buf += ch
    return rules


def _specificity(selector):
    """(ids, classes/attributes/pseudo-classes, elements) for a simple selector."""
    sel = re.sub(r'::?[a-z-]+(\([^)]*\))?', lambda m: ' .x' if not m.group(0).startswith('::') else ' e', selector)
    ids = len(re.findall(r'#[\w-]+', sel))
    classes = len(re.findall(r'\.[\w-]+', sel)) + len(re.findall(r'\[[^\]]+\]', sel))
    elements = len(re.findall(r'(?:^|[\s>+~])([a-zA-Z][\w-]*)', sel))
    return ids, classes, elements


class TestChangelistHeaderPadding(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        html = render_to_string(ASSETS, {})
        style = re.search(r'<style[^>]*>(.*?)</style>', html, re.S)
        assert style, 'testlist_assets.html has no <style> block'
        cls.rules = _parse_rules(style.group(1))

    def _top_level(self, selector):
        return [decls for at_rule, sels, decls in self.rules if not at_rule and selector in sels]

    def test_django_still_zeroes_th_padding(self):
        """The premise: Django's changelist rule takes the padding off the th itself."""
        path = finders.find('admin/css/changelists.css')
        with open(path) as fh:
            rules = _parse_rules(fh.read())
        decls = [d for _, sels, d in rules if '#changelist table thead th' in sels]
        self.assertTrue(any(d.get('padding') == '0' for d in decls))

    def test_th_rule_sets_no_dead_padding(self):
        """A padding on #result_list thead th would lose to Django's (1,0,3) rule."""
        for decls in self._top_level('#result_list thead th'):
            self.assertNotIn('padding', decls)

    def test_inner_text_element_gets_header_padding(self):
        """The padding goes on the element Django pads: th .text > a / .text > span."""
        found = [
            (sels, decls) for at_rule, sels, decls in self.rules
            if not at_rule and INNER_SELECTORS <= set(sels)
        ]
        self.assertTrue(found, 'no top-level rule targets #result_list thead th .text > a/span')
        self.assertEqual(found[0][1].get('padding'), '7px 10px')

    def test_inner_rule_outranks_django(self):
        django = max(_specificity('table thead th .text a'), _specificity('table thead th .text span'))
        for selector in INNER_SELECTORS:
            self.assertGreater(_specificity(selector), django)

    def test_sort_icons_move_with_the_label(self):
        """The label sits 1px higher than Django's, so the sort options do too."""
        decls = self._top_level('#result_list thead th.sorted .sortoptions')
        self.assertTrue(decls)
        self.assertEqual(decls[0].get('padding-top'), '8px')
        self.assertGreater(
            _specificity('#result_list thead th.sorted .sortoptions'),
            _specificity('table thead th.sorted .sortoptions'),
        )

    def test_narrow_override_still_wins(self):
        """The narrow-card rule (same selectors, later in source) keeps its 6px sides."""
        idx_base = next(
            i for i, (a, s, _) in enumerate(self.rules) if not a and INNER_SELECTORS <= set(s)
        )
        narrow = [
            (i, d) for i, (a, s, d) in enumerate(self.rules)
            if a.startswith('@container') and INNER_SELECTORS <= set(s)
        ]
        self.assertTrue(narrow)
        i, decls = narrow[0]
        self.assertGreater(i, idx_base)
        self.assertEqual(decls.get('padding-left'), '6px')
        self.assertEqual(decls.get('padding-right'), '6px')
