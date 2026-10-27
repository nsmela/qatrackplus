import collections
import json
import re

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models
from qatrack.qa.tests import utils

ID_RE = re.compile(r'\sid="([^"]+)"')
NAME_RE = re.compile(r'<(?:input|select|textarea)\b[^>]*\sname="([^"]+)"')


def duplicates(pattern, html):
    counts = collections.Counter(pattern.findall(html))
    return {k: v for k, v in counts.items() if v > 1}


class TestPerformPageUniqueIds(TestCase):
    """The Perform QC page must not repeat element ids or render an upload test's inputs twice"""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)
        self.status = utils.create_status()

        self.t_simple = utils.create_test(name='simple', procedure='http://example.com/proc')
        self.t_upload = utils.create_test(name='upload', test_type=models.UPLOAD)
        self.test_list = utils.create_test_list()
        for idx, test in enumerate([self.t_simple, self.t_upload]):
            utils.create_test_list_membership(self.test_list, test, idx)
        self.utc = utils.create_unit_test_collection(test_collection=self.test_list)
        # the perform page is only available to members of a group the assignment is visible to
        self.user.groups.add(*self.utc.visible_to.all())
        self.url = reverse('perform_qa', kwargs={'pk': self.utc.pk})

    def upload_prefix(self):
        return 'form-1'

    def test_perform_page_has_no_duplicate_ids(self):
        html = self.client.get(self.url).content.decode()
        assert duplicates(ID_RE, html) == {}
        # both rows that used to share "<slug>-procedure" are still there
        assert 'id="simple-procedure"' in html
        assert 'id="simple-procedure-detail"' in html
        # sidebar toggles keep working via data-toggle; each link now has its own id
        assert 'id="toggle-admin"' in html
        assert 'id="toggle-comments"' in html
        assert 'id="toggle-options"' not in html

    def test_upload_inputs_render_once_inside_value_cell(self):
        html = self.client.get(self.url).content.decode()
        names = duplicates(NAME_RE, html)
        assert '%s-string_value' % self.upload_prefix() not in names
        assert '%s-json_value' % self.upload_prefix() not in names
        # qa.js only reads/writes the copies inside td.qa-value, so that is the one that must remain
        value_cell = html.split('id="upload-value"', 1)[1].split('</td>', 1)[0]
        assert 'name="%s-string_value"' % self.upload_prefix() in value_cell
        assert 'name="%s-json_value"' % self.upload_prefix() in value_cell

    def test_submit_saves_upload_values(self):
        result = {'foo': 1.5}
        data = {
            'work_started': '2012-11-07 00:09',
            'status': self.status.pk,
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-value': 1,
            'form-0-comment': '',
            'form-1-string_value': '42',
            'form-1-json_value': json.dumps(result),
            'form-1-comment': '',
        }
        resp = self.client.post(self.url, data=data)
        assert resp.status_code == 302

        ti = models.TestInstance.objects.get(unit_test_info__test=self.t_upload)
        assert ti.string_value == '42'
        assert ti.json_value == result
        assert models.TestInstance.objects.get(unit_test_info__test=self.t_simple).value == 1

        # editing the saved session renders without duplicate ids/inputs too
        edit_url = reverse('edit_tli', kwargs={'pk': ti.test_list_instance.pk})
        edit_resp = self.client.get(edit_url)
        assert edit_resp.status_code == 200
        html = edit_resp.content.decode()
        assert 'id="toggle-serviceevents"' in html
        assert duplicates(ID_RE, html) == {}
        names = duplicates(NAME_RE, html)
        assert 'form-1-string_value' not in names
        assert 'form-1-json_value' not in names
