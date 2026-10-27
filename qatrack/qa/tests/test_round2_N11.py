import re
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils


class _ButtonCollector(HTMLParser):
    """Collect every <button> start tag's attributes, and the inline <script>/<style> text"""

    def __init__(self):
        super().__init__()
        self.buttons = []
        self.scripts = []
        self.styles = []
        self._in = None

    def handle_starttag(self, tag, attrs):
        if tag == 'button':
            self.buttons.append(dict(attrs))
        elif tag in ('script', 'style'):
            self._in = tag

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._in = None

    def handle_data(self, data):
        if self._in == 'script':
            self.scripts.append(data)
        elif self._in == 'style':
            self.styles.append(data)


def _parse(html):
    p = _ButtonCollector()
    p.feed(html)
    return p


def _classes(button):
    return set((button.get('class') or '').split())


class TestDialogSubmitHooks(TestCase):
    """The description dialog's and Save As dialog's submit buttons each have their own hook.

    `tl-btn-modal-save` is shared styling only; nothing that's meant for one dialog's submit
    may select it, so a handler for Save As can't disable, relabel or fire the description's.
    """

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)
        self.test = qa_utils.create_test(name='n11 test')
        self.tl = qa_utils.create_test_list(name='n11 list')
        qa_utils.create_test_list_membership(self.tl, self.test)

    def change_page(self):
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(self.tl.pk,)))
        assert resp.status_code == 200
        return _parse(resp.content.decode())

    def desc_dialog(self):
        url = reverse('admin:qa_testlist_test_desc_modal')
        resp = self.client.get(url, {'test_id': self.test.pk, 'index': 0})
        assert resp.status_code == 200
        return _parse(resp.content.decode())

    def saveas_button(self, page):
        found = [b for b in page.buttons if b.get('id') == 'tl-saveas-submit']
        assert len(found) == 1
        return found[0]

    def desc_button(self, dialog):
        found = [b for b in dialog.buttons if b.get('type') == 'submit']
        assert len(found) == 1
        return found[0]

    def test_each_submit_has_its_own_class(self):
        saveas = self.saveas_button(self.change_page())
        desc = self.desc_button(self.desc_dialog())
        assert 'tl-saveas-submit' in _classes(saveas)
        assert 'tl-desc-submit' in _classes(desc)
        assert 'tl-saveas-submit' not in _classes(desc)
        assert 'tl-desc-submit' not in _classes(saveas)
        assert desc.get('id') == 'tl-desc-submit'
        assert desc.get('id') != saveas.get('id')

    def test_shared_look_kept(self):
        saveas = self.saveas_button(self.change_page())
        desc = self.desc_button(self.desc_dialog())
        assert 'tl-btn-modal-save' in _classes(saveas)
        assert 'tl-btn-modal-save' in _classes(desc)

    def test_saveas_js_selectors_do_not_match_description_button(self):
        page = self.change_page()
        script = '\n'.join(page.scripts)
        assert 'submitSaveAs' in script
        # the builder script never selects buttons by the shared styling class
        assert 'tl-btn-modal-save' not in script
        # every way the script reaches the Save As submit names its own id
        by_id = re.findall(r'getElementById\(\s*["\']([^"\']*saveas-submit[^"\']*)["\']', script)
        by_sel = re.findall(r'["\']([^"\']*saveas-submit[^"\']*)["\']', script)
        assert by_id and set(by_id) == {'tl-saveas-submit'}
        assert set(by_sel) == {'tl-saveas-submit', '#tl-saveas-submit'}

        desc = self.desc_button(self.desc_dialog())
        for sel in by_sel:
            if sel.startswith('#'):
                assert desc.get('id') != sel[1:]
            elif sel.startswith('.'):
                assert sel[1:] not in _classes(desc)
            else:
                assert desc.get('id') != sel

    def test_saveas_disabled_style_scoped_to_saveas_submit(self):
        page = self.change_page()
        css = '\n'.join(page.styles)
        assert '.tl-saveas-submit:disabled' in css
        # no :disabled rule hangs off the shared styling class inside the Save As dialog any more
        assert '.tl-saveas-dialog .tl-btn-modal-save:disabled' not in css
