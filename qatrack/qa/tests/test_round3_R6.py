"""The Edit Test List title shows the test list's ID (round 3, R6).

The ID is a quieter second part of the pinned title row ("Edit Test List · ID 12")
on the edit page only: the add page and a Save As that failed validation (which
re-renders as an add page) have no ID to show.
"""
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils


def _header_title(html):
    match = re.search(r'<h1 class="tl-header-title">(.*?)</h1>', html, re.S)
    assert match, 'tl-header-title was not rendered'
    return match.group(1)


def _text(fragment):
    return ' '.join(re.sub(r'<[^>]+>', ' ', fragment).replace('&middot;', '·').split())


class TestHeaderShowsId(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        # Burn a few pks so the ID can't be mistaken for another small number on the page.
        for i in range(3):
            qa_utils.create_test_list(name='filler %d' % i)
        self.tl = qa_utils.create_test_list(name='Daily Linac QC')
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def test_edit_page_title_contains_id(self):
        with translation.override('en'):
            resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        title = _header_title(resp.content.decode())
        self.assertIn('<span class="tl-header-id">', title)
        self.assertEqual(_text(title), 'Edit Test List · ID %d' % self.tl.pk)
        # the separator is decoration only
        self.assertIn('<span class="tl-header-id-sep" aria-hidden="true">&middot;</span>', title)

    def test_edit_page_keeps_existing_msgid(self):
        # "Edit Test List" stays its own translatable string; the ID is rendered beside it.
        with translation.override('fr'):
            resp = self.client.get(self.change_url)
        title = _text(_header_title(resp.content.decode()))
        self.assertTrue(title.endswith('· ID %d' % self.tl.pk), title)

    def test_add_page_has_no_id(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        self.assertEqual(resp.status_code, 200)
        title = _header_title(resp.content.decode())
        self.assertNotIn('tl-header-id', title)
        self.assertEqual(_text(title), 'Add Test List')

    def test_failed_save_as_has_no_id(self):
        data = {
            'name': 'Daily Linac QC (Copy)',
            'slug': self.tl.slug,  # clashes with the original, so validation fails
            'description': '',
            'warning_message': '',
            'javascript': '',
            '_saveasnew': '1',
            '_saveas_source': self.tl.pk,
        }
        for prefix in ('testlistmembership_set', 'children', 'attachment_set'):
            data.update({
                '%s-TOTAL_FORMS' % prefix: 0,
                '%s-INITIAL_FORMS' % prefix: 0,
                '%s-MIN_NUM_FORMS' % prefix: 0,
                '%s-MAX_NUM_FORMS' % prefix: 1000,
            })
        resp = self.client.post(self.change_url, data=data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(qa_models.TestList.objects.filter(name='Daily Linac QC (Copy)').count(), 0)
        title = _header_title(resp.content.decode())
        self.assertNotIn('tl-header-id', title)
        self.assertEqual(_text(title), 'Add Test List')

    def test_browser_tab_title_unchanged(self):
        # The <title> already leads with the test list's name; the ID is left out of it.
        resp = self.client.get(self.change_url)
        self.assertContains(resp, '<title>Daily Linac QC | Edit Test List |')
