"""Round 3, R13: the Test change form in the Test List page's style.

admin/qa/test/change_form.html draws the form as cards (Details, Type & Behaviour,
Calculation procedure, Attachments, Used In) with the save buttons in the title row,
and admin/qa/test/test_assets.html adds the controls: a grouped Type select, on/off
switches, chips for multiple-choice options, a Number format picker with a live
preview (TestAdmin's qa_test_format_preview) and the ace Python editor. The header,
card and attachments styles and the attachments JS are shared with the Test List page
(admin/qa/shared/). Because the fields are placed by hand, these tests check that
every form field is still on the page, so saving never blanks one.
"""

import re

from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils

ASSETS = 'admin/qa/test/test_assets.html'
TL_ASSETS = 'admin/qa/testlist/testlist_assets.html'


def _soup(resp):
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), 'html.parser')


class TestTestChangeFormCards(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.test = qa_utils.create_test(name='Output', test_type=models.SIMPLE)
        self.url = reverse('admin:qa_test_change', args=(self.test.pk,))

    def test_every_form_field_is_on_the_page(self):
        """The fields are placed by hand, so check none was left out (it would post blank)."""
        for url in (self.url, reverse('admin:qa_test_add')):
            soup = _soup(self.client.get(url))
            form = soup.find('form', id='test_form')
            for name in qa_admin.TestForm(instance=self.test).fields:
                assert form.find(attrs={'name': name}), '%s missing from %s' % (name, url)

    def test_cards_in_order(self):
        soup = _soup(self.client.get(self.url))
        ids = [el['id'] for el in soup.select('#test_form .tl-details-card, #test_form .tl-attachments-card')]
        assert ids == ['tst-details-card', 'tst-type-card', 'tst-calc-card', 'tl-attachments-card', 'tst-used-card']

    def test_header_has_the_one_button_group(self):
        soup = _soup(self.client.get(self.url))
        title = soup.select_one('h1.tl-header-title').get_text(' ', strip=True)
        assert title.startswith('Edit Test') and 'ID %d' % self.test.pk in title
        names = [b.get('name') for b in soup.select('.tl-header-actions button[type=submit]')]
        assert names == ['_saveasnew', '_continue', '_save']
        assert soup.select_one('#tst-history-btn') and soup.select_one('#tst-delete-btn')
        assert not soup.select('.submit-row')  # Django's bottom row is gone

    def test_add_page(self):
        soup = _soup(self.client.get(reverse('admin:qa_test_add')))
        assert soup.select_one('h1.tl-header-title').get_text(strip=True) == 'Add Test'
        assert not soup.select_one('#tst-used-card')
        assert not soup.select_one('#tst-saveas-btn')
        names = [b.get('name') for b in soup.select('.tl-header-actions button[type=submit]')]
        assert names == ['_addanother', '_continue', '_save']

    def test_failed_save_as_new_offers_only_save_as_new(self):
        """Django hides Save and Save and Continue after a failed Save as New: they
        would change the original test instead of making the copy."""
        data = {'name': 'Output copy', 'slug': self.test.slug, '_saveasnew': 'Save as New'}
        for prefix in ('attachment_set', 'attachments'):
            data.update({
                '%s-TOTAL_FORMS' % prefix: 0, '%s-INITIAL_FORMS' % prefix: 0,
                '%s-MIN_NUM_FORMS' % prefix: 0, '%s-MAX_NUM_FORMS' % prefix: 1000,
            })
        before = models.Test.objects.count()
        soup = _soup(self.client.post(self.url, data))
        names = [b.get('name') for b in soup.select('.tl-header-actions button[type=submit]')]
        assert names == ['_saveasnew']
        assert models.Test.objects.count() == before
        self.test.refresh_from_db()
        assert self.test.name == 'Output'

    def test_type_select_is_grouped_and_complete(self):
        soup = _soup(self.client.get(self.url))
        select = soup.find('select', id='id_type')
        groups = select.find_all('optgroup')
        assert [g['label'] for g in groups] == ['Numbers', 'Answers & text', 'Dates', 'Files']
        values = [o['value'] for o in select.find_all('option')]
        assert sorted(values) == sorted(t for t, _ in models.TEST_TYPE_CHOICES)
        assert select.find('option', selected=True)['value'] == models.SIMPLE

    def test_every_type_has_a_help_line(self):
        assert set(qa_admin.TEST_TYPE_HELP) == {t for t, _ in models.TEST_TYPE_CHOICES}
        soup = _soup(self.client.get(self.url))
        help_box = soup.find(id='tst-type-help')
        for t, _ in models.TEST_TYPE_CHOICES:
            assert help_box.get('data-help-%s' % t)
        assert soup.find(id='tst-type-help-text').get_text(strip=True) == str(qa_admin.TEST_TYPE_HELP[models.SIMPLE])

    def test_switches_are_checkboxes_with_role_switch(self):
        soup = _soup(self.client.get(self.url))
        for name in qa_admin.TEST_SWITCH_FIELDS:
            box = soup.find('input', attrs={'name': name})
            assert box['type'] == 'checkbox' and box['role'] == 'switch', name
            assert box.find_parent('label', class_='tst-switch'), name

    def test_settings_shown_for_the_right_types(self):
        """Same rules as the old test_admin.js."""
        soup = _soup(self.client.get(self.url))

        def show_for(field_id):
            el = soup.find(id=field_id).find_parent(attrs={'data-show-for': True})
            return set(el['data-show-for'].split())

        def hide_for(field_id):
            el = soup.find(id=field_id).find_parent(attrs={'data-hide-for': True})
            return set(el['data-hide-for'].split())

        assert show_for('id_choices') == {'multchoice'}
        assert show_for('id_constant_value') == {'constant'}
        assert show_for('id_wrap_low') == show_for('id_wrap_high') == {'wraparound'}
        assert show_for('id_flag_when') == {'boolean'}
        assert show_for('id_formatting') == set(models.NUMERICAL_TYPES)
        assert show_for('id_hidden') == {'constant', 'composite', 'scomposite'}
        assert show_for('id_display_image') == {'upload', 'composite', 'scomposite'}
        assert hide_for('id_skip_without_comment') == set(models.NO_SKIP_REQUIRED_TYPES)
        assert hide_for('id_chart_visibility') == {'string', 'scomposite', 'date', 'datetime', 'upload'}
        assert hide_for('id_calculation_procedure') == {'constant'}

    def test_format_presets_and_custom(self):
        soup = _soup(self.client.get(self.url))
        select = soup.find('select', id='tst-format-select')
        assert select.has_attr('hidden') and not select.get('name')  # shown by the JS, never posted
        values = [o['value'] for o in select.find_all('option')]
        assert values == [v for v, _ in qa_admin.TEST_FORMAT_PRESETS] + ['__custom__']
        preview = soup.find(id='tst-format-preview')
        assert preview['hx-get'] == reverse('admin:qa_test_format_preview')
        assert preview['hx-include'] == '#id_formatting'

    def test_description_preview_uses_the_test_list_endpoint(self):
        soup = _soup(self.client.get(self.url))
        ta = soup.find('textarea', id='id_description')
        assert ta['hx-post'] == reverse('admin:qa_testlist_desc_preview')
        assert ta['hx-target'] == '#tst-desc-preview'

    def test_attachments_card_posts_the_test_key(self):
        soup = _soup(self.client.get(self.url))
        container = soup.find(id='attachments-editor-container')
        assert container['data-fk-name'] == 'test'
        assert container['data-parent-id'] == str(self.test.pk)

    def test_errors_mark_the_field(self):
        data = {
            'name': 'Wrap', 'slug': 'wrap', 'category': self.test.category.pk, 'type': models.WRAPAROUND,
            'attachment_set-TOTAL_FORMS': 0, 'attachment_set-INITIAL_FORMS': 0, '_continue': '1',
        }
        soup = _soup(self.client.post(reverse('admin:qa_test_add'), data))
        field = soup.find('input', id='id_wrap_high').find_parent(class_='tlb-field')
        assert 'tst-has-error' in field['class']
        assert field.select_one('.errorlist')

    def test_save_round_trip(self):
        data = {
            'name': 'Couch interlock', 'slug': 'couch_interlock', 'category': self.test.category.pk,
            'type': models.MULTIPLE_CHOICE, 'choices': 'Works,Fails,Not tested', 'formatting': '',
            'chart_visibility': 'on', 'require_comment': 'on',
            'attachment_set-TOTAL_FORMS': 0, 'attachment_set-INITIAL_FORMS': 0, '_save': '1',
        }
        resp = self.client.post(reverse('admin:qa_test_add'), data)
        assert resp.status_code == 302
        test = models.Test.objects.get(slug='couch_interlock')
        assert test.choices == 'Works,Fails,Not tested'
        assert test.require_comment and not test.skip_without_comment


class TestUsedInCard(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.test = qa_utils.create_test(name='Output')
        self.url = reverse('admin:qa_test_change', args=(self.test.pk,))

    def test_lists_and_machines(self):
        tl = qa_utils.create_test_list(name='Daily')
        qa_utils.create_test_list_membership(test_list=tl, test=self.test)
        uti = qa_utils.create_unit_test_info(test=self.test)
        soup = _soup(self.client.get(self.url))
        card = soup.find(id='tst-used-card')
        link = card.select_one('ul.tst-used-lists a')
        assert link['href'] == reverse('admin:qa_testlist_change', args=(tl.pk,))
        assert 'Daily' in link.get_text()
        row = card.select_one('tr[data-uti="%d"]' % uti.pk)
        assert row.select_one('a')['href'] == reverse('admin:qa_unittestinfo_change', args=(uti.pk,))
        counts = soup.find(id='tst-header-counts').get_text(' ', strip=True)
        assert 'In 1 test list' in counts and '1 machine' in counts

    def test_empty(self):
        card = _soup(self.client.get(self.url)).find(id='tst-used-card')
        assert len(card.select('p.tst-empty')) == 2
        assert not card.select('table')


class TestViewOnlyUser(TestCase):

    def test_read_only_fieldsets_instead_of_cards(self):
        test = qa_utils.create_test(name='Output')
        viewer = create_user(is_superuser=False, uname='viewer', pwd='pwd')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='qa', codename='view_test'))
        self.client.login(username='viewer', password='pwd')
        soup = _soup(self.client.get(reverse('admin:qa_test_change', args=(test.pk,))))
        assert not soup.find(id='tst-type-card')
        assert soup.select('fieldset.module')
        assert not soup.select('.tl-header-actions button[type=submit]')
        assert 'Output' in soup.get_text()


class TestFormatPreview(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.url = reverse('admin:qa_test_format_preview')

    def _preview(self, fmt):
        resp = self.client.get(self.url, {'formatting': fmt})
        assert resp.status_code == 200
        soup = BeautifulSoup(resp.content.decode(), 'html.parser')
        return [c.get_text() for c in soup.select('code.tst-format-out')], soup.select_one('.tst-format-bad')

    def test_preset(self):
        shown, bad = self._preview('%.2f')
        assert shown == ['123.46', '0.00'] and bad is None

    def test_new_style(self):
        shown, bad = self._preview('{:06.1f}')
        assert shown == ['0123.5', '0000.0'] and bad is None

    def test_matches_what_results_show(self):
        from qatrack.qa.utils import format_qc_value
        for fmt in ('', '%.3E', 'abc%', 'abc', '%s units', '{:.2g}'):
            shown, _ = self._preview(fmt)
            assert shown == [format_qc_value(v, fmt) for v in qa_admin.TEST_FORMAT_SAMPLES], fmt

    def test_unusable_format_is_pointed_out(self):
        _, bad = self._preview('abc%')
        assert "can't format a number" in bad.get_text()
        _, bad = self._preview('abc')
        assert 'leaves the number out' in bad.get_text()

    def test_staff_only(self):
        self.client.logout()
        resp = self.client.get(self.url, {'formatting': '%.2f'})
        assert resp.status_code == 302


class TestSharedAssets(TestCase):

    def test_both_pages_include_the_shared_styles_and_script(self):
        for name in (ASSETS, TL_ASSETS):
            html = render_to_string(name, {})
            assert '.tl-header-bar {' in html, name
            assert '.tl-details-card {' in html, name
            assert '.tl-attachments-card {' in html, name
            assert 'window.qaInitAttachmentsEditor = function' in html, name

    def test_attachments_js_uses_the_containers_key(self):
        js = render_to_string('admin/qa/shared/_attachments_js.html', {})
        assert 'container.getAttribute("data-fk-name")' in js
        assert '"-" + fkName' in js
        assert '-testlist"' not in js

    def test_test_list_page_still_posts_the_testlist_key(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        tl = qa_utils.create_test_list(name='Daily')
        soup = _soup(self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,))))
        assert soup.find(id='attachments-editor-container')['data-fk-name'] == 'testlist'

    def test_choices_chips_keep_typed_text_on_submit(self):
        js = render_to_string(ASSETS, {})
        chips = re.search(r'function initChoices\(\).*?\n  }\n', js, re.S).group(0)
        assert 'entry.addEventListener("blur"' in chips
        assert 'form.addEventListener("submit"' in chips
        assert 'input.value = choices.join(",")' in chips


class TestTestPageContrast(TestCase):
    """Text on the white cards is at least 4.5:1, and the switch track 3:1 in both states."""

    WHITE = '#ffffff'

    @staticmethod
    def _luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def _ratio(self, fg, bg):
        hi, lo = sorted((self._luminance(fg), self._luminance(bg)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def _colour(self, selector, prop='color'):
        html = render_to_string(ASSETS, {})
        style = re.sub(r'/\*.*?\*/', '', html[html.index('<style>'):html.index('</style>')], flags=re.S)
        for body in re.findall(r'(?:^|[},])\s*%s\s*\{([^}]*)\}' % re.escape(selector), style, flags=re.M):
            value = re.search(r'(?<![\w-])%s:\s*#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})' % re.escape(prop), body)
            if value:
                hex_digits = value.group(1).lower()
                if len(hex_digits) == 3:
                    hex_digits = ''.join(c * 2 for c in hex_digits)
                return '#' + hex_digits
        self.fail('%s { %s } not found' % (selector, prop))

    def test_text(self):
        for selector, bg in (
            ('.tst-help', self.WHITE), ('.tst-switch-title', self.WHITE), ('.tst-section-label', self.WHITE),
            ('.tst-format-bad', self.WHITE), ('.tst-format-in', self.WHITE), ('.tst-calc-note', self.WHITE),
            ('ul.tst-used-lists a', self.WHITE), ('.tst-empty', self.WHITE), ('.tst-chip-num', '#f4f4f4'),
            ('.tst-type-help', '#f5f7fa'), ('code.tst-format-out', '#f5f7fa'),
        ):
            colour = self._colour(selector)
            assert self._ratio(colour, bg) >= 4.5, '%s %s on %s' % (selector, colour, bg)

    def test_switch_track(self):
        off = self._colour('.tst-switch-track', 'background')
        on = self._colour('.tst-switch-input:checked + .tst-switch-track', 'background')
        for colour in (off, on):
            assert self._ratio(colour, self.WHITE) >= 3.0, colour
