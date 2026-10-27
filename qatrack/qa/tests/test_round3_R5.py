"""Round 3, R5: machine mode's Reference & Tolerance pencil sits in the row's last column.

The pencil that opens the Set Reference & Tolerance dialog (or links to the
Unit Test Info page) used to be appended to the Reference & Tolerance cell.
It now goes in a ``.tl-machine-actions`` holder inside the row's actions cell,
which is shown only in machine mode, in place of the base list's buttons.
Sublist test rows get a machine-only actions column for it. These tests check
the rendered markup, the column counts, and the JS and CSS that drive it.
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

    def test_every_test_row_has_the_holder_in_its_last_cell(self):
        soup = self._soup()
        rows = soup.select('tr.tl-test-row[data-test-id], tr.tl-sublist-test-row[data-test-id]')
        assert len(rows) == 2
        for row in rows:
            last = row.find_all('td', recursive=False)[-1]
            assert 'tl-cell-actions' in last['class']
            holders = last.find_all(class_='tl-machine-actions', recursive=False)
            assert len(holders) == 1
            assert holders[0].get_text(strip=True) == ''  # filled in by the builder JS
            # the pencil is no longer rendered or kept in the Reference & Tolerance cell
            reftol = row.find('td', class_='tl-col-reftol', recursive=False)
            assert not reftol.select('.tl-machine-edit')

    def test_base_list_buttons_are_unchanged(self):
        soup = self._soup()
        actions = soup.select_one('tr.tl-test-row td.tl-cell-actions')
        assert actions.select_one('a.tl-action-icon[title="Edit Test in a New Tab"]')
        assert actions.select_one('.tl-duplicate-test-btn')
        assert actions.select_one('.tl-delete-test-btn')

    def test_sublist_table_has_a_machine_only_actions_column(self):
        soup = self._soup()
        sub = soup.select_one('table.tl-sublist-table')
        last_th = sub.find('thead').find('tr').find_all('th', recursive=False)[-1]
        assert {'tl-th-actions', 'tl-col-machine-actions'} <= set(last_th['class'])
        assert last_th.select_one('.tl-visually-hidden').get_text(strip=True) == 'Actions'
        cell = sub.select_one('tr.tl-sublist-test-row td.tl-cell-actions')
        assert 'tl-col-machine-actions' in cell['class']

    def test_column_counts_and_spans(self):
        soup = self._soup()

        def visible(table, hidden):
            return sum(1 for th in table.find('thead').find('tr').find_all('th', recursive=False)
                       if not hidden & set(th.get('class', [])))

        main = soup.find('table', id='tl-tests-table')
        # the builder table's actions column is there in both modes
        assert visible(main, {'tl-col-reftol'}) == visible(main, {'tl-col-type-value'}) == 6
        assert soup.select_one('td.tl-sublist-cell')['colspan'] == '6'
        for sub in soup.select('table.tl-sublist-table'):
            assert visible(sub, {'tl-col-reftol', 'tl-col-machine-actions'}) == 5  # base list
            assert visible(sub, {'tl-col-type-value'}) == 6  # machine mode
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

    def test_pencil_goes_in_the_actions_holder(self):
        fill = self._function('fillMachineRow')
        assert 'machineActionsBox(r)' in fill
        assert 'box.innerHTML = machineRefTolEditHtml(r, info, limits)' in fill
        assert 'cell.innerHTML = machineRefTolHtml(info, limits)' in fill
        # no longer appended to the Reference & Tolerance cell's last line
        assert 'html.replace' not in fill
        box = self._function('machineActionsBox')
        assert 'tl-cell-actions' in box and 'tl-machine-actions' in box

    def test_pencil_keeps_its_labels_and_save_first_case(self):
        edit = self._function('machineRefTolEditHtml')
        assert 'if (!info || !limits.uses_limits) { return ""; }' in edit
        assert 'title="\' + escapeHtml(setLabel) + \'" aria-label="\' + escapeHtml(setLabel)' in edit
        assert 'Set reference and tolerance for %(test)s on %(unit)s' in edit

    def test_cleared_and_focused_in_the_holder(self):
        assert '.tl-machine-actions' in self._function('clearMachineCells')
        focus = self._function('focusRefTolOpener')
        assert 'machineActionsBox(opener.row)' in focus
        assert 'machineRefTolCell' not in focus

    def test_css_hides_base_buttons_but_not_the_holder(self):
        css = re.sub(r'\s+', ' ', self.assets)
        assert 'body.tl-mode-machine #tl-tests-card .tl-cell-actions > *:not(.tl-machine-actions),' in css
        assert 'body.tl-mode-machine #tl-tests-card .tl-cell-actions > *,' not in css
        assert '.tl-machine-actions, .tl-col-machine-actions { display: none; }' in css
        assert 'body.tl-mode-machine .tl-machine-actions { display: inline; }' in css
        assert 'body.tl-mode-machine .tl-col-machine-actions { display: table-cell; }' in css
