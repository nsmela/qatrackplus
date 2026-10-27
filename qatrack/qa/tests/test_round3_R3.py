"""Round 3, R3: machine mode shows one "Reference & Tolerance" column.

Machine mode used to show a Reference and a Tolerance column, with "Not used"
filling whichever one a test type ignores. Now there is one column, filled by
fillMachineRow() in testlist_assets.html from testlist_machine_values' JSON;
what it shows depends on the type's ``limits`` (machine_limit_usage):
the tolerance only for Multiple Choice and string types, the expected value for
Boolean tests, both for numerical types, and a short note for types that never
pass or fail. These tests check the rendered columns and spans, the JS helpers
the column relies on, and that the limits data driving it is still right.
"""

import re

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/testlist/testlist_assets.html'


class TestReferenceToleranceColumn(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.tests = {
            'num': qa_utils.create_test(name='Output'),
            'bool': qa_utils.create_test(name='Door', test_type=qa_models.BOOLEAN),
            'mc': qa_utils.create_test(name='Choice', test_type=qa_models.MULTIPLE_CHOICE, choices='a,b'),
            'string': qa_utils.create_test(name='Initials', test_type=qa_models.STRING),
            'upload': qa_utils.create_test(name='Image', test_type=qa_models.UPLOAD),
        }
        self.tl = qa_utils.create_test_list(name='Parent')
        for i, t in enumerate(self.tests.values()):
            qa_utils.create_test_list_membership(test_list=self.tl, test=t, order=i)
        child = qa_utils.create_test_list(name='Child')
        qa_utils.create_test_list_membership(test_list=child, test=qa_utils.create_test(name='In Sublist'))
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=child, order=10)
        qa_utils.create_unit_test_collection(
            unit=self.unit, test_collection=self.tl, assigned_to=create_group(name='Physicists'),
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _soup(self):
        resp = self.client.get(self.url, {'unit': self.unit.pk})
        assert resp.status_code == 200
        return BeautifulSoup(resp.content.decode(), 'html.parser')

    def test_one_combined_header_in_each_table(self):
        soup = self._soup()
        heads = soup.select('th.tl-col-reftol')
        # the builder table and the sublist's read-only table
        assert len(heads) == 2
        for th in heads:
            assert th.get_text(strip=True) == 'Reference & Tolerance'
            assert 'tl-th-reftol' in th['class']
        assert not soup.select('.tl-col-ref, .tl-col-tol, .tl-th-ref, .tl-th-tol')

    def test_one_cell_per_test_row(self):
        soup = self._soup()
        rows = soup.select('tr.tl-test-row[data-test-id], tr.tl-sublist-test-row[data-test-id]')
        assert len(rows) == 6
        for row in rows:
            cells = row.find_all('td', class_='tl-col-reftol', recursive=False)
            assert len(cells) == 1
            assert cells[0].get_text(strip=True) == ''  # filled in by the builder JS

    def test_machine_mode_column_counts(self):
        """Reference & Tolerance swaps in for Type Value, so both modes show the same number."""
        soup = self._soup()

        def visible(table, hidden):
            return sum(1 for th in table.find('thead').find('tr').find_all('th', recursive=False)
                       if not hidden & set(th.get('class', [])))

        main = soup.find('table', id='tl-tests-table')
        assert visible(main, {'tl-col-reftol'}) == visible(main, {'tl-col-type-value'}) == 6
        sub = soup.select_one('table.tl-sublist-table')
        assert visible(sub, {'tl-col-reftol'}) == visible(sub, {'tl-col-type-value'}) == 5
        assert soup.select_one('td.tl-sublist-cell')['colspan'] == '6'

    def test_limits_data_still_drives_the_column(self):
        resp = self.client.get(reverse('admin:qa_testlist_machine_values'), {
            'unit': self.unit.pk,
            'tests': ','.join(str(t.pk) for t in self.tests.values()),
        })
        limits = resp.json()['limits']
        by_key = {k: limits[str(t.pk)] for k, t in self.tests.items()}
        assert by_key['num'] == {'uses_limits': True, 'reference': 'required', 'tolerance': 'required'}
        assert by_key['bool'] == {'uses_limits': True, 'reference': 'required', 'tolerance': 'optional'}
        assert by_key['mc'] == {'uses_limits': True, 'reference': 'unused', 'tolerance': 'required'}
        assert by_key['string'] == by_key['mc']
        assert by_key['upload'] == {'uses_limits': False, 'reference': 'unused', 'tolerance': 'unused'}
        assert qa_admin.machine_limit_usage(qa_utils.create_test(name='When', test_type=qa_models.DATE)) == \
            by_key['upload']


class TestReferenceToleranceScript(TestCase):

    def setUp(self):
        self.assets = render_to_string(ASSETS, {})

    def _function(self, name):
        match = re.search(r'\n  function %s\(.*?\n  }\n' % name, self.assets, re.S)
        assert match, name
        return match.group(0)

    def test_css_shows_the_column_only_in_machine_mode(self):
        css = re.sub(r'\s+', ' ', self.assets)
        assert '.tl-col-reftol { display: none; }' in css
        assert 'body.tl-mode-machine .tl-col-reftol { display: table-cell; }' in css
        assert '.tl-col-ref,' not in css and '.tl-col-tol {' not in css

    def test_cell_text_depends_on_the_type(self):
        js = self._function('machineRefTolHtml')
        # types that never pass or fail: one neutral note, not "Not used" twice
        assert 'gettext("No limits needed")' in js
        assert 'Not used' not in js
        # no reference (Multiple Choice, string types): tolerance only
        assert 'limits.reference === "unused"' in js
        # Boolean: "Expected", numerical types: "Reference" and "Tolerance"
        assert 'gettext("Expected")' in js
        assert 'gettext("Reference")' in js
        assert 'gettext("Tolerance")' in js
        # rows the unit has no UnitTestInfo for yet keep the save hint
        assert 'gettext("Save the test list first")' in js
        # values still go through machineValueHtml, which marks missing required ones "Not set"
        assert 'machineValueHtml(info.reference, limits.reference)' in js
        assert 'machineValueHtml(info.tolerance, limits.tolerance' in js

    def test_pencil_is_built_by_its_own_helper(self):
        edit = self._function('machineRefTolEditHtml')
        assert 'tl-machine-reftol-btn' in edit
        assert 'data-reftol-url' in edit
        assert 'scopeMsg("edit-uti")' in edit  # the Unit Test Info link when the dialog isn't available
        fill = self._function('fillMachineRow')
        assert 'machineRefTolCell(r)' in fill
        assert 'machineRefTolHtml(info, limits)' in fill
        assert 'machineRefTolEditHtml(r, info, limits)' in fill
        # focus goes back to the pencil in the combined cell after a save
        assert 'machineRefTolCell(opener.row)' in self._function('focusRefTolOpener')
        assert 'td.tl-col-reftol' in self._function('clearMachineCells')

    def test_new_strings_are_translatable(self):
        for s in ('No limits needed', 'Expected', 'Reference', 'Tolerance'):
            assert '"%s": "%s"' % (s, s) in self.assets, s
