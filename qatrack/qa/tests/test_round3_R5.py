"""Round 3, R5 (since replaced by R11): where machine mode's Reference & Tolerance pencil goes.

R5 moved the pencil that opens the Set Reference & Tolerance dialog (or links
to the Unit Test Info page) into a ``.tl-machine-actions`` holder in the row's
actions cell, with a machine-only actions column in sublist tables. R11
replaced that layout: the pencil leads the Reference & Tolerance cell and
machine mode has no actions column at all (see test_round3_R11.py). The tests
below were updated to check that the R5 holder and column are gone, and that
the base list's actions column is unchanged.
"""

import re

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/testlist/testlist_assets.html'


class TestMachinePencilColumnMarkup(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.tl = qa_utils.create_test_list(name='Parent')
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='Output'), order=0)
        child = qa_utils.create_test_list(name='Child')
        qa_utils.create_test_list_membership(test_list=child, test=qa_utils.create_test(name='In Sublist'))
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=child, order=10)
        self.empty_child = qa_utils.create_test_list(name='Empty Child')
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=self.empty_child, order=11)
        qa_utils.create_unit_test_collection(
            unit=self.unit, test_collection=self.tl, assigned_to=create_group(name='Physicists'),
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _soup(self):
        resp = self.client.get(self.url, {'unit': self.unit.pk})
        assert resp.status_code == 200
        return BeautifulSoup(resp.content.decode(), 'html.parser')

    def test_no_test_row_has_a_pencil_holder_in_its_actions_cell(self):
        soup = self._soup()
        rows = soup.select('tr.tl-test-row[data-test-id], tr.tl-sublist-test-row[data-test-id]')
        assert len(rows) == 2
        assert not soup.select('.tl-machine-actions')
        for row in rows:
            # the Reference & Tolerance cell is rendered empty; the builder JS fills it, pencil first (R11)
            reftol = row.find('td', class_='tl-col-reftol', recursive=False)
            assert reftol.get_text(strip=True) == ''

    def test_base_list_buttons_are_unchanged(self):
        soup = self._soup()
        actions = soup.select_one('tr.tl-test-row td.tl-cell-actions')
        assert actions.select_one('a.tl-action-icon[title="Edit Test in a New Tab"]')
        assert actions.select_one('.tl-duplicate-test-btn')
        assert actions.select_one('.tl-delete-test-btn')

    def test_sublist_table_has_no_actions_column(self):
        soup = self._soup()
        sub = soup.select_one('table.tl-sublist-table')
        last_th = sub.find('thead').find('tr').find_all('th', recursive=False)[-1]
        assert 'tl-col-reftol' in last_th['class']
        assert not sub.select('.tl-th-actions, .tl-cell-actions, .tl-col-machine-actions')

    def test_column_counts_and_spans(self):
        soup = self._soup()

        def visible(table, hidden):
            return sum(1 for th in table.find('thead').find('tr').find_all('th', recursive=False)
                       if not hidden & set(th.get('class', [])))

        main = soup.find('table', id='tl-tests-table')
        # R11: the builder table's actions column is hidden in machine mode
        assert visible(main, {'tl-col-reftol'}) == 6
        assert visible(main, {'tl-col-type-value', 'tl-col-actions'}) == 5
        assert soup.select_one('td.tl-sublist-cell')['colspan'] == '6'
        for sub in soup.select('table.tl-sublist-table'):
            assert visible(sub, {'tl-col-reftol'}) == 5  # base list
            assert visible(sub, {'tl-col-type-value'}) == 5  # machine mode
        # an empty sublist's message spans the base count; syncColumnSpans() recounts it
        empty = soup.select_one('td.tl-empty-sublist-msg')
        assert empty['colspan'] == '5'
        assert 'tl-span-visible-cols' in empty['class']


class TestMachinePencilColumnScript(TestCase):

    def setUp(self):
        self.assets = render_to_string(ASSETS, {})

    def _function(self, name):
        match = re.search(r'\n  function %s\(.*?\n  }\n' % name, self.assets, re.S)
        assert match, name
        return match.group(0)

    def test_pencil_no_longer_goes_in_an_actions_holder(self):
        fill = self._function('fillMachineRow')
        assert 'machineActionsBox' not in self.assets
        assert 'tl-machine-actions' not in self.assets
        # R11: pencil and values both go in the Reference & Tolerance cell
        assert 'machineRefTolEditHtml(r, info, limits)' in fill
        assert 'machineRefTolHtml(info, limits)' in fill
        # not appended to the Reference & Tolerance cell's last line either
        assert 'html.replace' not in fill

    def test_pencil_keeps_its_labels_and_save_first_case(self):
        edit = self._function('machineRefTolEditHtml')
        assert 'if (!info || !limits.uses_limits) { return ""; }' in edit
        assert 'title="\' + escapeHtml(setLabel) + \'" aria-label="\' + escapeHtml(setLabel)' in edit
        assert 'Set reference and tolerance for %(test)s on %(unit)s' in edit

    def test_cleared_and_focused_in_the_reftol_cell(self):
        assert '.tl-machine-actions' not in self._function('clearMachineCells')
        focus = self._function('focusRefTolOpener')
        assert 'machineRefTolCell(opener.row)' in focus

    def test_css_hides_the_whole_actions_column_in_machine_mode(self):
        css = re.sub(r'\s+', ' ', self.assets)
        assert 'body.tl-mode-machine .tl-col-actions { display: none; }' in css
        assert '.tl-cell-actions > *:not(.tl-machine-actions)' not in css
        assert '.tl-col-machine-actions' not in css
