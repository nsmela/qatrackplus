"""The builder's Type column shows one chip with the type's full name (round 3, R2)."""
import re

from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.utils import get_internal_user

OLD_CLASSES = ('tl-type-badge', 'tl-type-label', 'tl-type-pill-wrap')


class TestTypeChip(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        get_internal_user()
        self.mc = qa_utils.create_test(name='Laser Alignment', test_type=qa_models.MULTIPLE_CHOICE)
        self.mc.choices = 'Pass,Fail'
        self.mc.save()
        self.upload = qa_utils.create_test(name='Image Upload', test_type=qa_models.UPLOAD)
        self.tl = qa_utils.create_test_list(name='Daily QC')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.mc)
        child = qa_utils.create_test_list(name='Imaging')
        qa_utils.create_test_list_membership(test_list=child, test=self.upload)
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=child)

    def _get(self, url, data=None):
        resp = self.client.get(url, data or {})
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def assert_no_old_markup(self, content):
        for cls in OLD_CLASSES:
            self.assertNotIn(cls, content)

    def test_change_page_rows_and_sublist_rows(self):
        content = self._get(reverse('admin:qa_testlist_change', args=(self.tl.pk,)))
        self.assertInHTML('<span class="tl-type-chip">Multiple Choice</span>', content, count=1)
        self.assertInHTML('<span class="tl-type-chip">File Upload</span>', content, count=1)
        self.assertNotRegex(content, r'class="tl-type-(badge|label|pill-wrap)"')

    def test_add_row_has_one_chip(self):
        content = self._get(reverse('admin:qa_testlist_add_test_row'), {'test_id': self.mc.pk, 'index': 3})
        cell = re.search(r'<td class="tl-cell-type">(.*?)</td>', content, re.S).group(1)
        self.assertHTMLEqual(cell, '<span class="tl-type-chip">Multiple Choice</span>')
        self.assert_no_old_markup(content)

    def test_add_sublist_card_has_chips(self):
        child = qa_models.TestList.objects.get(name='Imaging')
        content = self._get(reverse('admin:qa_testlist_add_sublist_card'), {'child_id': child.pk, 'index': 0})
        self.assertInHTML('<span class="tl-type-chip">File Upload</span>', content, count=1)
        self.assert_no_old_markup(content)

    def test_search_results_have_one_chip(self):
        content = self._get(reverse('admin:qa_testlist_search_tests'), {'q': 'Laser'})
        self.assertInHTML('<span class="tl-type-chip">Multiple Choice</span>', content, count=1)
        self.assertNotIn('M/C', content)
        self.assert_no_old_markup(content)

    def test_duplicate_dialog_has_one_chip(self):
        content = self._get(reverse('admin:qa_testlist_duplicate_test'), {'test_id': self.mc.pk})
        self.assertInHTML('<span class="tl-type-chip">Multiple Choice</span>', content, count=1)
        self.assert_no_old_markup(content)

    def test_metadata_has_no_short_badge(self):
        meta = qa_admin.get_test_metadata(self.mc)
        self.assertNotIn('type_badge', meta)
        self.assertEqual(meta['type_label'], 'Multiple Choice')

    def test_assets_drop_old_classes(self):
        origin = get_template('admin/qa/testlist/testlist_assets.html').origin
        with open(origin.name, encoding='utf-8') as f:
            source = f.read()
        self.assertIn('.tl-type-chip', source)
        self.assert_no_old_markup(source)
