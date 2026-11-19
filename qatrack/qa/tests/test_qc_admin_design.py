"""The QC-wide admin pages (admin/qa/change_form.html and admin/qa/change_list.html).

Every QC model without a template of its own gets the card layout from these two
templates; these tests use Test Instance Status, which has no override, as the example,
and smoke-test every QC admin page so a model whose fields the cards can't draw is
caught here.
"""

import re

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils


class TestQCChangeForm(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.status = qa_utils.create_status(name="Approved", slug="approved")

    def test_add_page_draws_title_row_and_cards(self):
        resp = self.client.get(reverse('admin:qa_testinstancestatus_add'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('Add Test Instance Status', html)
        self.assertIn('class="tl-details-card qc-card', html)
        self.assertIn('id="qc-save-btn"', html)
        # One save button group: Django's bottom submit row isn't drawn
        self.assertNotIn('class="submit-row"', html)
        # No History/Delete before the object exists
        self.assertNotIn('id="qc-history-btn"', html)
        self.assertNotIn('id="qc-delete-btn"', html)

    def test_fields_render_once_with_required_marker(self):
        html = self.client.get(reverse('admin:qa_testinstancestatus_add')).content.decode()
        self.assertEqual(html.count('name="name"'), 1)
        self.assertEqual(html.count('name="slug"'), 1)
        self.assertRegex(html, r'<label for="id_name">[^<]*<em class="tl-req"')
        # Checkbox fields use the inline checkbox row
        self.assertIn('class="qc-check" for="id_is_default"', html)

    def test_change_page_shows_id_history_and_delete(self):
        url = reverse('admin:qa_testinstancestatus_change', args=(self.status.pk,))
        html = self.client.get(url).content.decode()
        self.assertIn('Edit Test Instance Status', html)
        self.assertIn('ID %d' % self.status.pk, html)
        self.assertIn('id="qc-history-btn"', html)
        self.assertIn('id="qc-delete-btn"', html)

    def test_save_and_continue_still_saves(self):
        url = reverse('admin:qa_testinstancestatus_change', args=(self.status.pk,))
        data = {
            'name': 'Approved by physics',
            'slug': 'approved',
            'description': '',
            'is_default': 'on',
            'requires_review': 'on',
            'valid': 'on',
            'colour': 'rgba(0,166,90,1)',
            '_continue': 'Save and Continue Editing',
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context['adminform'].form.errors)
        self.status.refresh_from_db()
        self.assertEqual(self.status.name, 'Approved by physics')

    def test_errors_render_inside_the_card(self):
        url = reverse('admin:qa_testinstancestatus_add')
        resp = self.client.post(url, {'name': '', 'slug': '', 'colour': 'rgba(0,166,90,1)', '_save': 'Save'})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('qc-has-error', html)
        self.assertIn('class="errorlist', html)
        # the error sits under its input, so the input stays level with the others in its row
        field = html.split('qc-field field-name ')[1].split('qc-field field-')[0]
        self.assertLess(field.index('class="qc-widget"'), field.index('class="errorlist'))

    def test_view_only_user_gets_read_only_cards(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testinstancestatus'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        url = reverse('admin:qa_testinstancestatus_change', args=(self.status.pk,))
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Test Instance Status', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertNotIn('id="qc-delete-btn"', html)
        self.assertIn('>Back<', html)


class TestQCChangeList(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        qa_utils.create_status()

    def test_list_draws_header_results_card_and_add_button(self):
        resp = self.client.get(reverse('admin:qa_testinstancestatus_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-index-header qc-index-header"', html)
        self.assertIn('class="tl-results-head"', html)
        self.assertIn('class="tl-btn tl-btn-primary"', html)
        self.assertIn('window.qaChangelist', html)

    def test_filters_start_collapsed(self):
        # Tolerances has a "type" filter
        resp = self.client.get(reverse('admin:qa_tolerance_changelist'))
        html = resp.content.decode()
        self.assertIn('id="changelist-filter"', html)
        self.assertIn('<details data-filter-title=', html)
        self.assertIsNone(re.search(r'<details[^>]*\bopen\b', html))

    def test_test_list_page_uses_the_shared_list_assets(self):
        html = self.client.get(reverse('admin:qa_testlist_changelist')).content.decode()
        self.assertIn('window.qaChangelist', html)
        self.assertIn('#changelist-filter details > summary', html)
        # Its own column widths stay with it
        self.assertIn('.column-col_frequency', html)


class TestEveryQCAdminPageRenders(TestCase):
    """Smoke test: the list and add page of every QC admin render with the cards."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        utc = qa_utils.create_unit_test_collection()
        qa_utils.create_test_list_instance(unit_test_collection=utc)
        qa_utils.create_tolerance()
        qa_utils.create_category(name="Dosimetry", slug="dosimetry")

    def test_list_and_add_pages(self):
        for model, model_admin in admin.site._registry.items():
            if model._meta.app_label != 'qa':
                continue
            name = model._meta.model_name
            with self.subTest(model=name, page='changelist'):
                resp = self.client.get(reverse('admin:qa_%s_changelist' % name))
                self.assertEqual(resp.status_code, 200)
            try:
                add_url = reverse('admin:qa_%s_add' % name)
            except NoReverseMatch:
                continue
            with self.subTest(model=name, page='add'):
                resp = self.client.get(add_url)
                self.assertIn(resp.status_code, (200, 403))

    def test_change_pages(self):
        for model in [models.TestInstanceStatus, models.Tolerance, models.Frequency, models.Category,
                      models.TestListCycle, models.UnitTestCollection, models.TestListInstance,
                      models.TestInstance, models.AutoReviewRuleSet]:
            obj = model.objects.first()
            if obj is None:
                continue
            name = model._meta.model_name
            with self.subTest(model=name):
                resp = self.client.get(reverse('admin:qa_%s_change' % name, args=(obj.pk,)))
                self.assertEqual(resp.status_code, 200)


class TestQCCardLabels(TestCase):
    """Labels on the cards (admin/qa/includes/qc_fieldset_card.html)."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        utc = qa_utils.create_unit_test_collection()
        self.tli = qa_utils.create_test_list_instance(unit_test_collection=utc)

    def tli_html(self):
        return self.client.get(reverse('admin:qa_testlistinstance_change', args=(self.tli.pk,))).content.decode()

    def test_no_label_points_nowhere(self):
        html = self.tli_html()
        self.assertNotIn('for=""', html)
        rule_set_html = self.client.get(reverse('admin:qa_autoreviewruleset_add')).content.decode()
        self.assertNotIn('for=""', rule_set_html)

    def test_split_date_and_time_label_points_at_the_date(self):
        html = self.tli_html()
        self.assertIn('id="id_work_started_0"', html)
        self.assertRegex(html, r'<label for="id_work_started_0">')

    def test_label_repeating_the_card_title_is_only_for_screen_readers(self):
        html = self.tli_html()
        # The Comments card holds one field, also called Comments
        self.assertIn('<span class="qc-label tl-visually-hidden">Comments</span>', html)
        # Labels that differ from their card's title stay visible
        self.assertIn('<span class="qc-label">Test List</span>', html)

    def test_required_single_field_keeps_its_label(self):
        # Rule Sets' Rules card holds one required field, also called Rules
        html = self.client.get(reverse('admin:qa_autoreviewruleset_add')).content.decode()
        self.assertRegex(html, r'<label>Rules <em class="tl-req"')


class TestSharedDialogStyles(TestCase):
    """The dialog frame and the Reference and Tolerance dialog have one copy of their CSS."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.cycle = qa_utils.create_cycle(test_lists=[qa_utils.create_test_list()])

    def test_pages_with_dialogs_include_the_dialog_frame(self):
        frame = 'Dialog frame (admin/qa/shared/_modal_css.html)'
        reftol = 'Reference and Tolerance dialogs (admin/qa/shared/_reftol_dialog_css.html)'
        pages = {
            'builder': (reverse('admin:qa_testlist_add'), True),
            'cycle': (reverse('admin:qa_testlistcycle_change', args=(self.cycle.pk,)), False),
            'refs and tols': (reverse('admin:qa_unittestinfo_changelist'), True),
        }
        for page, (url, has_reftol) in pages.items():
            with self.subTest(page=page):
                html = self.client.get(url).content.decode()
                self.assertEqual(html.count(frame), 1)
                self.assertEqual(html.count(reftol), 1 if has_reftol else 0)

    def test_list_without_filters_draws_one_top_border(self):
        html = self.client.get(reverse('admin:qa_autoreviewruleset_changelist')).content.decode()
        self.assertIn('#changelist:not(.filtered) .tl-results-head { border-top:0;', html)
