"""QC admin step 4: Test List Instances, Test Instances and the test pack pages.

The Test List Instance and Test Instance change pages use the shared QC cards with
their own fieldsets (every field that was editable stays editable), the Test List
Instance page has a "View on Site" button, its delete page lists the linked service
events in cards, and the test pack export/import pages use the title row and cards.
"""

from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils
from qatrack.service_log import models as sl_models
from qatrack.service_log.tests import utils as sl_utils

# The fields each change form edited before the card layout: they must all stay editable.
TLI_EDITABLE = {
    'work_started',
    'work_completed',
    'due_date',
    'in_progress',
    'user_key',
    'include_for_scheduling',
    'reviewed',
    'all_reviewed',
    'day',
    'modified',
}
TI_EDITABLE = {
    'status',
    'value',
    'string_value',
    'date_value',
    'datetime_value',
    'json_value',
    'skipped',
    'comment',
    'work_completed',
    'order',
    'created',
}


def _split(dt):
    """A datetime as the admin's split date/time inputs expect it."""
    dt = timezone.localtime(dt)
    return dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M')


def _inline_management(resp):
    """Management form data for every inline on a change page (no rows added)."""
    data = {}
    for inline in resp.context['inline_admin_formsets']:
        prefix = inline.formset.prefix
        data.update(
            {
                '%s-TOTAL_FORMS' % prefix: '0',
                '%s-INITIAL_FORMS' % prefix: '0',
                '%s-MIN_NUM_FORMS' % prefix: '0',
                '%s-MAX_NUM_FORMS' % prefix: '1000',
            }
        )
    return data


def _superuser_request():
    request = RequestFactory().get('/')
    request.user = create_user(is_superuser=True, uname='user', pwd='pwd')
    return request


class TestTestListInstanceChangePage(TestCase):
    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tli = qa_utils.create_test_list_instance()
        self.url = reverse('admin:qa_testlistinstance_change', args=(self.tli.pk,))

    def test_form_keeps_every_editable_field(self):
        ma = qa_admin.admin.site._registry[models.TestListInstance]
        form = ma.get_form(_superuser_request(), self.tli)
        self.assertEqual(set(form.base_fields), TLI_EDITABLE)

    def test_change_page_draws_cards_and_title(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('Edit Test List Instance', html)
        self.assertIn(self.tli.test_list.name, html)
        for card in ('qc-card-performed', 'qc-card-review', 'qc-card-scheduling-record', 'qc-card-comments'):
            self.assertIn('id="%s"' % card, html)
        self.assertIn('fa-clipboard', html)
        # The attachments inline is the shared attachments card
        self.assertIn('attachments-editor-container', html)
        # Read-only context and the editable fields
        self.assertIn(self.tli.unit_test_collection.unit.name, html)
        self.assertIn('name="work_completed_0"', html)
        self.assertIn('name="user_key"', html)
        self.assertIn('class="qc-check" for="id_all_reviewed"', html)
        self.assertIn('No comments', html)
        self.assertIn('.qci-label', html)
        # No add page for instances: they're created by performing QC
        self.assertNotIn('id="qc-saveas-btn"', html)

    def test_view_on_site_button_links_to_the_session_page(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="qci-view-on-site-btn"', html)
        self.assertIn('href="%s"' % reverse('view_test_list_instance', kwargs={'pk': self.tli.pk}), html)

    def test_view_on_site_hidden_without_permission_to_view_sessions(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testlistinstance'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('id="qci-view-on-site-btn"', html)

    def test_comments_are_listed(self):
        from django.contrib.sites.models import Site
        from django_comments.models import Comment

        Comment.objects.create(
            content_object=self.tli,
            user=self.user,
            comment='Chamber re-zeroed before repeat',
            site=Site.objects.get_current(),
            submit_date=timezone.now(),
        )
        html = self.client.get(self.url).content.decode()
        self.assertIn('class="qci-comments"', html)
        self.assertIn('Chamber re-zeroed before repeat', html)

    def test_save_still_saves(self):
        resp = self.client.get(self.url)
        ws_d, ws_t = _split(self.tli.work_started)
        wc_d, wc_t = _split(self.tli.work_completed)
        mod_d, mod_t = _split(timezone.now())
        data = {
            'work_started_0': ws_d,
            'work_started_1': ws_t,
            'work_completed_0': wc_d,
            'work_completed_1': wc_t,
            'due_date_0': '',
            'due_date_1': '',
            'day': '0',
            'include_for_scheduling': 'on',
            'user_key': 'session-key-1',
            'reviewed_0': '',
            'reviewed_1': '',
            'all_reviewed': 'on',
            'modified_0': mod_d,
            'modified_1': mod_t,
            '_continue': 'Save and Continue Editing',
        }
        data.update(_inline_management(resp))
        resp = self.client.post(self.url, data)
        self.assertEqual(
            resp.status_code,
            302,
            getattr(resp, 'context', None) and resp.context['adminform'].form.errors,
        )
        self.tli.refresh_from_db()
        self.assertEqual(self.tli.user_key, 'session-key-1')
        self.assertTrue(self.tli.all_reviewed)

    def test_errors_render_inside_the_card(self):
        resp = self.client.get(self.url)
        data = {'work_started_0': '', 'work_started_1': '', 'modified_0': '', 'modified_1': '', 'day': '0'}
        data.update(_inline_management(resp))
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('qc-field field-work_started qc-has-error', html)

    def test_view_only_user_gets_read_only_cards(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testlistinstance'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Test List Instance', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertIn('id="qc-card-performed"', html)
        self.assertNotIn('name="user_key"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertNotIn('id="qc-delete-btn"', html)


class TestTestListInstanceChangeList(TestCase):
    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tli = qa_utils.create_test_list_instance()

    def test_list_shows_readable_columns_and_no_add(self):
        resp = self.client.get(reverse('admin:qa_testlistinstance_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-index-header qc-index-header"', html)
        self.assertIn(self.tli.unit_test_collection.unit.name, html)
        self.assertIn(self.tli.test_list.name, html)
        self.assertIn('Unreviewed', html)
        self.assertIn('class="qci-label qci-pf-tolerance"', html)
        self.assertNotIn('TestListInstance(pk=', html)
        self.assertNotIn('class="tl-btn tl-btn-primary"', html)


class TestTestListInstanceDeletePage(TestCase):
    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tli = qa_utils.create_test_list_instance()
        self.ti = qa_utils.create_test_instance(test_list_instance=self.tli)
        usa = sl_utils.create_unit_service_area(unit=self.tli.unit_test_collection.unit)
        # A status that doesn't require review goes back to the default when the session is deleted
        self.default_ses = sl_utils.create_service_event_status(name='Service Pending', is_default=True)
        approved = sl_utils.create_service_event_status(name='Approved', is_review_required=False)
        self.se_ib = sl_utils.create_service_event(
            unit_service_area=usa,
            service_status=approved,
            add_test_list_instance_initiated_by=self.tli,
        )
        self.rtsqa = sl_utils.create_return_to_service_qa(add_test_list_instance=self.tli)
        self.url = reverse('admin:qa_testlistinstance_delete', args=(self.tli.pk,))

    def test_delete_page_lists_linked_service_events_in_cards(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('Delete Test List Instance', html)
        self.assertIn('id="qci-delete-session"', html)
        self.assertIn('id="qci-delete-rtsqa"', html)
        self.assertIn('id="qci-delete-initiated"', html)
        self.assertIn('Service Event %d' % self.se_ib.pk, html)
        self.assertIn('Service Event %d' % self.rtsqa.service_event.pk, html)
        # The initiated-by event's status changes to the default: both labels are shown
        self.assertIn('Approved', html)
        self.assertIn('qci-new-status', html)
        self.assertIn('Service Pending', html)
        # The test instances deleted with it
        self.assertIn('id="qci-delete-tests"', html)
        self.assertIn(self.ti.unit_test_info.test.name, html)
        # The confirm form and the warning
        self.assertIn('id="qci-delete-confirm"', html)
        self.assertIn("This can't be undone.", html)
        self.assertIn('name="post" value="yes"', html)
        self.assertIn('No, Take Me Back', html)
        # The breadcrumb links to the change page (it used to miss the slash)
        self.assertIn('href="%s"' % reverse('admin:qa_testlistinstance_change', args=(self.tli.pk,)), html)

    def test_existing_context_still_provided(self):
        resp = self.client.get(self.url)
        self.assertTrue(len(resp.context['se_rtsqa_qs']) > 0)
        self.assertTrue(len(resp.context['se_ib_qs']) > 0)

    def test_confirming_deletes_and_keeps_service_events(self):
        resp = self.client.post(self.url, {'post': 'yes'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(models.TestListInstance.objects.filter(pk=self.tli.pk).exists())
        self.assertFalse(models.TestInstance.objects.filter(pk=self.ti.pk).exists())
        self.se_ib.refresh_from_db()
        self.assertEqual(self.se_ib.service_status, self.default_ses)
        self.assertTrue(sl_models.ServiceEvent.objects.filter(pk=self.rtsqa.service_event.pk).exists())

    def test_without_delete_permission_is_refused(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testlistinstance'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        self.assertEqual(self.client.get(self.url).status_code, 403)


class TestTestInstanceChangePage(TestCase):
    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.status = qa_utils.create_status(name='Unreviewed', slug='unreviewed')
        self.ti = qa_utils.create_test_instance(status=self.status)
        # save() works pass/fail out from the value, so set it directly
        models.TestInstance.objects.filter(pk=self.ti.pk).update(pass_fail=models.TOLERANCE)
        self.ti.refresh_from_db()
        self.url = reverse('admin:qa_testinstance_change', args=(self.ti.pk,))

    def test_form_keeps_every_editable_field(self):
        ma = qa_admin.admin.site._registry[models.TestInstance]
        form = ma.get_form(_superuser_request(), self.ti)
        self.assertEqual(set(form.base_fields), TI_EDITABLE)

    def test_change_page_draws_cards(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Edit Test Instance', html)
        for card in ('qc-card-result', 'qc-card-context', 'qc-card-stored-analysis-results'):
            self.assertIn('id="%s"' % card, html)
        self.assertIn('name="value"', html)
        self.assertIn('name="status"', html)
        self.assertIn('class="qc-check" for="id_skipped"', html)
        # Pass/fail as a status label, with its word
        self.assertIn('class="qci-label qci-pf-tolerance">Tolerance</span>', html)
        # Context links back to the unit test info and the session
        uti = self.ti.unit_test_info
        self.assertIn(reverse('admin:qa_unittestinfo_change', args=(uti.pk,)), html)
        self.assertIn(reverse('admin:qa_testlistinstance_change', args=(self.ti.test_list_instance_id,)), html)
        self.assertIn(uti.test.name, html)
        self.assertIn('attachments-editor-container', html)

    def test_save_still_saves(self):
        resp = self.client.get(self.url)
        wc_d, wc_t = _split(self.ti.work_completed)
        cr_d, cr_t = _split(self.ti.created)
        data = {
            'value': '2.5',
            'string_value': '',
            'date_value': '',
            'datetime_value_0': '',
            'datetime_value_1': '',
            'json_value': '',
            'status': str(self.status.pk),
            'comment': 'Repeated after warm-up',
            'work_completed_0': wc_d,
            'work_completed_1': wc_t,
            'order': '0',
            'created_0': cr_d,
            'created_1': cr_t,
            '_continue': 'Save and Continue Editing',
        }
        data.update(_inline_management(resp))
        resp = self.client.post(self.url, data)
        self.assertEqual(
            resp.status_code,
            302,
            getattr(resp, 'context', None) and resp.context['adminform'].form.errors,
        )
        self.ti.refresh_from_db()
        self.assertEqual(self.ti.value, 2.5)
        self.assertEqual(self.ti.comment, 'Repeated after warm-up')

    def test_errors_render_inside_the_card(self):
        resp = self.client.get(self.url)
        data = {'value': 'not a number', 'status': str(self.status.pk), 'order': '0'}
        data.update(_inline_management(resp))
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('qc-field field-value qc-has-error', html)

    def test_view_only_user_gets_read_only_cards(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testinstance'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Test Instance', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertIn('id="qc-card-result"', html)
        self.assertNotIn('name="value"', html)
        self.assertNotIn('id="qc-save-btn"', html)

    def test_list_shows_status_and_pass_fail_labels(self):
        resp = self.client.get(reverse('admin:qa_testinstance_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="qci-label" style="border-color: %s">Unreviewed</span>' % self.status.colour, html)
        self.assertIn('class="qci-label qci-pf-tolerance">Tolerance</span>', html)
        self.assertIn('.qci-pf-tolerance', html)
        self.assertIn(self.ti.unit_test_info.test.name, html)
        self.assertNotIn('TestInstance(pk=', html)
        self.assertNotIn('class="tl-btn tl-btn-primary"', html)


class TestTestPackPages(TestCase):
    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.test_list = qa_utils.create_test_list()
        self.test_list.description = '<p>Daily <strong>output</strong> checks</p>'
        self.test_list.save()
        self.test = qa_utils.create_test()
        qa_utils.create_test_list_membership(self.test_list, self.test)

    def test_export_page_draws_title_row_and_cards(self):
        resp = self.client.get(reverse('admin:qa_export_testpack'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('id="qtp-download-btn"', html)
        self.assertIn('form="qtp-export-form"', html)
        self.assertIn('id="qtp-export-form"', html)
        for card in ('qtp-testlists-card', 'qtp-testlistcycles-card', 'qtp-tests-card', 'qtp-summary-card'):
            self.assertIn('id="%s"' % card, html)
        # What testpack-export.js needs is still there
        for el in (
            'id="testlists-table"',
            'id="testlistcycles-table"',
            'id="tests-table"',
            'id="testlists-summary"',
            'id="testlistcycles-summary"',
            'id="tests-summary"',
            'class="loading',
            'tp-container',
            'js/testpack-export.js',
        ):
            self.assertIn(el, html)
        for name in ('testlists', 'testlistcycles', 'tests', 'name', 'description'):
            self.assertIn('name="%s"' % name, html)
        self.assertIn('Test List Cycles', html)
        self.assertNotIn('Test Lists Cycles', html)
        self.assertNotIn('style="', html.split('id="content-main"', 1)[1].split('<div id="footer"')[0])

    def test_export_descriptions_are_plain_text(self):
        html = self.client.get(reverse('admin:qa_export_testpack')).content.decode()
        self.assertIn('Daily output checks', html)
        self.assertNotIn('&lt;p&gt;', html)

    def test_export_errors_render_in_the_card(self):
        resp = self.client.post(
            reverse('admin:qa_export_testpack'),
            {
                'name': '',
                'description': '',
                'testlists': '',
                'testlistcycles': '',
                'tests': '',
            },
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="errorlist nonfield qtp-errors"', html)
        self.assertIn('qc-field field-name qc-has-error', html)

    def test_export_still_downloads(self):
        resp = self.client.post(
            reverse('admin:qa_export_testpack'),
            {
                'name': 'daily-pack',
                'description': '',
                'testlists': str(self.test_list.pk),
                'testlistcycles': '',
                'tests': '',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Disposition'], 'attachment; filename=daily-pack.tpk')

    def test_import_page_draws_title_row_and_cards(self):
        resp = self.client.get(reverse('admin:qa_import_testpack'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('id="qtp-import-btn"', html)
        self.assertIn('form="qtp-import-form"', html)
        for card in ('qtp-file-card', 'qtp-details-card', 'qtp-summary-card', 'qtp-testlists-card'):
            self.assertIn('id="%s"' % card, html)
        # What testpack-import.js needs is still there
        for el in (
            'id="id_testpack"',
            'name="testpack_data"',
            'id="name"',
            'id="created-by"',
            'id="version"',
            'id="description"',
            'id="testlists-table"',
            'id="testlistcycles-table"',
            'id="tests-table"',
            'id="testlists-summary"',
            'js/testpack-import.js',
            'window.test_types',
        ):
            self.assertIn(el, html)
        self.assertIn('Test List Cycles', html)
        self.assertNotIn('Test Lists Cycles', html)

    def test_pages_need_change_test_list_permission(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_testlist'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        self.assertEqual(self.client.get(reverse('admin:qa_export_testpack')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:qa_import_testpack')).status_code, 403)
