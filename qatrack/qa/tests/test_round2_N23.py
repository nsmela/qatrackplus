"""Test pack export/import pages: translatable JS labels and "…" loading text."""

import re

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from qatrack.qa.tests import utils


class TestTestPackPagesI18n(TestCase):

    def setUp(self):
        self.user = utils.create_user(is_superuser=True, uname="admin_n23", pwd="pwd")
        self.client.force_login(self.user)

    def _get(self, name):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_pages_load_js_catalogue_before_script(self):
        """The JS catalogue must load before the test pack script so gettext() is translated."""
        jsi18n = reverse('admin:jsi18n')
        for name, script in (('admin:qa_export_testpack', 'js/testpack-export.js'),
                             ('admin:qa_import_testpack', 'js/testpack-import.js')):
            html = self._get(name)
            self.assertIn('src="%s"' % jsi18n, html)
            self.assertIn(script, html)
            self.assertLess(html.index('src="%s"' % jsi18n), html.index(script))

    def test_loading_text_uses_ellipsis(self):
        for name in ('admin:qa_export_testpack', 'admin:qa_import_testpack'):
            html = self._get(name)
            self.assertIn('Loading Test List table…', html)
            self.assertIn('Loading Test List Cycle table…', html)
            self.assertIn('Loading Test table…', html)
            self.assertNotIn('table...', html)

    def test_js_catalogue_provides_gettext_helpers(self):
        response = self.client.get(reverse('admin:jsi18n'))
        self.assertEqual(response.status_code, 200)
        js = response.content.decode()
        for fn in ('gettext', 'ngettext', 'interpolate'):
            self.assertIn('django.%s' % fn, js)

    def test_js_labels_go_through_gettext(self):
        """User-facing labels in the test pack scripts are wrapped in gettext()/ngettext()."""
        for script in ('js/testpack-export.js', 'js/testpack-import.js'):
            path = finders.find(script)
            self.assertTrue(path and 'admin_media' in path, path)
            with open(path, encoding='utf-8') as f:
                js = f.read()
            for label in ('All', 'Select Filtered', 'Select All', 'Select None'):
                self.assertIn('gettext("%s")' % label, js)
            self.assertIn('ngettext("%(count)s Selected"', js)
            # the old hard-coded English labels are gone
            self.assertNotIn('"Select all items"', js)
            self.assertNotIn('"Select none"', js)
            self.assertIsNone(re.search(r'\+\s*" Selected"', js))
