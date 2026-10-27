from django.forms import modelform_factory
from django.test import TestCase
from django.urls import reverse

from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.tests.utils import create_user


class TestSameTestAddedTwice(TestCase):
    """The same test in two membership rows gets the builder's own duplicate message."""

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.tl = qa_utils.create_test_list(name='Parent List')
        self.t1 = qa_utils.create_test(name='test one')
        self.membership = qa_utils.create_test_list_membership(test_list=self.tl, test=self.t1, order=0)
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _post_data(self, remove_saved=False, remove_new=False):
        data = {
            'name': self.tl.name,
            'slug': 'parent-list',
            'description': '',
            'warning_message': '',
            'javascript': '',
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
            'children-TOTAL_FORMS': 0,
            'children-INITIAL_FORMS': 0,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-TOTAL_FORMS': 2,
            'testlistmembership_set-INITIAL_FORMS': 1,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-0-id': self.membership.pk,
            'testlistmembership_set-0-test_list': self.tl.pk,
            'testlistmembership_set-0-test': self.t1.pk,
            'testlistmembership_set-0-order': 0,
            'testlistmembership_set-1-id': '',
            'testlistmembership_set-1-test_list': self.tl.pk,
            'testlistmembership_set-1-test': self.t1.pk,
            'testlistmembership_set-1-order': 1,
        }
        if remove_saved:
            data['testlistmembership_set-0-DELETE'] = 'on'
        if remove_new:
            data['testlistmembership_set-1-DELETE'] = 'on'
        return data

    def _errors(self, resp):
        return [str(e) for e in resp.context['errors']]

    def test_same_test_twice_names_the_test(self):
        resp = self.client.post(self.url, data=self._post_data())
        self.assertEqual(resp.status_code, 200)
        errors = self._errors(resp)
        self.assertEqual(len(errors), 1)
        self.assertIn('appear more than once', errors[0])
        self.assertIn('test one (%s)' % self.t1.slug, errors[0])
        self.assertEqual(qa_models.TestListMembership.objects.filter(test_list=self.tl).count(), 1)

    def test_no_generic_duplicate_message(self):
        resp = self.client.post(self.url, data=self._post_data())
        content = resp.content.decode()
        self.assertNotIn('Please correct the duplicate data', content)
        self.assertNotIn('Please correct the duplicate values', content)
        self.assertEqual(content.count('appear more than once in this test list'), 1)

    def test_new_copy_removed_saves(self):
        resp = self.client.post(self.url, data=self._post_data(remove_new=True))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            list(qa_models.TestListMembership.objects.filter(test_list=self.tl).values_list('pk', flat=True)),
            [self.membership.pk],
        )

    def test_saved_copy_removed_saves(self):
        resp = self.client.post(self.url, data=self._post_data(remove_saved=True))
        self.assertEqual(resp.status_code, 302)
        tlms = qa_models.TestListMembership.objects.filter(test_list=self.tl)
        self.assertEqual(tlms.count(), 1)
        self.assertNotEqual(tlms.get().pk, self.membership.pk)

    def test_form_alone_reports_duplicate(self):
        data = self._post_data()
        form_class = modelform_factory(qa_models.TestList, form=qa_admin.TestListAdminForm, exclude=['tests'])
        form = form_class(data=data, instance=self.tl)
        self.assertFalse(form.is_valid())
        self.assertIn('test one', ' '.join(form.non_field_errors()))
