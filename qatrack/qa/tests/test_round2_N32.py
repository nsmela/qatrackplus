"""Round 2, N32: a saved test row printed its `testlistmembership_set-N-id` hidden input twice
(Django's pk field plus a hand-written copy). Each membership form should carry it exactly once."""
import collections
import re
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils


class _FormFields(HTMLParser):
    """What a browser would submit for the change form's `testlist_form`, roughly."""

    def __init__(self):
        super().__init__()
        self.data = []
        self._in_form = False
        self._select = None
        self._select_first = None
        self._select_chosen = False
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form' and a.get('id') == 'testlist_form':
            self._in_form = True
        if not self._in_form:
            return
        name = a.get('name')
        if tag == 'input' and name and a.get('type') not in ('submit', 'button', 'file'):
            if a.get('type') in ('checkbox', 'radio') and 'checked' not in a:
                return
            self.data.append((name, a.get('value') or ('on' if a.get('type') == 'checkbox' else '')))
        elif tag == 'select' and name:
            self._select, self._select_first, self._select_chosen = name, None, False
        elif tag == 'option' and self._select:
            if self._select_first is None:
                self._select_first = a.get('value', '')
            if 'selected' in a:
                self.data.append((self._select, a.get('value', '')))
                self._select_chosen = True
        elif tag == 'textarea' and name:
            self._textarea = [name, '']

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == 'form' and self._in_form:
            self._in_form = False
        elif tag == 'select' and self._select:
            if not self._select_chosen and self._select_first is not None:
                self.data.append((self._select, self._select_first))
            self._select = None
        elif tag == 'textarea' and self._textarea is not None:
            self.data.append(tuple(self._textarea))
            self._textarea = None


class TestTestRowRendersIdOnce(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.tl = qa_utils.create_test_list(name='N32 List')
        self.tests = [qa_utils.create_test(name='n32 test %d' % i) for i in range(3)]
        self.memberships = [
            qa_utils.create_test_list_membership(test_list=self.tl, test=t, order=i)
            for i, t in enumerate(self.tests)
        ]
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _content(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _form_data(self, content):
        parser = _FormFields()
        parser.feed(content)
        self.assertTrue(parser.data, 'testlist_form not found')
        data = collections.defaultdict(list)
        for k, v in parser.data:
            data[k].append(v)
        data['slug'] = ['n32-list']  # the test util's default slug isn't a valid slug
        return data

    @staticmethod
    def _errors(resp):
        if resp.status_code != 200:
            return resp.status_code
        return [resp.context['adminform'].form.errors] + [
            (fs.formset.errors, fs.formset.non_form_errors()) for fs in resp.context['inline_admin_formsets']
        ]

    def test_one_input_per_membership_name(self):
        content = self._content()
        names = collections.Counter(
            re.findall(r'<input\b[^>]*\bname="(testlistmembership_set-\d+-[^"]+)"', content)
        )
        self.assertEqual([n for n, c in names.items() if c > 1], [])
        for i, m in enumerate(self.memberships):
            tags = re.findall(r'<input\b[^>]*\bname="testlistmembership_set-%d-id"[^>]*>' % i, content)
            self.assertEqual(len(tags), 1, tags)
            self.assertIn('value="%d"' % m.pk, tags[0])

    def test_no_duplicate_membership_element_ids(self):
        ids = collections.Counter(re.findall(r'\bid="(id_testlistmembership_set-[^"]+)"', self._content()))
        self.assertEqual([i for i, c in ids.items() if c > 1], [])

    def test_save_unchanged_keeps_membership_pks(self):
        data = self._form_data(self._content())
        self.assertEqual(len(data['testlistmembership_set-0-id']), 1)
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302, self._errors(resp))
        pks = sorted(qa_models.TestListMembership.objects.filter(test_list=self.tl).values_list('pk', flat=True))
        self.assertEqual(pks, sorted(m.pk for m in self.memberships))

    def test_remove_row_deletes_membership(self):
        data = self._form_data(self._content())
        data['testlistmembership_set-1-DELETE'] = ['on']
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302, self._errors(resp))
        pks = set(qa_models.TestListMembership.objects.filter(test_list=self.tl).values_list('pk', flat=True))
        self.assertEqual(pks, {self.memberships[0].pk, self.memberships[2].pk})

    def test_add_row_partial_has_one_id_input(self):
        new = qa_utils.create_test(name='n32 new')
        resp = self.client.get(
            reverse('admin:qa_testlist_add_test_row'), {'test_id': new.pk, 'index': 3, 'test_list_id': self.tl.pk},
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        tags = re.findall(r'<input\b[^>]*\bname="testlistmembership_set-3-id"[^>]*>', content)
        self.assertEqual(len(tags), 1, tags)
        self.assertIn('value=""', tags[0])
        names = collections.Counter(re.findall(r'<input\b[^>]*\bname="([^"]+)"', content))
        self.assertEqual([n for n, c in names.items() if c > 1], [])
