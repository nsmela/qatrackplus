import re

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.attachments.models import Attachment
from qatrack.qa.tests import utils as qa_utils


class TestTestListAttachmentDeletePermission(TestCase):
    """The Test List page only offers to remove a saved attachment when the user may delete
    attachments, and a posted removal without that permission leaves the attachment in place
    (Django's inline formset has can_delete=False and ignores the DELETE box)."""

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.limited = create_user(is_superuser=False, uname='nodelete', pwd='pwd')
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='qa',
            codename__in=['view_testlist', 'change_testlist', 'view_testlistmembership', 'view_sublist'],
        ))
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='attachments', codename__in=['view_attachment', 'add_attachment'],
        ))
        self.tl = qa_utils.create_test_list(name='Attach List')
        self.tl.slug = 'attach-list'
        self.tl.save()
        self.attachment = Attachment.objects.create(
            attachment='uploads/testlist/manual.pdf', label='Manual', testlist=self.tl, created_by=self.limited,
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _login(self, uname):
        self.client.login(username=uname, password='pwd')

    def _card(self, content):
        match = re.search(r'<div class="attachment-card existing" id="existing-attach-%d">(.*?)</div>\s*</div>\s*</div>'
                          % self.attachment.pk, content, flags=re.S)
        self.assertIsNotNone(match)
        return match.group(1)

    def _post_data(self, delete=True):
        data = {
            'name': self.tl.name,
            'slug': self.tl.slug,
            'description': '',
            'warning_message': '',
            'javascript': '',
            'attachment_set-TOTAL_FORMS': 1,
            'attachment_set-INITIAL_FORMS': 1,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
            'attachment_set-0-id': self.attachment.pk,
            'attachment_set-0-testlist': self.tl.pk,
            'testlistmembership_set-TOTAL_FORMS': 0,
            'testlistmembership_set-INITIAL_FORMS': 0,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'children-TOTAL_FORMS': 0,
            'children-INITIAL_FORMS': 0,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
        }
        if delete:
            data['attachment_set-0-DELETE'] = 'on'
        return data

    def test_no_remove_control_without_delete_permission(self):
        self._login('nodelete')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        card = self._card(content)
        self.assertIn('Manual', card)
        self.assertNotIn('btn-delete-existing', card)
        self.assertNotIn('attachment_set-0-DELETE', content)
        # the preview link is still there
        self.assertIn('tl-attach-btn', card)

    def test_remove_control_with_delete_permission(self):
        self._login('super')
        content = self.client.get(self.url).content.decode()
        card = self._card(content)
        self.assertIn('btn-delete-existing', card)
        self.assertIn('name="attachment_set-0-DELETE"', card)

    def test_posted_delete_without_permission_keeps_attachment(self):
        self._login('nodelete')
        resp = self.client.post(self.url, data=self._post_data(delete=True))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Attachment.objects.filter(pk=self.attachment.pk).exists())

    def test_posted_delete_with_permission_removes_attachment(self):
        self._login('super')
        resp = self.client.post(self.url, data=self._post_data(delete=True))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Attachment.objects.filter(pk=self.attachment.pk).exists())
