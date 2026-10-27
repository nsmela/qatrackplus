from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.attachments.models import Attachment
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.tests.test_round2_N31 import page_post_data

CARD_IDS = ['tl-details-card', 'tl-attachments-card', 'tl-parents-card', 'tl-tests-card']  # R10 order


def card_order(content):
    """The builder card ids in the order they appear on the page (ids that aren't there are left out)."""
    found = [(content.index('id="%s"' % cid), cid) for cid in CARD_IDS if 'id="%s"' % cid in content]
    return [cid for _, cid in sorted(found)]


class TestAttachmentsCardOrder(TestCase):
    """The Attachments card sits between Details and Tests & Sublists (R8)."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.tl = qa_utils.create_test_list(name='R8 list')
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='R8 test'))
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def test_change_page_card_order(self):
        content = self.client.get(self.url).content.decode()
        self.assertEqual(card_order(content), CARD_IDS)

    def test_change_page_card_order_when_used_as_sublist(self):
        parent = qa_utils.create_test_list(name='R8 parent')
        qa_utils.create_sublist(parent_test_list=parent, child_test_list=self.tl)
        content = self.client.get(self.url).content.decode()
        self.assertEqual(card_order(content), CARD_IDS)
        self.assertIn('tl-parents-grid', content)

    def test_add_page_card_order(self):
        content = self.client.get(reverse('admin:qa_testlist_add')).content.decode()
        # the add page has no Parent Test List Memberships card
        self.assertEqual(card_order(content), ['tl-details-card', 'tl-attachments-card', 'tl-tests-card'])

    def test_attachment_inputs_render_once_inside_their_card(self):
        content = self.client.get(self.url).content.decode()
        self.assertEqual(content.count('name="attachment_set-TOTAL_FORMS"'), 1)
        self.assertEqual(content.count('id="tl-attachments-card"'), 1)
        start = content.index('id="tl-attachments-card"')
        self.assertLess(start, content.index('name="attachment_set-TOTAL_FORMS"'))
        self.assertLess(content.index('name="attachment_set-TOTAL_FORMS"'), content.index('id="tl-tests-card"'))
        self.assertLess(start, content.index('id="tl-browse-btn"'))


class TestSaveWithAttachmentAfterMove(TestCase):
    """Moving the card mustn't change what the page posts: unchanged, added and removed attachments all save."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.tl = qa_utils.create_test_list(name='R8 save list')
        self.tl.slug = 'r8-save-list'
        self.tl.save()
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='R8 save test'))
        self.attachment = Attachment.objects.create(
            attachment='uploads/testlist/r8.pdf', label='R8 Manual', comment='keep me',
            testlist=self.tl, created_by=self.user,
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _page_data(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = page_post_data(resp.content.decode())
        data['_save'] = 'Save'
        return data

    def _post(self, data):
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context.get('errors'))

    def test_unchanged_save_keeps_attachment_and_comment(self):
        self._post(self._page_data())
        self.attachment.refresh_from_db()
        self.assertEqual(self.attachment.comment, 'keep me')
        self.assertEqual(self.attachment.label, 'R8 Manual')

    def test_save_with_new_attachment(self):
        data = self._page_data()
        idx = int(data['attachment_set-INITIAL_FORMS'])
        data.update({
            'attachment_set-TOTAL_FORMS': max(int(data['attachment_set-TOTAL_FORMS']), idx + 1),
            'attachment_set-%d-attachment' % idx: SimpleUploadedFile('r8-new.txt', b'hi', content_type='text/plain'),
            'attachment_set-%d-testlist' % idx: self.tl.pk,
        })
        self._post(data)
        new = Attachment.objects.filter(testlist=self.tl).exclude(pk=self.attachment.pk).get()
        self.assertTrue(new.attachment.name.endswith('.txt'))
        new.attachment.delete(save=False)
        self.attachment.refresh_from_db()
        self.assertEqual(self.attachment.comment, 'keep me')

    def test_save_with_removed_attachment(self):
        data = self._page_data()
        data['attachment_set-0-DELETE'] = 'on'
        self._post(data)
        self.assertFalse(Attachment.objects.filter(pk=self.attachment.pk).exists())
