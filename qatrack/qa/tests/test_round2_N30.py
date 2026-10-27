import re

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa.tests import utils as qa_utils


class TestTestAdminChoicesLabel(TestCase):
    """The multiple-choice "choices" field is labelled "Choices", not a second "Description"."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)

    def label_for(self, html, field):
        match = re.search(r'<label[^>]*for="id_%s"[^>]*>(.*?)</label>' % field, html, re.S)
        assert match, 'no label for %s' % field
        return match.group(1).strip()

    def test_form_label(self):
        assert qa_admin.TestForm().fields['choices'].label == 'Choices'

    def test_add_page_shows_choices_label(self):
        resp = self.client.get(reverse('admin:qa_test_add'))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert self.label_for(html, 'choices').startswith('Choices')
        assert self.label_for(html, 'description').startswith('Description')
        assert 'Comma separated list of choices for multiple choice test types' in html

    def test_change_page_shows_choices_label(self):
        test = qa_utils.create_test(name='mc_test', test_type='multchoice', choices='a,b,c')
        resp = self.client.get(reverse('admin:qa_test_change', args=(test.pk,)))
        assert resp.status_code == 200
        assert self.label_for(resp.content.decode(), 'choices').startswith('Choices')
