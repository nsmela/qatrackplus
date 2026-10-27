"""Round 3, R11: machine mode's pencil leads the Reference & Tolerance cell.

In machine mode the Set Reference & Tolerance pencil no longer has a column of
its own (R5's layout). fillMachineRow() in testlist_assets.html writes it at
the start of the row's Reference & Tolerance cell, before the values, in a slot
that keeps its width on rows without a pencil so the values line up. The
builder table's actions column (Edit, Duplicate, Remove) is hidden in machine
mode, and sublist tables have no actions column at all. These tests check the
rendered columns and spans, and the JS and CSS that build the cell.
"""

import re

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/testlist/testlist_assets.html'


def _visible(table, hidden):
    """Header cells left in `table` once the classes in `hidden` are hidden."""
    return [th for th in table.find('thead').find('tr').find_all('th', recursive=False)
            if not hidden & set(th.get('class', []))]


MACHINE_HIDDEN = {'tl-col-type-value', 'tl-col-actions'}
BASE_HIDDEN = {'tl-col-reftol'}


class TestMachineModeColumns(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.tl = qa_utils.create_test_list(name='Parent')
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='Output'), order=0)
        child = qa_utils.create_test_list(name='Child')
        qa_utils.create_test_list_membership(test_list=child, test=qa_utils.create_test(name='In Sublist'))
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=child, order=10)
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=qa_utils.create_test_list(name='Empty'),
                                order=11)
        qa_utils.create_unit_test_collection(
            unit=self.unit, test_collection=self.tl, assigned_to=create_group(name='Physicists'),
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _soup(self):
        resp = self.client.get(self.url, {'unit': self.unit.pk})
        assert resp.status_code == 200
        return BeautifulSoup(resp.content.decode(), 'html.parser')

    def test_builder_actions_column_is_marked_base_only(self):
        soup = self._soup()
        main = soup.find('table', id='tl-tests-table')
        last_th = main.find('thead').find('tr').find_all('th', recursive=False)[-1]
        assert {'tl-th-actions', 'tl-col-actions'} <= set(last_th['class'])
        cell = soup.select_one('tr.tl-test-row').find_all('td', recursive=False)[-1]
        assert {'tl-cell-actions', 'tl-col-actions'} <= set(cell['class'])
        # the base list's buttons are still rendered for the base list
        assert cell.select_one('.tl-duplicate-test-btn')
        assert cell.select_one('.tl-delete-test-btn')

    def test_reference_and_tolerance_is_the_last_column_in_machine_mode(self):
        soup = self._soup()
        tables = [soup.find('table', id='tl-tests-table')] + soup.select('table.tl-sublist-table')
        for table in tables:
            shown = _visible(table, MACHINE_HIDDEN)
            assert 'tl-col-reftol' in shown[-1]['class']
            assert not any('tl-th-actions' in th['class'] for th in shown)

    def test_column_counts_and_spans(self):
        soup = self._soup()
        main = soup.find('table', id='tl-tests-table')
        assert len(_visible(main, BASE_HIDDEN)) == 6
        assert len(_visible(main, MACHINE_HIDDEN)) == 5
        for sub in soup.select('table.tl-sublist-table'):
            assert len(_visible(sub, BASE_HIDDEN)) == len(_visible(sub, MACHINE_HIDDEN)) == 5
        # the server renders base-mode spans; syncColumnSpans() recounts them in machine mode
        for td in soup.select('td.tl-sublist-cell'):
            assert td['colspan'] == '6'
            assert 'tl-span-visible-cols' in td['class']
        empty = soup.select_one('td.tl-empty-sublist-msg')
        assert empty['colspan'] == '5'

    def test_no_separate_pencil_holder_or_column(self):
        soup = self._soup()
        assert not soup.select('.tl-machine-actions, .tl-col-machine-actions')
        for row in soup.select('tr.tl-sublist-test-row'):
            assert 'tl-col-reftol' in row.find_all('td', recursive=False)[-1]['class']


class TestPencilInTheReferenceToleranceCell(TestCase):

    def setUp(self):
        self.assets = render_to_string(ASSETS, {})
        self.css = re.sub(r'\s+', ' ', self.assets)

    def _function(self, name):
        match = re.search(r'\n  function %s\(.*?\n  }\n' % name, self.assets, re.S)
        assert match, name
        return match.group(0)

    def test_pencil_comes_before_the_values(self):
        fill = self._function('fillMachineRow')
        edit_at = fill.index('machineRefTolEditHtml(r, info, limits)')
        values_at = fill.index('machineRefTolHtml(info, limits)')
        assert edit_at < values_at
        assert fill.index('tl-reftol-edit') < fill.index('tl-reftol-values')
        assert 'tl-reftol-wrap' in fill
        assert 'cell.innerHTML' in fill

    def test_pencil_slot_is_always_written(self):
        """Rows without a pencil still get the (empty) slot, so their values line up."""
        fill = self._function('fillMachineRow')
        assert re.search(r"'<span class=\"tl-reftol-edit\">' \+ machineRefTolEditHtml\(", fill)
        # and the helper still returns nothing for those rows
        edit = self._function('machineRefTolEditHtml')
        assert 'if (!info || !limits.uses_limits) { return ""; }' in edit

    def test_pencil_keeps_its_labels_and_fallback_link(self):
        edit = self._function('machineRefTolEditHtml')
        assert 'Set reference and tolerance for %(test)s on %(unit)s' in edit
        assert 'title="\' + escapeHtml(setLabel) + \'" aria-label="\' + escapeHtml(setLabel)' in edit
        assert 'aria-haspopup="dialog"' in edit
        assert 'scopeMsg("edit-uti")' in edit  # the Unit Test Info link when the dialog isn't available

    def test_focus_returns_to_the_pencil_in_the_cell(self):
        focus = self._function('focusRefTolOpener')
        assert 'machineRefTolCell(opener.row)' in focus
        assert '.tl-machine-reftol-btn' in focus
        assert 'machineActionsBox' not in self.assets

    def test_clearing_empties_the_cell(self):
        clear = self._function('clearMachineCells')
        assert '"#tl-tests-card td.tl-col-reftol"' in clear

    def test_css_lays_the_cell_out_pencil_first(self):
        assert '.tl-reftol-wrap { display: flex; align-items: flex-start; gap: 4px; }' in self.css
        assert '.tl-reftol-edit { flex: 0 0 24px;' in self.css
        assert '.tl-reftol-values { flex: 1 1 auto; min-width: 0; }' in self.css
        assert '.tl-reftol-edit .tl-machine-edit { margin-left: 0; }' in self.css

    def test_css_hides_the_actions_column_in_machine_mode(self):
        assert 'body.tl-mode-machine .tl-col-actions { display: none; }' in self.css
        assert 'tl-machine-actions' not in self.css
        assert 'tl-col-machine-actions' not in self.css
