"""Round 2, N28: the builder's Duplicate Test endpoint only copies tests the Test admin lets the user view."""
from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils


class TestDuplicateTestVisibility(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=False, uname='dupuser', pwd='pwd')
        # a test list editor: everything on test lists, nothing on Test yet
        cts = ContentType.objects.get_for_models(
            qa_models.TestList, qa_models.TestListMembership, qa_models.Sublist,
        ).values()
        self.user.user_permissions.add(*Permission.objects.filter(content_type__in=cts))
        self.test = qa_utils.create_test(name='n28_source')
        self.url = reverse('admin:qa_testlist_duplicate_test')
        self.client.login(username='dupuser', password='pwd')

    def _grant(self, *codenames):
        ct = ContentType.objects.get_for_model(qa_models.Test)
        self.user.user_permissions.add(*Permission.objects.filter(content_type=ct, codename__in=codenames))

    def _post(self, test_id=None, name='n28 copy', client=None):
        data = {'new_name': name, 'index': '0'}
        if test_id is not None:
            data['source_test_id'] = test_id
        return (client or self.client).post(self.url, data)

    def test_no_add_test_forbidden(self):
        self._grant('view_test', 'change_test')
        self.assertEqual(self.client.get(self.url, {'test_id': self.test.pk}).status_code, 403)
        resp = self._post(self.test.pk)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(qa_models.Test.objects.filter(name='n28 copy').exists())

    def test_add_test_without_view_forbidden(self):
        self._grant('add_test')
        resp = self.client.get(self.url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('No test was created', resp.content.decode())
        before = qa_models.Test.objects.count()
        resp = self._post(self.test.pk)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(qa_models.Test.objects.count(), before)

    def test_no_view_gives_same_answer_for_missing_test(self):
        # without view permission a missing id is 403 too, so ids can't be probed
        self._grant('add_test')
        self.assertEqual(self._post(999999).status_code, 403)

    def test_missing_id_404(self):
        self._grant('add_test', 'view_test')
        self.assertEqual(self.client.get(self.url, {'test_id': 999999}).status_code, 404)
        self.assertEqual(self._post(999999).status_code, 404)
        self.assertEqual(self._post().status_code, 404)

    def test_malformed_id_404(self):
        self._grant('add_test', 'view_test')
        self.assertEqual(self.client.get(self.url, {'test_id': 'abc'}).status_code, 404)
        self.assertEqual(self._post('abc').status_code, 404)

    def test_test_outside_admin_queryset_404(self):
        """Any future per-object scoping in TestAdmin.get_queryset applies here too."""
        self._grant('add_test', 'view_test')
        with mock.patch.object(
            qa_admin.TestAdmin, 'get_queryset', lambda self, request: qa_models.Test.objects.none(),
        ):
            self.assertEqual(self.client.get(self.url, {'test_id': self.test.pk}).status_code, 404)
            self.assertEqual(self._post(self.test.pk).status_code, 404)
        self.assertFalse(qa_models.Test.objects.filter(name='n28 copy').exists())

    def test_object_view_permission_respected(self):
        self._grant('add_test', 'view_test')
        orig = qa_admin.TestAdmin.has_view_permission

        def no_object_view(admin_self, request, obj=None):
            return obj is None and orig(admin_self, request, obj)

        with mock.patch.object(qa_admin.TestAdmin, 'has_view_permission', no_object_view):
            self.assertEqual(self._post(self.test.pk).status_code, 403)
        self.assertFalse(qa_models.Test.objects.filter(name='n28 copy').exists())

    def test_other_methods_405(self):
        self._grant('add_test', 'view_test')
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)

    def test_get_only_renders_dialog(self):
        self._grant('add_test', 'view_test')
        before = qa_models.Test.objects.count()
        resp = self.client.get(self.url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="tl-duplicate-test-form"')
        self.assertContains(resp, 'csrfmiddlewaretoken')
        self.assertEqual(qa_models.Test.objects.count(), before)

    def test_post_requires_csrf(self):
        self._grant('add_test', 'view_test')
        client = Client(enforce_csrf_checks=True)
        client.login(username='dupuser', password='pwd')
        resp = self._post(self.test.pk, client=client)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(qa_models.Test.objects.filter(name='n28 copy').exists())

    def test_duplicate_works_with_view_test(self):
        self._grant('add_test', 'view_test')
        resp = self._post(self.test.pk)
        self.assertEqual(resp.status_code, 200)
        copy = qa_models.Test.objects.get(name='n28 copy')
        self.assertEqual(copy.category_id, self.test.category_id)
        self.assertEqual(copy.created_by, self.user)

    def test_duplicate_works_with_change_test(self):
        # the Test admin treats change permission as view permission too
        self._grant('add_test', 'change_test')
        self.assertEqual(self._post(self.test.pk).status_code, 200)
        self.assertTrue(qa_models.Test.objects.filter(name='n28 copy').exists())

    def test_button_needs_view_or_change_test(self):
        row_url = reverse('admin:qa_testlist_add_test_row')
        self._grant('add_test')
        resp = self.client.get(row_url, {'test_id': self.test.pk, 'index': 1})
        self.assertNotContains(resp, 'tl-duplicate-test-btn')
        self._grant('view_test')
        resp = self.client.get(row_url, {'test_id': self.test.pk, 'index': 1})
        self.assertContains(resp, 'tl-duplicate-test-btn')
