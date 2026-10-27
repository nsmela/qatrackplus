import collections
import re

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils


class TestSublistCardRendersIdOnce(TestCase):
    """A saved sublist card used to render its `children-N-id` hidden input twice (Django's
    pk field plus a hand-written copy). Each sublist form should carry it exactly once."""

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.parent = qa_utils.create_test_list(name='Parent List')
        self.t1 = qa_utils.create_test(name='test one')
        self.t2 = qa_utils.create_test(name='test two')
        self.membership = qa_utils.create_test_list_membership(test_list=self.parent, test=self.t1, order=0)
        self.child = qa_utils.create_test_list(name='Child List')
        qa_utils.create_test_list_membership(test_list=self.child, test=self.t2)
        self.sublist = qa_utils.create_sublist(parent_test_list=self.parent, child_test_list=self.child)
        self.url = reverse('admin:qa_testlist_change', args=(self.parent.pk,))

    def _post_data(self, delete_sublist=False):
        data = {
            'name': self.parent.name,
            'slug': 'parent-list',
            'description': '',
            'warning_message': '',
            'javascript': '',
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-TOTAL_FORMS': 1,
            'testlistmembership_set-INITIAL_FORMS': 1,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-0-id': self.membership.pk,
            'testlistmembership_set-0-test_list': self.parent.pk,
            'testlistmembership_set-0-test': self.t1.pk,
            'testlistmembership_set-0-order': 0,
            'children-TOTAL_FORMS': 1,
            'children-INITIAL_FORMS': 1,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'children-0-id': self.sublist.pk,
            'children-0-parent': self.parent.pk,
            'children-0-child': self.child.pk,
            'children-0-order': 1,
        }
        if delete_sublist:
            data['children-0-DELETE'] = 'on'
        return data

    @staticmethod
    def _children_inputs(content):
        return re.findall(r'<input\b[^>]*\bname="(children-[^"]+)"[^>]*>', content)

    @staticmethod
    def _children_ids(content):
        return re.findall(r'\bid="(id_children-[^"]+)"', content)

    def test_saved_sublist_id_rendered_once(self):
        content = self.client.get(self.url).content.decode()
        tags = re.findall(r'<input\b[^>]*\bname="children-0-id"[^>]*>', content)
        self.assertEqual(len(tags), 1, tags)
        self.assertIn('value="%d"' % self.sublist.pk, tags[0])

    def test_no_duplicate_sublist_input_names_or_ids(self):
        content = self.client.get(self.url).content.decode()
        names = collections.Counter(self._children_inputs(content))
        self.assertEqual([n for n, c in names.items() if c > 1], [])
        for suffix in ('id', 'parent', 'child', 'order', 'DELETE', 'outline'):
            self.assertEqual(names['children-0-%s' % suffix], 1, suffix)
        ids = collections.Counter(self._children_ids(content))
        self.assertEqual([i for i, c in ids.items() if c > 1], [])

    def test_swapped_and_new_cards_render_id_once(self):
        other = qa_utils.create_test_list(name='Other List')
        url = reverse('admin:qa_testlist_add_sublist_card')
        swap = {'swap': '1', 'child_id': other.pk, 'index': 0, 'sublist_id': self.sublist.pk, 'order': 1}
        for params in (swap, {'child_id': other.pk, 'index': 2}):
            content = self.client.get(url, params).content.decode()
            names = collections.Counter(self._children_inputs(content))
            self.assertEqual(names['children-%s-id' % params['index']], 1, params)
            self.assertEqual([n for n, c in names.items() if c > 1], [], params)

    def test_save_with_unchanged_sublist(self):
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 302)
        subs = qa_models.Sublist.objects.filter(parent=self.parent)
        self.assertEqual(list(subs.values_list('pk', 'child_id')), [(self.sublist.pk, self.child.pk)])

    def test_remove_sublist(self):
        resp = self.client.post(self.url, self._post_data(delete_sublist=True))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(qa_models.Sublist.objects.filter(parent=self.parent).exists())
