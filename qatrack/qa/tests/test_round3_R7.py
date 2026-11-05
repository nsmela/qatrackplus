"""Round 3, R7: the builder's test description dialog is gone.

A test's description is edited on the Test's own page. In each builder row the
Test cell (the name and the description) links there in a new tab, like the
row's pencil; the description itself is plain text, and blank when the test
has none. Users who can't change tests just see the text.
"""
import re

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.template.loader import get_template
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils

CELL_LINK = re.compile(r'<a href="[^"]*" target="_blank" rel="noopener" class="tl-test-link"[^>]*>.*?</a>', re.S)
DESC = re.compile(r'<div class="tl-test-desc">.*?</div>', re.S)


class TestDescriptionDialogRemoved(TestCase):

    def test_endpoint_url_gone(self):
        with pytest.raises(NoReverseMatch):
            reverse('admin:qa_testlist_test_desc_modal')

    def test_old_path_not_routed(self):
        user = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.force_login(user)
        test = qa_utils.create_test(name='r7 gone')
        resp = self.client.get('/admin/qa/testlist/test-desc-modal/', {'test_id': test.pk, 'index': 0})
        # falls through to the test list change view, which finds no test list with that "id"
        assert b'tl-desc-modal-backdrop' not in resp.content
        assert resp.status_code in (302, 404)

    def test_dialog_template_gone(self):
        from django.template import TemplateDoesNotExist
        with pytest.raises(TemplateDoesNotExist):
            get_template('admin/qa/testlist/partials/_test_desc_modal.html')

    def test_builder_script_has_no_description_dialog_code(self):
        user = create_user(is_superuser=True, uname='super2', pwd='pwd')
        self.client.force_login(user)
        tl = qa_utils.create_test_list(name='r7 script list')
        content = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,))).content.decode()
        for gone in ('tl-desc-modal-backdrop', 'tl-modal-desc-input', 'tl-desc-error-msg', 'tl-desc-submit',
                     'tl-add-desc-btn', 'test-desc-modal', "Couldn't save the description"):
            assert gone not in content, gone


class TestDescriptionLinks(TestCase):

    def setUp(self):
        self.superuser = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.limited = create_user(is_superuser=False, uname='limited', pwd='pwd')
        # full test list permissions, but none on Test itself
        cts = ContentType.objects.get_for_models(
            qa_models.TestList, qa_models.TestListMembership, qa_models.Sublist,
        ).values()
        self.limited.user_permissions.add(*Permission.objects.filter(content_type__in=cts))
        self.with_desc = qa_utils.create_test(name='Output Constancy 6X')
        self.with_desc.description = '<b>Measure</b> output'
        self.with_desc.save()
        self.no_desc = qa_utils.create_test(name='Door Interlock')
        self.no_desc.description = ''
        self.no_desc.save()
        self.tl = qa_utils.create_test_list(name='r7 list')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.with_desc, order=0)
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.no_desc, order=1)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))
        self.row_url = reverse('admin:qa_testlist_add_test_row')

    def edit_url(self, test):
        return reverse('admin:qa_test_change', args=[test.pk])

    def change_page(self, user):
        self.client.force_login(user)
        resp = self.client.get(self.change_url)
        assert resp.status_code == 200
        return resp.content.decode()

    def add_row(self, user, test):
        self.client.force_login(user)
        resp = self.client.get(self.row_url, {'test_id': test.pk, 'index': 5})
        assert resp.status_code == 200
        return resp.content.decode()

    def cell_link(self, html, test):
        links = [link for link in CELL_LINK.findall(html) if 'href="%s"' % self.edit_url(test) in link]
        assert len(links) == 1
        link = links[0]
        assert 'title="Edit %s (opens in a new tab)"' % test.name in link
        assert '<div class="tl-test-name" title="%s">%s</div>' % (test.slug, test.name) in link
        assert '<span class="tl-visually-hidden">(opens in a new tab)</span>' in link
        assert 'hx-' not in link
        assert 'aria-haspopup' not in link
        return link

    def assert_desc_in_link(self, html, test):
        link = self.cell_link(html, test)
        desc = DESC.search(link)
        assert desc and '<span>Measure output</span>' in desc.group(0)

    def assert_blank_desc_in_link(self, html, test):
        link = self.cell_link(html, test)
        assert 'tl-test-desc"' not in link
        assert 'Add Description' not in link

    def test_description_is_not_its_own_link(self):
        html = self.change_page(self.superuser)
        assert not re.search(r'<a [^>]*class="tl-test-desc', html)
        assert 'Add Description' not in html

    def test_change_page_links_with_change_test(self):
        html = self.change_page(self.superuser)
        self.assert_desc_in_link(html, self.with_desc)
        self.assert_blank_desc_in_link(html, self.no_desc)

    def test_change_page_read_only_without_change_test(self):
        html = self.change_page(self.limited)
        assert not CELL_LINK.search(html)
        assert 'Add Description' not in html
        desc = DESC.search(html)
        assert desc and 'Measure output' in desc.group(0)

    def test_add_row_partial_with_change_test(self):
        self.assert_desc_in_link(self.add_row(self.superuser, self.with_desc), self.with_desc)
        self.assert_blank_desc_in_link(self.add_row(self.superuser, self.no_desc), self.no_desc)

    def test_add_row_partial_without_change_test(self):
        html = self.add_row(self.limited, self.with_desc)
        assert not CELL_LINK.search(html)
        assert DESC.search(html)
        html = self.add_row(self.limited, self.no_desc)
        assert 'Add Description' not in html
        assert 'class="tl-test-desc"' not in html

    def test_duplicate_row_renders_the_same_link(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(reverse('admin:qa_testlist_duplicate_test'), {
            'source_test_id': self.with_desc.pk, 'new_name': 'Output Constancy 6X (Copy)', 'index': 3,
        })
        assert resp.status_code == 200
        copy = qa_models.Test.objects.get(name='Output Constancy 6X (Copy)')
        links = CELL_LINK.findall(resp.content.decode())
        assert len(links) == 1
        assert 'href="%s"' % self.edit_url(copy) in links[0]
        assert 'Measure output' in links[0]

    def test_link_covers_the_whole_cell(self):
        html = self.change_page(self.superuser)
        assert re.search(r'\.tl-cell-test \{\s*position: relative;', html)
        assert re.search(r'a\.tl-test-link::after \{[^}]*position: absolute;[^}]*inset: 0;', html)

    def test_machine_mode_keeps_the_test_cell_link(self):
        html = self.change_page(self.superuser)
        assert 'body.tl-mode-machine #tl-tests-card .tl-test-link' not in html
