"""Round 2, N7: full-width rows in the builder span only the columns that are shown.

The builder's tests table (and each sublist's read-only table) has a Type Value
column for the base list and Reference / Tolerance columns for machine mode;
CSS hides whichever set doesn't apply (`body.tl-mode-machine`). Hidden cells
aren't part of the table grid, so a colspan that counted them made phantom
columns past the last header.

The server renders the base-mode spans. Machine mode is switched in the
browser, so syncColumnSpans() in testlist_assets.html recounts them there; the
tests below check the rendered base-mode spans, that the machine-mode count is
what the JS will find, and that the JS hook is wired to both mode switches.
"""

import re

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/testlist/testlist_assets.html'

# Which header cells the builder CSS hides in each mode (see the
# "Reference / Tolerance columns replace Type Value" rules, checked below).
HIDDEN_IN = {
    'base': {'tl-col-ref', 'tl-col-tol'},
    'machine': {'tl-col-type-value'},
}


def _visible_columns(table, mode):
    head = table.find('thead').find('tr')
    count = 0
    for th in head.find_all('th', recursive=False):
        if HIDDEN_IN[mode] & set(th.get('class', [])):
            continue
        count += int(th.get('colspan', 1))
    return count


def _owning_table(td):
    return td.find_parent('table')


class TestSublistRowSpans(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.parent = qa_utils.create_test_list(name='Parent List')
        qa_utils.create_test_list_membership(test_list=self.parent, test=qa_utils.create_test(name='test one'))
        self.full = qa_utils.create_test_list(name='Child With Tests')
        qa_utils.create_test_list_membership(test_list=self.full, test=qa_utils.create_test(name='test two'))
        self.empty = qa_utils.create_test_list(name='Empty Child')
        qa_utils.create_sublist(parent_test_list=self.parent, child_test_list=self.full, order=1)
        qa_utils.create_sublist(parent_test_list=self.parent, child_test_list=self.empty, order=2)
        self.url = reverse('admin:qa_testlist_change', args=(self.parent.pk,))

    def _soup(self, url, params=None):
        resp = self.client.get(url, params or {})
        assert resp.status_code == 200
        return BeautifulSoup(resp.content.decode(), 'html.parser')

    def test_builder_table_visible_column_counts(self):
        table = self._soup(self.url).find('table', id='tl-tests-table')
        assert _visible_columns(table, 'base') == 6
        assert _visible_columns(table, 'machine') == 7

    def test_sublist_rows_span_the_base_mode_columns(self):
        soup = self._soup(self.url)
        cells = soup.select('#tl-tests-tbody td.tl-sublist-cell')
        assert len(cells) == 2
        for td in cells:
            table = _owning_table(td)
            assert table.get('id') == 'tl-tests-table'
            assert int(td['colspan']) == _visible_columns(table, 'base')
            # marked for syncColumnSpans(), which makes it span the machine-mode columns
            assert 'tl-span-visible-cols' in td['class']

    def test_empty_sublist_message_spans_its_table_columns(self):
        soup = self._soup(self.url)
        msgs = soup.select('td.tl-empty-sublist-msg')
        assert len(msgs) == 1
        td = msgs[0]
        table = _owning_table(td)
        assert 'tl-sublist-table' in table['class']
        assert int(td['colspan']) == _visible_columns(table, 'base') == 5
        assert _visible_columns(table, 'machine') == 6
        assert 'tl-span-visible-cols' in td['class']

    def test_no_cell_spans_past_the_shown_columns(self):
        """Every colspan on the page fits the columns its table shows in base mode."""
        soup = self._soup(self.url, {'unit': '1'})  # ?unit= changes nothing server-side
        for td in soup.select('#tl-tests-card td[colspan]'):
            table = _owning_table(td)
            assert int(td['colspan']) <= _visible_columns(table, 'base'), td

    def test_added_sublist_card_uses_the_same_spans(self):
        url = reverse('admin:qa_testlist_add_sublist_card')
        resp = self.client.get(url, {'child_id': self.empty.pk, 'index': 3, 'parent_id': self.parent.pk})
        assert resp.status_code == 200
        soup = BeautifulSoup(resp.content.decode(), 'html.parser')
        assert soup.select_one('td.tl-sublist-cell')['colspan'] == '6'
        assert 'tl-span-visible-cols' in soup.select_one('td.tl-sublist-cell')['class']
        msg = soup.select_one('td.tl-empty-sublist-msg')
        assert int(msg['colspan']) == _visible_columns(_owning_table(msg), 'base')

    def test_template_comment_is_not_rendered(self):
        content = self.client.get(self.url).content.decode()
        assert 'syncColumnSpans' not in content.split('<script', 1)[0]


class TestSyncColumnSpansScript(TestCase):

    def setUp(self):
        self.assets = render_to_string(ASSETS, {})

    def test_css_hides_the_columns_the_counts_assume(self):
        css = re.sub(r'\s+', ' ', self.assets)
        assert '.tl-col-ref, .tl-col-tol { display: none; }' in css
        assert 'body.tl-mode-machine .tl-col-type-value { display: none; }' in css

    def test_js_recounts_on_both_mode_switches_and_new_rows(self):
        js = self.assets
        assert 'function syncColumnSpans(root)' in js
        assert re.search(r'classList\.remove\("tl-mode-machine"\);\s*syncColumnSpans\(\);', js)
        assert re.search(r'classList\.add\("tl-mode-machine"\);\s*syncColumnSpans\(\);', js)
        assert 'syncColumnSpans(node)' in js
        assert 'td.tl-span-visible-cols' in js
