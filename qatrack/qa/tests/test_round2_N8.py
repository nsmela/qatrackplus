"""Round 2, N8: on narrow screens the Test List filter groups start collapsed.

Below the max-width: 1024px breakpoint the filter card stacks above the results,
so the builder JS (initFilterCollapse() in testlist_assets.html) closes the filter
groups on page load, gated by matchMedia. It keeps a group open when a choice other
than "All" is selected in it, or when Django's admin/js/filters.js remembers the
person opening it. The behaviour itself runs in the browser; these tests pin the
server-side pieces it relies on.
"""

import os
import re

import django
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from qatrack.qa.tests import utils

BREAKPOINT = '(max-width: 1024px)'


def _filter_groups(html):
    """Return {filter title: [li class attributes]} for each <details> filter group."""
    groups = {}
    for title, body in re.findall(r'<details data-filter-title="([^"]*)"[^>]*>(.*?)</details>', html, re.S):
        groups[title] = re.findall(r'<li\s*(?:class="([^"]*)")?\s*>', body)
    return groups


class TestFilterCollapseOnNarrowScreens(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('n8admin', 'n8@example.com', 'secret')
        self.client.force_login(self.user)
        utils.create_test_list('N8 list')
        self.url = reverse('admin:qa_testlist_changelist')

    def _get(self, query=''):
        resp = self.client.get(self.url + query)
        assert resp.status_code == 200
        return resp.content.decode()

    def test_script_is_on_the_page_and_runs_before_results_sizing(self):
        html = self._get()
        assert 'function initFilterCollapse()' in html
        # Called in both start-up paths, before initResultsScroll() measures the card.
        calls = re.findall(r'initFilterCollapse\(\);\s*initResultsScroll\(\);', html)
        assert len(calls) == 2

    def test_gated_on_the_same_breakpoint_as_the_stacked_filter_css(self):
        html = self._get()
        body = html[html.index('function initFilterCollapse()'):]
        body = body[:body.index('\n  }\n')]
        assert 'window.matchMedia("%s")' % BREAKPOINT in body
        # The CSS rule that stacks the filter card above the results uses that width.
        css = re.search(r'@media %s \{(.*?)\n\}' % re.escape(BREAKPOINT), html, re.S)
        assert css and '#changelist.filtered > #changelist-filter { grid-column:1; grid-row:1;' in css.group(1)

    def test_respects_filters_js_memory(self):
        html = self._get()
        assert "admin/js/filters.js" in html
        body = html[html.index('function initFilterCollapse()'):]
        assert 'sessionStorage.getItem("django.admin.filtersState")' in body
        # The key the script reads is the one Django's filters.js writes.
        filters_js = os.path.join(os.path.dirname(django.__file__), 'contrib', 'admin', 'static', 'admin', 'js',
                                  'filters.js')
        with open(filters_js) as f:
            assert "'django.admin.filtersState'" in f.read()

    def test_unfiltered_every_group_has_all_first_and_selected(self):
        """The script treats a group as inactive when its first choice ("All") is selected."""
        groups = _filter_groups(self._get())
        assert groups, 'no <details data-filter-title> filter groups rendered'
        for title, classes in groups.items():
            assert classes and classes[0] == 'selected', title
            assert 'selected' not in classes[1:], title

    def test_active_filter_group_is_detectable(self):
        groups = _filter_groups(self._get('?activeutcs=hasactiveutcs'))
        active = [title for title, classes in groups.items() if classes[0] != 'selected']
        assert active == ['Active Unit Assignments']
        assert 'selected' in groups['Active Unit Assignments'][1:]
