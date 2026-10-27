from html.parser import HTMLParser

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.attachments.models import Attachment
from qatrack.qa.tests import utils as qa_utils


class _FormFields(HTMLParser):
    """Collect what a browser would submit from the page's main form (no file inputs, no JS)."""

    def __init__(self):
        super().__init__()
        self.data = {}
        self._in_form = False
        self._textarea = None
        self._select = None
        self._select_first = None

    def _add(self, name, value):
        self.data.setdefault(name, []).append(value)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form' and a.get('id') == 'testlist_form':
            self._in_form = True
        if not self._in_form:
            return
        name = a.get('name')
        if tag == 'input' and name and 'disabled' not in a:
            itype = (a.get('type') or 'text').lower()
            if itype in ('submit', 'button', 'file', 'image', 'reset'):
                return
            if itype in ('checkbox', 'radio') and 'checked' not in a:
                return
            self._add(name, a.get('value', 'on' if itype in ('checkbox', 'radio') else ''))
        elif tag == 'textarea' and name:
            self._textarea = name
            self._add(name, '')
        elif tag == 'select' and name:
            self._select = name
            self._select_first = None
        elif tag == 'option' and self._select:
            value = a.get('value', '')
            if self._select_first is None:
                self._select_first = value
            if 'selected' in a:
                self._add(self._select, value)

    def handle_endtag(self, tag):
        if tag == 'form':
            self._in_form = False
        elif tag == 'textarea':
            self._textarea = None
        elif tag == 'select' and self._select:
            if self._select not in self.data and self._select_first is not None:
                self._add(self._select, self._select_first)
            self._select = None

    def handle_data(self, data):
        if self._textarea:
            self.data[self._textarea][-1] += data


def page_post_data(content):
    parser = _FormFields()
    parser.feed(content)
    return {k: v if len(v) > 1 else v[0] for k, v in parser.data.items()}


class TestSavingTestListKeepsAttachmentData(TestCase):
    """A normal Save of the Test List page must not blank the comment (or label) of a saved
    attachment: the saved-attachment card posts every editable field of its inline form."""

    def setUp(self):
        self.superuser = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.limited = create_user(is_superuser=False, uname='tlonly', pwd='pwd')
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='qa',
            codename__in=['view_testlist', 'change_testlist', 'view_testlistmembership', 'view_sublist'],
        ))
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='attachments', codename__in=['view_attachment'],
        ))
        self.tl = qa_utils.create_test_list(name='Attach List')
        self.tl.slug = 'attach-list'
        self.tl.save()
        self.attachment = Attachment.objects.create(
            attachment='uploads/testlist/manual.pdf', label='Manual', comment='keep me\nsecond line',
            testlist=self.tl, created_by=self.superuser,
        )
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _save_as_page_would(self, uname, extra=None):
        self.client.login(username=uname, password='pwd')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = page_post_data(resp.content.decode())
        data['_save'] = 'Save'
        if extra:
            data.update(extra)
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context.get('errors'))
        return resp

    def _assert_unchanged(self):
        self.attachment.refresh_from_db()
        # browsers submit line breaks as CRLF; the text itself must survive
        self.assertEqual(self.attachment.comment.replace('\r\n', '\n'), 'keep me\nsecond line')
        self.assertEqual(self.attachment.label, 'Manual')
        self.assertEqual(self.attachment.attachment.name, 'uploads/testlist/manual.pdf')
        self.assertEqual(self.attachment.testlist_id, self.tl.pk)
        self.assertEqual(self.attachment.created_by, self.superuser)

    def test_superuser_save_keeps_comment_and_label(self):
        self._save_as_page_would('super')
        self._assert_unchanged()

    def test_testlist_only_user_save_keeps_comment_and_label(self):
        self._save_as_page_would('tlonly')
        self._assert_unchanged()

    def test_existing_card_carries_comment_as_hidden_input(self):
        self.client.login(username='super', password='pwd')
        data = page_post_data(self.client.get(self.url).content.decode())
        self.assertEqual(data['attachment_set-0-comment'], 'keep me\nsecond line')

    def test_adding_new_attachment_still_works(self):
        upload = SimpleUploadedFile('new-sheet.txt', b'hello', content_type='text/plain')
        self.client.login(username='super', password='pwd')
        data = page_post_data(self.client.get(self.url).content.decode())
        total = int(data['attachment_set-TOTAL_FORMS'])
        idx = int(data['attachment_set-INITIAL_FORMS'])
        data.update({
            '_save': 'Save',
            'attachment_set-TOTAL_FORMS': max(total, idx + 1),
            'attachment_set-%d-attachment' % idx: upload,
            'attachment_set-%d-comment' % idx: 'fresh comment',
            'attachment_set-%d-testlist' % idx: self.tl.pk,
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        new = Attachment.objects.filter(testlist=self.tl).exclude(pk=self.attachment.pk).get()
        self.assertEqual(new.comment, 'fresh comment')
        self.assertTrue(new.attachment.name.endswith('.txt'))
        new.attachment.delete(save=False)
        self._assert_unchanged()


class TestBrowseNeedsAddAttachment(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.limited = create_user(is_superuser=False, uname='noadd', pwd='pwd')
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='qa',
            codename__in=['view_testlist', 'change_testlist', 'view_testlistmembership', 'view_sublist'],
        ))
        self.limited.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='attachments', codename__in=['view_attachment', 'change_attachment'],
        ))
        self.tl = qa_utils.create_test_list(name='Browse List')
        self.tl.slug = 'browse-list'
        self.tl.save()
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def test_browse_shown_with_add_attachment(self):
        self.client.login(username='super', password='pwd')
        content = self.client.get(self.url).content.decode()
        self.assertIn('id="tl-browse-btn"', content)
        self.assertIn('id="id_tl-new-attachments"', content)

    def test_change_attachment_user_save_keeps_comment(self):
        att = Attachment.objects.create(
            attachment='uploads/testlist/a.pdf', comment='keep me', testlist=self.tl, created_by=self.limited,
        )
        self.client.login(username='noadd', password='pwd')
        data = page_post_data(self.client.get(self.url).content.decode())
        data['_save'] = 'Save'
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        att.refresh_from_db()
        self.assertEqual(att.comment, 'keep me')

    def test_browse_hidden_without_add_attachment(self):
        self.client.login(username='noadd', password='pwd')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('id="tl-attachments-card"', content)
        self.assertNotIn('id="tl-browse-btn"', content)
        self.assertNotIn('id="id_tl-new-attachments"', content)
        self.assertNotIn('Use Browse… to attach files', content)
