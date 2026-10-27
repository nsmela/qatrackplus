"""admin/change_list.html: Django 4.2's filters.js is loaded (collapsed filter
groups are remembered) and the formset error note is plural-aware."""
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils

FILTERS_JS = 'admin/js/filters.js'
ONE_ERROR = 'Please correct the error below.'
MANY_ERRORS = 'Please correct the errors below.'


class TestChangeListFiltersJs(TestCase):

    def setUp(self):
        create_user(uname='n22', pwd='pwd')
        self.client.login(username='n22', password='pwd')
        # Empty changelists render no filter sidebar, so give each one a row.
        qa_utils.create_unit_type()
        qa_utils.create_test_list()
        qa_utils.create_test()

    def _assert_filters_js(self, url):
        resp = self.client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'id="changelist-filter"' in html
        assert 'data-filter-title=' in html
        assert FILTERS_JS in html
        # Deferred, as Django does, so it runs after the filter sidebar exists.
        tag = html[html.rindex('<script', 0, html.index(FILTERS_JS)):html.index(FILTERS_JS) + 40]
        assert 'defer' in tag

    def test_unittype_changelist_loads_filters_js(self):
        self._assert_filters_js(reverse('admin:units_unittype_changelist'))

    def test_filtered_changelist_loads_filters_js(self):
        self._assert_filters_js(reverse('admin:units_unittype_changelist') + '?collapse__exact=1')

    def test_test_changelist_loads_filters_js(self):
        self._assert_filters_js(reverse('admin:qa_test_changelist'))

    def test_testlist_changelist_loads_filters_js(self):
        self._assert_filters_js(reverse('admin:qa_testlist_changelist'))

    def test_no_dead_flex_coltype(self):
        resp = self.client.get(reverse('admin:units_unittype_changelist'))
        assert 'id="content" class="flex"' not in resp.content.decode()


class TestChangeListErrorNotePlural(TestCase):
    """UnitTypeAdmin has list_editable = ['unit_class', 'vendor', 'collapse']."""

    def setUp(self):
        create_user(uname='n22', pwd='pwd')
        self.client.login(username='n22', password='pwd')
        self.ut = qa_utils.create_unit_type()
        self.url = reverse('admin:units_unittype_changelist')

    def _post(self, unit_class, vendor):
        data = {
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(self.ut.pk),
            'form-0-unit_class': unit_class,
            'form-0-vendor': vendor,
            '_save': 'Save',
        }
        resp = self.client.post(self.url, data)
        assert resp.status_code == 200
        return resp.content.decode()

    def test_one_error_is_singular(self):
        html = self._post('999999', '')
        assert ONE_ERROR in html
        assert MANY_ERRORS not in html

    def test_two_errors_are_plural(self):
        html = self._post('999999', '999999')
        assert MANY_ERRORS in html
        assert ONE_ERROR not in html

    def test_template_uses_blocktranslate_count(self):
        """Languages with more than two plural forms need ngettext, not an == 1 check."""
        src = (Path(settings.PROJECT_ROOT) / 'templates' / 'admin' / 'change_list.html').read_text(encoding='utf-8')
        assert '{% blocktranslate count counter=cl.formset.total_error_count %}' in src
        assert 'total_error_count == 1' not in src

    def test_snippet_pluralises(self):
        tpl = Template(
            '{% load i18n %}{% blocktranslate count counter=n %}Please correct the error below.'
            '{% plural %}Please correct the errors below.{% endblocktranslate %}'
        )
        assert tpl.render(Context({'n': 1})) == ONE_ERROR
        assert tpl.render(Context({'n': 2})) == MANY_ERRORS

