"""Round 3, R7: the builder's test description dialog is gone.

A test's description is edited on the Test's own page. In each builder row the
description (or "Add Description" when there's none) links there in a new tab,
like the row's pencil; users who can't change tests just see the text.
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

DESC_LINK = re.compile(r'<a href="[^"]*" target="_blank" rel="noopener" class="tl-test-desc"[^>]*>.*?</a>', re.S)
ADD_LINK = re.compile(r'<a href="[^"]*" target="_blank" rel="noopener" class="tl-add-desc-link"[^>]*>.*?</a>', re.S)


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

    def assert_desc_link(self, html, test):
        links = DESC_LINK.findall(html)
        assert len(links) == 1
        link = links[0]
        assert 'href="%s"' % self.edit_url(test) in link
        assert 'title="Edit %s (opens in a new tab)"' % test.name in link
        # the visible description stays the link's text; hidden text says where it goes
        assert '<span>Measure output</span>' in link
        assert '<span class="tl-visually-hidden">Edit %s (opens in a new tab)</span>' % test.name in link
        assert 'hx-' not in link
        assert 'aria-haspopup' not in link

    def assert_add_link(self, html, test):
        links = ADD_LINK.findall(html)
        assert len(links) == 1
        link = links[0]
        assert 'href="%s"' % self.edit_url(test) in link
        assert 'title="Add Description to %s (opens in a new tab)"' % test.name in link
        assert 'Add Description' in link
        assert 'to %s (opens in a new tab)</span>' % test.name in link

    def test_change_page_links_with_change_test(self):
        html = self.change_page(self.superuser)
        self.assert_desc_link(html, self.with_desc)
        self.assert_add_link(html, self.no_desc)
        assert 'class="tl-test-desc tl-test-desc-readonly"' not in html

    def test_change_page_read_only_without_change_test(self):
        html = self.change_page(self.limited)
        assert not DESC_LINK.search(html)
        assert not ADD_LINK.search(html)
        assert 'class="tl-add-desc-link"' not in html
        readonly = re.search(r'<div class="tl-test-desc tl-test-desc-readonly">.*?</div>', html, re.S)
        assert readonly and 'Measure output' in readonly.group(0)

    def test_add_row_partial_with_change_test(self):
        self.assert_desc_link(self.add_row(self.superuser, self.with_desc), self.with_desc)
        self.assert_add_link(self.add_row(self.superuser, self.no_desc), self.no_desc)

    def test_add_row_partial_without_change_test(self):
        html = self.add_row(self.limited, self.with_desc)
        assert not DESC_LINK.search(html)
        assert 'class="tl-test-desc tl-test-desc-readonly"' in html
        html = self.add_row(self.limited, self.no_desc)
        assert 'tl-add-desc-link' not in html
        assert 'class="tl-test-desc ' not in html
        assert 'class="tl-test-desc"' not in html

    def test_duplicate_row_renders_the_same_link(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(reverse('admin:qa_testlist_duplicate_test'), {
            'source_test_id': self.with_desc.pk, 'new_name': 'Output Constancy 6X (Copy)', 'index': 3,
        })
        assert resp.status_code == 200
        copy = qa_models.Test.objects.get(name='Output Constancy 6X (Copy)')
        html = resp.content.decode()
        links = DESC_LINK.findall(html)
        assert len(links) == 1
        assert 'href="%s"' % self.edit_url(copy) in links[0]

    def test_machine_mode_hides_add_description_link(self):
        html = self.change_page(self.superuser)
        assert 'body.tl-mode-machine #tl-tests-card .tl-add-desc-link' in html
        # the description link itself stays usable in machine mode
        assert 'body.tl-mode-machine #tl-tests-card .tl-test-desc {' not in html
