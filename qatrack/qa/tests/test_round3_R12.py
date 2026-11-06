"""Round 3, R12: "Assign to Machine…" is hidden in machine mode.

Assigning the list to a machine is a base-list action, so the button joins the
machine-mode hide list in testlist_assets.html alongside the other shared
settings. It is hidden by CSS only: the server still renders it when the page
opens on a machine (?unit=), so it comes back as soon as the scope dropdown
returns to the base list and initScopeSelect() drops body.tl-mode-machine.
"""

import re

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/testlist/testlist_assets.html'


def _rules(css):
    """(selectors, body) pairs for each top-level rule in `css`."""
    return [([s.strip() for s in sel.split(',')], body.strip())
            for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)]


class TestHideRule(TestCase):

    def setUp(self):
        assets = render_to_string(ASSETS, {})
        style = re.search(r'<style[^>]*>(.*?)</style>', assets, re.S).group(1)
        self.rules = _rules(re.sub(r'/\*.*?\*/', '', style, flags=re.S))

    def test_button_is_in_the_machine_mode_hide_list(self):
        rule = [body for sels, body in self.rules if 'body.tl-mode-machine #tl-btn-assign-machine' in sels]
        assert len(rule) == 1
        assert re.sub(r'\s+', ' ', rule[0]) == 'display: none !important;'
        # the same rule that hides the other shared-settings controls
        hide_list = [sels for sels, body in self.rules if 'body.tl-mode-machine #tl-header-add-test-btn' in sels][0]
        assert 'body.tl-mode-machine #tl-btn-assign-machine' in hide_list

    def test_nothing_hides_the_button_outside_machine_mode(self):
        for sels, body in self.rules:
            if 'display: none' not in body and 'visibility: hidden' not in body:
                continue
            for sel in sels:
                if 'assign-machine' in sel:
                    assert sel.startswith('body.tl-mode-machine '), sel


class TestButtonRenders(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.tl = qa_utils.create_test_list(name='Parent')
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='Output'))
        qa_utils.create_unit_test_collection(
            unit=self.unit, test_collection=self.tl, assigned_to=create_group(name='Physicists'),
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _button(self, url, params=None):
        resp = self.client.get(url, params or {})
        assert resp.status_code == 200
        return BeautifulSoup(resp.content.decode(), 'html.parser').find(id='tl-btn-assign-machine')

    def test_enabled_in_base_mode(self):
        btn = self._button(self.url)
        assert btn is not None
        assert not btn.has_attr('disabled')
        assert 'test_list=%d' % self.tl.pk in btn['data-assign-url']
        assert 'Assign to Machine' in btn.get_text()

    def test_disabled_variant_on_the_add_page(self):
        btn = self._button(reverse('admin:qa_testlist_add'))
        assert btn is not None
        assert btn.has_attr('disabled')
        assert btn['aria-disabled'] == 'true'

    def test_still_rendered_when_opened_on_a_machine(self):
        """Hidden by CSS, not left out, so switching back to the base list shows it without a reload."""
        btn = self._button(self.url, {'unit': self.unit.pk})
        assert btn is not None
        assert not btn.has_attr('disabled')
        assert not btn.has_attr('hidden')
