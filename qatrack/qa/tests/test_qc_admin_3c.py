"""Set References & Tolerances (UnitTestInfoAdmin) pages in the QC admin card design.

The list's "Not set" highlighting, the pencil that opens the Test List builder's
Reference and Tolerance dialog from the list, the change page's three cards, and the
Copy References & Tolerances and Set Multiple pages.
"""

import re

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils


def grant(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(content_type__app_label='qa', codename=codename))


def row_html(html, uti):
    """The changelist row (<tr>…</tr>) for one UnitTestInfo."""
    link = 'href="%s"' % reverse('admin:qa_unittestinfo_change', args=[uti.pk])
    at = html.index(link)
    return html[html.rindex('<tr', 0, at) : html.index('</tr>', at)]


def cell(row, name):
    return re.search(r'<td class="field-%s[^"]*">(.*?)</td>' % name, row, re.S).group(1)


class TestListNotSet(TestCase):
    """Reference and Tolerance columns: "Not set" is highlighted only where it causes No Tol Set."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.unit = qa_utils.create_unit(name='Linac 1')
        self.url = reverse('admin:qa_unittestinfo_changelist')

    def _uti(self, test_type, ref=None, tol=None, **kwargs):
        test = qa_utils.create_test(test_type=test_type, **kwargs)
        return qa_utils.create_unit_test_info(unit=self.unit, test=test, ref=ref, tol=tol)

    def _row(self, uti):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        return row_html(resp.content.decode(), uti)

    def test_numerical_without_reference_or_tolerance_is_highlighted(self):
        row = self._row(self._uti(models.SIMPLE))
        for name in ('reference_display', 'tolerance_display'):
            value = cell(row, name)
            self.assertIn('class="qcr-missing"', value)
            self.assertIn('Not set', value)
            self.assertIn('will show No Tol Set', value)

    def test_numerical_with_reference_only_highlights_the_tolerance(self):
        row = self._row(self._uti(models.SIMPLE, ref=qa_utils.create_reference(value=100)))
        self.assertEqual(cell(row, 'reference_display'), '100')
        self.assertIn('qcr-missing', cell(row, 'tolerance_display'))

    def test_set_tolerance_shows_its_name_with_plain_reading(self):
        tol = qa_utils.create_tolerance()
        row = self._row(self._uti(models.SIMPLE, ref=qa_utils.create_reference(), tol=tol))
        value = cell(row, 'tolerance_display')
        self.assertIn('>%s</span>' % tol.name, value)
        self.assertIn('title="%s"' % tol.plain_display_title(), value)
        self.assertNotIn('Not set', row)

    def test_boolean_tolerance_is_optional(self):
        row = self._row(self._uti(models.BOOLEAN))
        self.assertIn('qcr-missing', cell(row, 'reference_display'))
        tol = cell(row, 'tolerance_display')
        self.assertIn('class="qcr-none"', tol)
        self.assertNotIn('qcr-missing', tol)

    def test_string_types_have_no_reference(self):
        row = self._row(self._uti(models.MULTIPLE_CHOICE, choices='a,b,c'))
        ref = cell(row, 'reference_display')
        self.assertIn('class="qcr-unused"', ref)
        self.assertIn('Not used', ref)
        self.assertIn('qcr-missing', cell(row, 'tolerance_display'))

    def test_upload_never_uses_limits_and_has_no_pencil(self):
        row = self._row(self._uti(models.UPLOAD))
        for name in ('reference_display', 'tolerance_display'):
            self.assertIn('Not used', cell(row, name))
            self.assertNotIn('qcr-missing', cell(row, name))
        self.assertNotIn('qcr-reftol-btn', row)

    def test_rule_is_the_builders(self):
        """Highlighted exactly where machine_limit_usage (the builder's rule) says "required"."""
        for test_type in (
            models.SIMPLE,
            models.BOOLEAN,
            models.MULTIPLE_CHOICE,
            models.STRING,
            models.DATE,
            models.WRAPAROUND,
            models.COMPOSITE,
        ):
            uti = self._uti(test_type, choices='a,b' if test_type == models.MULTIPLE_CHOICE else None)
            usage = qa_admin.machine_limit_usage(uti.test)
            for part in ('reference', 'tolerance'):
                with self.subTest(test_type=test_type, part=part):
                    html = qa_admin.unit_test_info_missing_html(uti, part)
                    self.assertEqual('qcr-missing' in html, usage[part] == 'required')
                    self.assertEqual('Not used' in html, usage[part] == 'unused')


class TestListPencil(TestCase):
    """The pencil opens the builder's Reference and Tolerance dialog, for users who may change them."""

    def setUp(self):
        self.unit = qa_utils.create_unit(name='Linac 1')
        self.test = qa_utils.create_test(name='Output', test_type=models.SIMPLE)
        self.ref = qa_utils.create_reference(value=100)
        self.tol = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.test, ref=self.ref)
        self.url = reverse('admin:qa_unittestinfo_changelist')
        self.dialog_url = reverse('admin:qa_testlist_machine_ref_tol', args=[self.uti.pk])

    def _login(self, *codenames):
        user = create_user(uname='staff', pwd='pwd', is_staff=True, is_superuser=False)
        grant(user, *codenames)
        self.client.login(username='staff', password='pwd')
        return user

    def test_pencil_for_users_who_can_change(self):
        self._login('view_unittestinfo', 'change_unittestinfo')
        html = self.client.get(self.url).content.decode()
        row = row_html(html, self.uti)
        self.assertIn('class="qcr-reftol-btn"', row)
        self.assertIn('data-reftol-url="%s"' % self.dialog_url, row)
        self.assertIn('aria-label="Set reference and tolerance for Output on Linac 1"', row)
        # the glue script and its status note are on the page
        self.assertIn('id="qcr-note"', html)
        self.assertIn('button.qcr-reftol-btn', html)
        self.assertIn('id="qcr-copy-btn"', html)

    def test_read_only_users_get_the_link_and_no_pencil(self):
        self._login('view_unittestinfo')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        row = row_html(html, self.uti)
        self.assertNotIn('class="qcr-reftol-btn"', html)
        self.assertNotIn('class="column-set_ref_tol"', html)
        self.assertIn(reverse('admin:qa_unittestinfo_change', args=[self.uti.pk]), row)
        # the copy page needs change permission, so its button isn't offered
        self.assertNotIn('id="qcr-copy-btn"', html)
        self.assertNotIn('Add Set References', html)

    def test_dialog_opens_and_saves_from_the_list(self):
        """A user with only the Unit Test Info permissions (no test list ones) can use the dialog."""
        self._login('view_unittestinfo', 'change_unittestinfo')
        resp = self.client.get(self.dialog_url, headers={'x-requested-with': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="tl-reftol-form"')
        self.assertContains(resp, 'action="%s"' % self.dialog_url)

        resp = self.client.post(
            self.dialog_url,
            {
                'reference_value': '101',
                'tolerance': self.tol.pk,
                'comment': 'From the list',
            },
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference.value, 101)
        self.assertEqual(self.uti.tolerance, self.tol)
        change = models.UnitTestInfoChange.objects.get(unit_test_info=self.uti)
        self.assertEqual(change.comment, 'From the list')

        # the response carries the list's own cell HTML, which the glue script puts in the row
        row = row_html(self.client.get(self.url).content.decode(), self.uti)
        self.assertEqual(cell(row, 'reference_display'), '101')
        self.assertIn(self.tol.name, cell(row, 'tolerance_display'))
        self.assertEqual(resp.json()['reference_cell_html'], cell(row, 'reference_display'))
        self.assertEqual(resp.json()['tolerance_cell_html'], cell(row, 'tolerance_display'))

    def test_dialog_errors_come_back_as_422(self):
        self._login('view_unittestinfo', 'change_unittestinfo')
        pct = qa_utils.create_tolerance(tol_type=models.PERCENT)
        resp = self.client.post(self.dialog_url, {'reference_value': '', 'tolerance': pct.pk})
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'id="tl-reftol-form"', status_code=422)
        self.assertContains(resp, 'tl-assign-error', status_code=422)
        self.uti.refresh_from_db()
        self.assertIsNone(self.uti.tolerance)

    def test_new_tolerance_dialog_reachable(self):
        self._login('view_unittestinfo', 'change_unittestinfo', 'add_tolerance')
        dialog = self.client.get(self.dialog_url).content.decode()
        new_tol_url = reverse('admin:qa_testlist_new_tolerance') + '?uti=%d' % self.uti.pk
        self.assertIn('data-newtol-url="%s"' % new_tol_url, dialog)
        resp = self.client.get(new_tol_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="tl-newtol-form"')

    def test_dialog_refused_without_change_permission(self):
        self._login('view_unittestinfo')
        self.assertEqual(self.client.get(self.dialog_url).status_code, 403)


class TestChangeForm(TestCase):
    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.unit = qa_utils.create_unit(name='Linac 1')
        self.test = qa_utils.create_test(name='Output', test_type=models.SIMPLE)
        self.ref = qa_utils.create_reference(value=100)
        self.tol = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.test, ref=self.ref, tol=self.tol)
        self.url = reverse('admin:qa_unittestinfo_change', args=[self.uti.pk])

    def _post(self, **data):
        payload = {
            'test_type': self.test.get_type_display(),
            'reference_set_by': 'user',
            'reference_set': '',
            'reference_value': '',
            'tolerance': self.tol.pk,
            'comment': '',
            '_save': 'Save',
        }
        payload.update(data)
        return self.client.post(self.url, payload)

    def test_three_cards(self):
        html = self.client.get(self.url).content.decode()
        self.assertRegex(html, r'<h1 class="tl-header-title">\s*Set Reference & Tolerance')
        self.assertIn('Output on Linac 1', html)
        for card in ('qc-card-details', 'qc-card-reference-tolerance', 'qc-card-history'):
            self.assertIn('id="%s"' % card, html)
        self.assertLess(html.index('id="qc-card-details"'), html.index('id="qc-card-reference-tolerance"'))
        self.assertLess(html.index('id="qc-card-reference-tolerance"'), html.index('id="qc-card-history"'))

    def test_details_is_a_description_list_of_current_values(self):
        html = self.client.get(self.url).content.decode()
        details = html[html.index('id="qcr-details"') : html.index('</dl>', html.index('id="qcr-details"'))]
        for label in ('Unit', 'Test', 'Current Reference', 'Current Tolerance'):
            self.assertIn('<dt>%s</dt>' % label, details)
        self.assertIn('Linac 1', details)
        self.assertIn('<dd class="qcr-value">100</dd>', details)
        self.assertIn(self.tol.name, details)
        self.assertNotIn('<input', details)

    def test_reference_details_are_text_not_greyed_inputs(self):
        html = self.client.get(self.url).content.decode()
        meta = html[html.index('id="qcr-reference-details"') :]
        meta = meta[: meta.index('</dl>')]
        self.assertIn('<dt>Test Type</dt>', meta)
        self.assertIn('<dd>Simple Numerical</dd>', meta)
        self.assertIn('<dt>Reference Set By</dt>', meta)
        self.assertNotIn('readonly', html[html.index('id="qc-card-reference-tolerance"') :])
        # still posted as before, as hidden inputs
        self.assertIn('<input type="hidden" name="test_type" value="Simple Numerical"', html)
        for name in ('reference_value', 'tolerance', 'comment'):
            self.assertEqual(html.count('name="%s"' % name), 1, name)
        self.assertIn('Leave this blank to keep the current reference.', html)

    def test_non_numeric_reference_is_refused_not_a_server_error(self):
        for bad in ('abc', '1,5', 'nan', 'inf'):
            with self.subTest(reference=bad):
                resp = self._post(reference_value=bad)
                self.assertEqual(resp.status_code, 200)
                html = resp.content.decode()
                self.assertIn('Enter the reference as a number', html)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference, self.ref)

    def test_saving_a_new_reference_writes_history(self):
        resp = self._post(reference_value='105', comment='New output factor')
        self.assertEqual(resp.status_code, 302)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference.value, 105)
        change = models.UnitTestInfoChange.objects.get(unit_test_info=self.uti)
        self.assertEqual(change.reference, self.ref)
        self.assertTrue(change.reference_changed)
        self.assertEqual(change.comment, 'New output factor')

        html = self.client.get(self.url).content.decode()
        history = html[html.index('id="qc-card-history"') :]
        self.assertIn('<span class="tl-count-badge">1</span>', history)
        self.assertIn('id="change-history"', history)
        self.assertIn('New output factor', history)
        self.assertIn('class="uti-history-after"', history)
        self.assertLess(history.index('100'), history.index('105'))

    def test_blank_keeps_reference(self):
        resp = self._post(reference_value='')
        self.assertEqual(resp.status_code, 302)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference_id, self.ref.pk)

    def test_errors_render_inside_the_card(self):
        pct = qa_utils.create_tolerance(tol_type=models.PERCENT)
        resp = self._post(reference_value='0', tolerance=pct.pk)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        card = html[html.index('id="qc-card-reference-tolerance"') : html.index('id="qc-card-history"')]
        self.assertIn('qc-field field-reference_value qc-has-error', card)
        self.assertIn('Reference value cannot be zero when using a percent tolerance', card)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.tolerance, self.tol)

    def test_string_type_has_no_reference_input(self):
        test = qa_utils.create_test(name='Door', test_type=models.MULTIPLE_CHOICE, choices='open,closed')
        uti = qa_utils.create_unit_test_info(unit=self.unit, test=test)
        html = self.client.get(reverse('admin:qa_unittestinfo_change', args=[uti.pk])).content.decode()
        self.assertIn('<input type="hidden" name="reference_value"', html)
        self.assertIn('This test type doesn&#x27;t use a reference', html)
        details = html[html.index('id="qcr-details"') :]
        self.assertIn('Not used', details[: details.index('</dl>')])

    def test_missing_reference_highlighted_in_details(self):
        test = qa_utils.create_test(name='Interlock', test_type=models.BOOLEAN)
        uti = qa_utils.create_unit_test_info(unit=self.unit, test=test)
        html = self.client.get(reverse('admin:qa_unittestinfo_change', args=[uti.pk])).content.decode()
        details = html[html.index('id="qcr-details"') :]
        details = details[: details.index('</dl>')]
        self.assertIn('qcr-missing', details)
        self.assertIn('qcr-none', details)

    def test_view_only_user_gets_a_read_only_page(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        grant(viewer, 'view_unittestinfo')
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertRegex(html, r'<h1 class="tl-header-title">\s*View Reference & Tolerance')
        self.assertIn('<dd class="qcr-value">100</dd>', html)
        self.assertIn('<dd>Simple Numerical</dd>', html)
        self.assertIn('id="qc-card-history"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        for name in ('reference_value', 'tolerance', 'comment', 'test_type'):
            self.assertNotIn('name="%s"' % name, html)
        self.assertIn('>Back<', html)
        self.assertEqual(self._post(reference_value='1').status_code, 403)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference_id, self.ref.pk)


class TestCopyPage(TestCase):
    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.url = reverse('admin:qa_copy_refs_and_tols')
        self.tl = qa_utils.create_test_list(name='Daily')
        self.test = qa_utils.create_test(name='Output')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.test)
        self.u1 = qa_utils.create_unit(name='Linac 1')
        self.u2 = qa_utils.create_unit(name='Linac 2')
        qa_utils.create_unit_test_collection(unit=self.u1, test_collection=self.tl)
        qa_utils.create_unit_test_collection(unit=self.u2, test_collection=self.tl)
        self.src, _ = models.UnitTestInfo.objects.get_or_create(unit=self.u1, test=self.test)
        self.src.reference = qa_utils.create_reference(value=42)
        self.src.tolerance = qa_utils.create_tolerance()
        self.src.save()
        self.dest, _ = models.UnitTestInfo.objects.get_or_create(unit=self.u2, test=self.test)
        self.data = {
            'content_type': 'testlist',
            'source_testlist': self.tl.pk,
            'source_unit': self.u1.pk,
            'dest_unit': self.u2.pk,
        }

    def test_form_page(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'qa/copy_refs_tols.html')
        self.assertTemplateUsed(resp, 'admin/qa/unittestinfo/copy_refs_and_tols.html')
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('id="qc-card-copy"', html)
        self.assertIn('name="stage" value="1"', html)
        self.assertIn('name="source_unit"', html)
        # the admin's own page context: the header's user links and the nav sidebar
        self.assertIn('id="user-tools"', html)
        self.assertIn('id="nav-sidebar"', html)

    def test_preview_lists_the_changes(self):
        resp = self.client.post(self.url, dict(self.data, stage='1'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="qc-card-copy-changes"', html)
        table = html[html.index('id="qcr-copy-preview"') : html.index('</table>', html.index('id="qcr-copy-preview"'))]
        self.assertIn('Output', table)
        self.assertIn('42', table)
        self.assertIn(self.src.tolerance.name, table)
        self.assertIn('name="stage" value="2"', html)
        self.assertIn('<input type="hidden" name="confirm" value="Confirm">', html)
        self.assertIn('name="stage" value="0"', html)
        # Cancel is a link: it can't post the confirm form
        self.assertNotIn('name="cancel"', html)
        self.dest.refresh_from_db()
        self.assertIsNone(self.dest.reference)

    def test_change_selection_goes_back_without_copying(self):
        resp = self.client.post(self.url, dict(self.data, stage='0', confirm='Confirm'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="qc-card-copy"', html)
        self.assertRegex(html, r'<option value="%d" selected>' % self.u2.pk)
        self.dest.refresh_from_db()
        self.assertIsNone(self.dest.reference)

    def test_confirm_copies(self):
        resp = self.client.post(self.url, dict(self.data, stage='2', confirm='Confirm'))
        self.assertEqual(resp.status_code, 302)
        self.dest.refresh_from_db()
        self.assertEqual(self.dest.reference, self.src.reference)
        self.assertEqual(self.dest.tolerance, self.src.tolerance)

    def test_errors_render_inside_the_card(self):
        resp = self.client.post(self.url, dict(self.data, dest_unit=self.u1.pk, stage='1'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('qc-field field-dest_unit qc-has-error', html)


class TestSetMultiplePage(TestCase):
    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.admin = qa_admin.UnitTestInfoAdmin(models.UnitTestInfo, AdminSite())
        self.uti = qa_utils.create_unit_test_info(ref=qa_utils.create_reference(value=7))

    def test_page_renders_the_fields_and_selected_tests(self):
        request = RequestFactory().post('/', {'action': 'set_multiple_references_and_tolerances'})
        request.user = self.user
        resp = self.admin.set_multiple_references_and_tolerances(
            request,
            models.UnitTestInfo.objects.filter(pk=self.uti.pk),
        )
        html = resp.render().content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('id="qc-card-set-multiple"', html)
        self.assertIn('name="tolerance"', html)
        self.assertIn('name="reference"', html)
        self.assertIn('<input type="hidden" name="_selected_action" value="%d">' % self.uti.pk, html)
        self.assertIn('name="action" value="set_multiple_references_and_tolerances"', html)
        self.assertIn('name="post" value="yes"', html)
        table = html[html.index('id="qcr-set-multiple-tests"') :]
        self.assertIn(self.uti.test.name, table)
        self.assertIn('>7<', table)


class TestSetMultipleAction(TestCase):
    """The Set References & Tolerances list action, through the list page itself."""

    ACTION = 'set_multiple_references_and_tolerances'

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.url = reverse('admin:qa_unittestinfo_changelist')
        self.unit = qa_utils.create_unit(name='Linac 3')
        self.old_tol = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.new_tol = qa_utils.create_tolerance(act_low=-5, tol_low=-4, tol_high=4, act_high=5)
        self.percent = qa_utils.create_tolerance(tol_type=models.PERCENT)
        self.ref = qa_utils.create_reference(value=10)
        self.a = qa_utils.create_unit_test_info(
            unit=self.unit, test=qa_utils.create_test(name='Output A'), ref=self.ref, tol=self.old_tol,
        )
        self.b = qa_utils.create_unit_test_info(
            unit=self.unit, test=qa_utils.create_test(name='Output B'), ref=self.ref, tol=self.old_tol,
        )

    def post(self, utis, **data):
        payload = {'action': self.ACTION, '_selected_action': [u.pk for u in utis], 'post': 'yes'}
        payload.update(data)
        return self.client.post(self.url, payload)

    def refresh(self):
        self.a.refresh_from_db()
        self.b.refresh_from_db()

    def test_offered_in_the_list_to_users_who_can_change(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="%s"' % self.ACTION, html)

    def test_not_offered_to_view_only_users(self):
        viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename='view_unittestinfo'))
        self.client.logout()
        self.client.login(username='viewer', password='pwd')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('value="%s"' % self.ACTION, html)

    def test_first_post_shows_the_page(self):
        resp = self.client.post(self.url, {'action': self.ACTION, '_selected_action': [self.a.pk, self.b.pk]})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="qc-card-set-multiple"', html)
        self.assertIn('Output A', html)
        self.assertIn('Output B', html)
        # numerical tests: no Boolean or multiple choice tolerances on offer
        self.assertIn('<option value="%d"' % self.percent.pk, html)
        self.assertIn("Keep each test&#x27;s current tolerance", html)

    def test_sets_both_and_records_history_with_the_comment(self):
        resp = self.post([self.a, self.b], tolerance=self.new_tol.pk, reference='12.5', comment='New chamber')
        self.assertEqual(resp.status_code, 302)
        self.refresh()
        for uti in (self.a, self.b):
            self.assertEqual(uti.tolerance, self.new_tol)
            self.assertEqual(uti.reference.value, 12.5)
            change = models.UnitTestInfoChange.objects.get(unit_test_info=uti)
            self.assertEqual(change.comment, 'New chamber')
            self.assertEqual(change.changed_by, self.user)
            self.assertEqual(change.reference, self.ref)
            self.assertEqual(change.tolerance, self.old_tol)
            self.assertTrue(change.reference_changed)
            self.assertTrue(change.tolerance_changed)
        messages = [str(m) for m in resp.wsgi_request._messages]
        self.assertIn('Set the reference and tolerance for 2 tests.', messages)

    def test_blank_reference_keeps_each_tests_own(self):
        other_ref = qa_utils.create_reference(value=20)
        self.b.reference = other_ref
        self.b.save()
        self.post([self.a, self.b], tolerance=self.new_tol.pk, reference='')
        self.refresh()
        self.assertEqual(self.a.reference, self.ref)
        self.assertEqual(self.b.reference, other_ref)
        self.assertEqual(self.a.tolerance, self.new_tol)
        change = models.UnitTestInfoChange.objects.get(unit_test_info=self.a)
        self.assertFalse(change.reference_changed)
        self.assertTrue(change.tolerance_changed)

    def test_kept_tolerance_stays(self):
        self.post([self.a, self.b], tolerance='', reference='11')
        self.refresh()
        self.assertEqual(self.a.tolerance, self.old_tol)
        self.assertEqual(self.a.reference.value, 11)
        change = models.UnitTestInfoChange.objects.get(unit_test_info=self.a)
        self.assertFalse(change.tolerance_changed)

    def test_no_tolerance_clears_it(self):
        self.post([self.a, self.b], tolerance='none')
        self.refresh()
        self.assertIsNone(self.a.tolerance)
        self.assertIsNone(self.b.tolerance)
        self.assertEqual(self.a.reference, self.ref)

    def test_nothing_chosen_changes_nothing(self):
        resp = self.post([self.a, self.b], tolerance='', reference='', comment='just a note')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('leaving both as they are would change nothing', resp.content.decode())
        self.assertFalse(models.UnitTestInfoChange.objects.exists())

    def test_one_bad_test_saves_nothing(self):
        # a percent tolerance needs a non-zero reference: B has none, so A mustn't change either
        self.b.reference = None
        self.b.save()
        resp = self.post([self.a, self.b], tolerance=self.percent.pk, reference='')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Nothing was saved: 1 test can't take these values", html)
        self.assertIn('class="qcr-row-error qcr-row-error-msg"', html)
        self.assertIn('A reference value is required when using a percent tolerance', html)
        # the table still shows the saved tolerance, not the refused one
        self.assertEqual({row['uti'].tolerance for row in resp.context['rows']}, {self.old_tol})
        self.refresh()
        self.assertEqual(self.a.tolerance, self.old_tol)
        self.assertEqual(self.b.tolerance, self.old_tol)
        self.assertFalse(models.UnitTestInfoChange.objects.exists())

    def test_non_numeric_reference_is_refused_not_a_server_error(self):
        for bad in ('abc', '1,5', 'nan', 'inf', '-Infinity'):
            with self.subTest(reference=bad):
                resp = self.post([self.a, self.b], tolerance=self.new_tol.pk, reference=bad)
                self.assertEqual(resp.status_code, 200)
                self.assertIn('Enter the reference as a number', resp.content.decode())
        self.refresh()
        self.assertEqual(self.a.reference, self.ref)
        self.assertEqual(self.a.tolerance, self.old_tol)
        self.assertFalse(models.UnitTestInfoChange.objects.exists())

    def test_bad_reference_with_kept_tolerance_gets_one_message(self):
        resp = self.post([self.a, self.b], tolerance='', reference='abc')
        html = resp.content.decode()
        self.assertIn('Enter the reference as a number', html)
        # not also "you left both blank": the reference was typed, just not a number
        self.assertNotIn('leaving both as they are would change nothing', html)
        self.assertIn('Please correct the errors below. Nothing has been saved.', html)

    def test_mixed_kinds_are_refused(self):
        boolean = qa_utils.create_unit_test_info(
            unit=self.unit, test=qa_utils.create_test(name='Door', test_type=models.BOOLEAN),
        )
        resp = self.post([self.a, boolean], tolerance=self.new_tol.pk, reference='1')
        self.assertEqual(resp.status_code, 302)
        messages = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(any('Choose tests of one kind' in m for m in messages))
        self.refresh()
        self.assertEqual(self.a.tolerance, self.old_tol)

    def test_upload_tests_are_refused(self):
        upload = qa_utils.create_unit_test_info(
            unit=self.unit, test=qa_utils.create_test(name='Image', test_type=models.UPLOAD),
        )
        resp = self.client.post(self.url, {'action': self.ACTION, '_selected_action': [upload.pk]})
        self.assertEqual(resp.status_code, 302)
        messages = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(any("don't use references or tolerances" in m for m in messages))

    def test_wraparound_only_offers_absolute_tolerances(self):
        wrap = qa_utils.create_unit_test_info(
            unit=self.unit,
            test=qa_utils.create_test(name='Gantry', test_type=models.WRAPAROUND, wrap_low=0, wrap_high=360),
        )
        resp = self.client.post(self.url, {'action': self.ACTION, '_selected_action': [self.a.pk, wrap.pk]})
        html = resp.content.decode()
        self.assertIn('<option value="%d"' % self.new_tol.pk, html)
        self.assertNotIn('<option value="%d"' % self.percent.pk, html)

    def test_string_tests_have_no_reference_and_take_choices(self):
        mc = qa_utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='a,b', mc_tol_choices='c')
        utis = [
            qa_utils.create_unit_test_info(
                unit=self.unit, test=qa_utils.create_test(name=name, test_type=models.MULTIPLE_CHOICE, choices='a,b,c'),
            )
            for name in ('Choice 1', 'Choice 2')
        ]
        resp = self.client.post(self.url, {'action': self.ACTION, '_selected_action': [u.pk for u in utis]})
        html = resp.content.decode()
        self.assertNotIn('name="reference"', html)
        self.assertIn('<option value="%d"' % mc.pk, html)
        # nothing chosen: no mention of a reference they can't enter
        html = self.post(utis, tolerance='').content.decode()
        self.assertIn('Choose a tolerance: leaving it as it is would change nothing.', html)
        self.assertNotIn('or enter a reference', html)
        self.assertNotIn('<option value="%d"' % self.new_tol.pk, html)
        self.post(utis, tolerance=mc.pk)
        for uti in utis:
            uti.refresh_from_db()
            self.assertEqual(uti.tolerance, mc)
            self.assertIsNone(uti.reference)

    def test_boolean_tests_take_yes_or_no(self):
        bool_tol = models.Tolerance.objects.filter(type=models.BOOLEAN).first()
        utis = [
            qa_utils.create_unit_test_info(
                unit=self.unit, test=qa_utils.create_test(name=name, test_type=models.BOOLEAN),
            )
            for name in ('Door 1', 'Door 2')
        ]
        resp = self.post(utis, tolerance=bool_tol.pk if bool_tol else '', reference='1', comment='Interlocks')
        self.assertEqual(resp.status_code, 302)
        for uti in utis:
            uti.refresh_from_db()
            self.assertEqual(uti.reference.type, models.BOOLEAN)
            self.assertEqual(str(uti.reference), 'Yes')
