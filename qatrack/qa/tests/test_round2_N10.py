"""Round 2, N10: the builder's "Repeats: … and N more" note is plural-aware.

The note is built in the builder JS (testlist_assets.html). Its singular and
plural English text are the same, so the template renders both translated forms
from one plural msgid into the TL_PLURALS table, and the JS picks one with the
active language's plural rule (window.pluralidx from Django's JS catalogue).
"""

import re
from unittest import mock

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from qatrack.qa.tests import utils

MSGID = 'Repeats: %(tests)s and %(count)s more'
ASSETS = 'admin/qa/testlist/testlist_assets.html'


def _plural_forms(html):
    """Return the two rendered forms of the "and N more" entry in TL_PLURALS."""
    match = re.search(
        r'var TL_PLURALS = \{\s*"Repeats: %\(tests\)s and %\(count\)s more": \[\s*"([^"]*)",\s*"([^"]*)"\s*\]',
        html,
    )
    assert match, 'TL_PLURALS entry for the repeat note was not rendered'
    return match.group(1), match.group(2)


class TestRepeatNotePlurals(TestCase):

    def test_english_forms_keep_placeholders(self):
        with translation.override('en'):
            one, other = _plural_forms(render_to_string(ASSETS, {}))
        # English output is unchanged: "and 1 more" and "and 2 more" both come
        # from the same text once interpolate() fills %(count)s.
        assert one == MSGID
        assert other == MSGID

    def test_forms_come_from_one_plural_msgid(self):
        """Counter 1 picks the singular form and counter 2 the plural form."""
        calls = []

        def fake_ngettext(singular, plural, number):
            calls.append((singular, plural, number))
            return ('ONE %(tests)s / %(count)s' if number == 1 else 'MANY %(tests)s / %(count)s')

        with mock.patch.object(translation, 'ngettext', fake_ngettext):
            one, other = _plural_forms(render_to_string(ASSETS, {}))

        assert one == 'ONE %(tests)s / %(count)s'
        assert other == 'MANY %(tests)s / %(count)s'
        assert (MSGID, MSGID, 1) in calls
        assert (MSGID, MSGID, 2) in calls

    def test_js_uses_ngettext_and_pluralidx(self):
        html = render_to_string(ASSETS, {})
        assert 'window.pluralidx' in html
        assert 'hasOwn.call(TL_PLURALS, s)' in html
        assert 'interpolate(ngettext("Repeats: %(tests)s and %(count)s more"' in html
        # The old gettext-only lookup (no plural handling) is gone.
        assert 'gettext("Repeats: %(tests)s and %(count)s more")' not in html.replace('ngettext("Repeats', '')

    def test_change_page_renders_table(self):
        user = User.objects.create_superuser('n10admin', 'n10@example.com', 'pw')
        self.client.force_login(user)
        tl = utils.create_test_list('N10 list')
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,)))
        assert resp.status_code == 200
        one, other = _plural_forms(resp.content.decode())
        assert one == other == MSGID
