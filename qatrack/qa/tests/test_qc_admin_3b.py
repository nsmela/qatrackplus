"""Assign Test Lists to Units (UnitTestCollection) admin: the restyled pages and their features.

Covers the change form's cards (What / Where & When / Who), the htmx test list
picker and contents preview endpoints, the read-only unit and test list of a saved
assignment, validation errors, view-only users and the list page's tags and
list_editable Active column.
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils


class UTCAdminTestCase(TestCase):
    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)

        self.site = qa_utils.create_site(name='Main Site')
        self.u_1 = qa_utils.create_unit(name='Linac One', site=self.site)
        self.u_2 = qa_utils.create_unit(name='Linac Two')
        self.f_1 = qa_utils.create_frequency(name='Daily', slug='daily')
        self.f_2 = qa_utils.create_frequency(name='Monthly', slug='monthly')
        self.g_1 = Group.objects.create(name='Physics')
        self.g_2 = Group.objects.create(name='Therapists')

        self.tl_1 = qa_utils.create_test_list(name='Morning Output')
        self.t_1 = qa_utils.create_test(name='Output 6MV', test_type=models.SIMPLE)
        self.t_2 = qa_utils.create_test(name='Door interlock', test_type=models.BOOLEAN)
        qa_utils.create_test_list_membership(test_list=self.tl_1, test=self.t_1, order=0)
        qa_utils.create_test_list_membership(test_list=self.tl_1, test=self.t_2, order=1)
        self.tl_2 = qa_utils.create_test_list(name='Monthly Mechanical')
        self.cycle = qa_utils.create_cycle(test_lists=[self.tl_1, self.tl_2], name='Weekly Cycle')

        self.tl_ct = ContentType.objects.get_for_model(models.TestList)
        self.cycle_ct = ContentType.objects.get_for_model(models.TestListCycle)

        self.utc = qa_utils.create_unit_test_collection(
            unit=self.u_1,
            frequency=self.f_1,
            test_collection=self.tl_1,
            assigned_to=self.g_1,
        )

        self.url_add = reverse('admin:qa_unittestcollection_add')
        self.url_list = reverse('admin:qa_unittestcollection_changelist')
        self.url_change = reverse('admin:qa_unittestcollection_change', args=(self.utc.pk,))
        self.url_search = reverse('admin:qa_unittestcollection_search')
        self.url_preview = reverse('admin:qa_unittestcollection_preview')

    def post_data(self, **kwargs):
        data = {
            'content_type': self.tl_ct.pk,
            'object_id': self.tl_2.pk,
            'unit': self.u_2.pk,
            'frequency': self.f_2.pk,
            'due_date_0': '',
            'due_date_1': '',
            'auto_schedule': 'on',
            'active': 'on',
            'assigned_to': self.g_2.pk,
            'visible_to': [self.g_1.pk, self.g_2.pk],
            '_save': 'Save',
        }
        data.update(kwargs)
        return {k: v for k, v in data.items() if v is not None}

    def saved_data(self, **kwargs):
        """POST data for the saved assignment, unchanged unless overridden."""
        return self.post_data(
            **{
                'content_type': self.tl_ct.pk,
                'object_id': self.tl_1.pk,
                'unit': self.u_1.pk,
                'frequency': self.f_1.pk,
                'assigned_to': self.g_1.pk,
                **kwargs,
            }
        )

    def login_as(self, *codenames, uname='limited'):
        user = create_user(uname=uname, pwd='pwd', is_staff=True, is_superuser=False)
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(user)
        return user


class TestAddPage(UTCAdminTestCase):
    def test_add_page_draws_the_three_cards_and_preview(self):
        resp = self.client.get(self.url_add)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="utc-what-card"', html)
        self.assertIn('id="qc-card-where-when"', html)
        self.assertIn('id="qc-card-who"', html)
        self.assertIn('id="utc-preview-card"', html)
        self.assertIn('Choose a test list or cycle to see what it contains.', html)
        # the page's own template, not the old treenav one
        self.assertNotIn('updatecombo', html)
        self.assertNotIn('select2.min.js', html)
        self.assertIn('utc_assets', [t.name.split('/')[-1].replace('.html', '') for t in resp.templates])

    def test_picker_keeps_the_real_fields(self):
        html = self.client.get(self.url_add).content.decode()
        # content type as Test List / Test List Cycle radios
        self.assertEqual(html.count('name="content_type"'), 2)
        self.assertIn('type="radio"', html)
        self.assertIn('Test List Cycle', html)
        # object_id stays a real input (works without JS)
        self.assertEqual(html.count('name="object_id"'), 1)
        self.assertIn('class="utc-object-raw"', html)
        # the htmx search box, outside the change form
        self.assertIn('hx-get="%s"' % self.url_search, html)
        self.assertIn('form="utc-search-no-form"', html)
        self.assertIn('data-preview-url="%s"' % self.url_preview, html)

    def test_add_assignment_for_a_test_list(self):
        before = models.UnitTestCollection.objects.count()
        resp = self.client.post(self.url_add, self.post_data())
        self.assertEqual(resp.status_code, 302, resp.context and resp.context['adminform'].form.errors)
        self.assertEqual(models.UnitTestCollection.objects.count(), before + 1)
        utc = models.UnitTestCollection.objects.latest('pk')
        self.assertEqual(utc.tests_object, self.tl_2)
        self.assertEqual(utc.unit, self.u_2)
        self.assertEqual(utc.frequency, self.f_2)
        self.assertEqual(utc.assigned_to, self.g_2)
        self.assertEqual(set(utc.visible_to.all()), {self.g_1, self.g_2})
        self.assertTrue(utc.active)
        self.assertEqual(utc.name, self.tl_2.name)

    def test_add_assignment_for_a_cycle(self):
        resp = self.client.post(self.url_add, self.post_data(content_type=self.cycle_ct.pk, object_id=self.cycle.pk))
        self.assertEqual(resp.status_code, 302)
        utc = models.UnitTestCollection.objects.latest('pk')
        self.assertEqual(utc.tests_object, self.cycle)
        self.assertEqual(utc.content_type, self.cycle_ct)

    def test_ad_hoc_assignment(self):
        resp = self.client.post(self.url_add, self.post_data(frequency=''))
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(models.UnitTestCollection.objects.latest('pk').frequency)

    def test_required_errors_render_inside_the_cards(self):
        resp = self.client.post(self.url_add, self.post_data(content_type='', object_id='', unit=''))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('field-content_type qc-has-error', html)
        self.assertIn('field-object_id qc-has-error', html)
        self.assertIn('field-unit qc-has-error', html)

    def test_unique_unit_frequency_object_error(self):
        before = models.UnitTestCollection.objects.count()
        resp = self.client.post(self.url_add, self.saved_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(models.UnitTestCollection.objects.count(), before)
        self.assertIn(
            'This test list or cycle is already assigned to this unit at this frequency.', resp.content.decode()
        )

    def test_invalid_post_keeps_the_chosen_item_and_preview(self):
        resp = self.client.post(self.url_add, self.post_data(object_id=self.tl_1.pk, unit=''))
        html = resp.content.decode()
        self.assertIn('data-utc-chosen-name>Morning Output<', html)
        # the preview shows the posted choice's tests
        self.assertIn('Output 6MV', html)
        self.assertIn('Door interlock', html)


class TestChangePage(UTCAdminTestCase):
    def test_unit_and_test_list_are_read_only(self):
        resp = self.client.get(self.url_change)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Edit Test List Assignment', html)
        self.assertIn('Morning Output &middot; Linac One &middot; Daily', html)
        # unit shown as text, the select tucked away for Save as New
        self.assertIn('class="qc-readonly utc-locked-value">Linac One<', html)
        self.assertIn('Choose another unit for Save as New', html)
        # the test list shown read-only, with the picker for Save as New in a <details>
        self.assertIn('<strong class="utc-chip-name">Morning Output</strong>', html)
        self.assertIn("can't be changed once an assignment is saved", html)
        self.assertIn('Choose a different test list or cycle for Save as New', html)
        self.assertIn('id="qc-saveas-btn"', html)

    def test_contents_preview_and_builder_link(self):
        html = self.client.get(self.url_change).content.decode()
        self.assertIn('id="utc-preview-card"', html)
        self.assertIn('Output 6MV', html)
        self.assertIn('Door interlock', html)
        self.assertIn('Boolean', html)
        self.assertIn('href="%s"' % reverse('admin:qa_testlist_change', args=(self.tl_1.pk,)), html)
        self.assertIn('Open in Test List Builder', html)

    def test_save_changes_other_fields(self):
        resp = self.client.post(
            self.url_change, self.saved_data(frequency=self.f_2.pk, active=None, assigned_to=self.g_2.pk)
        )
        self.assertEqual(resp.status_code, 302, resp.context and resp.context['adminform'].form.errors)
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.frequency, self.f_2)
        self.assertEqual(self.utc.assigned_to, self.g_2)
        self.assertFalse(self.utc.active)

    def test_changing_the_unit_is_refused_in_its_card(self):
        resp = self.client.post(self.url_change, self.saved_data(unit=self.u_2.pk))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('field-unit qc-has-error', html)
        self.assertIn('To prevent data loss', html)
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.unit, self.u_1)

    def test_changing_the_test_list_is_refused_in_its_card(self):
        resp = self.client.post(self.url_change, self.saved_data(object_id=self.tl_2.pk))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('qc-has-error', html)
        self.assertIn('To prevent data loss', html)
        # the Save as New picker is opened to show the error
        self.assertIn('class="utc-unlock utc-unlock-what" open', html)
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.tests_object, self.tl_1)

    def test_save_as_new_can_use_another_unit(self):
        before = models.UnitTestCollection.objects.count()
        data = self.saved_data(unit=self.u_2.pk, _saveasnew='Save as New')
        del data['_save']
        resp = self.client.post(self.url_change, data)
        self.assertEqual(resp.status_code, 302, resp.context and resp.context['adminform'].form.errors)
        self.assertEqual(models.UnitTestCollection.objects.count(), before + 1)
        copy = models.UnitTestCollection.objects.latest('pk')
        self.assertEqual(copy.unit, self.u_2)
        self.assertEqual(copy.tests_object, self.tl_1)
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.unit, self.u_1)

    def test_save_as_new_with_same_values_is_the_unique_error(self):
        data = self.saved_data(_saveasnew='Save as New')
        del data['_save']
        resp = self.client.post(self.url_change, data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('already assigned to this unit at this frequency', resp.content.decode())

    def test_change_frequency_to_an_existing_assignment_is_the_unique_error(self):
        qa_utils.create_unit_test_collection(unit=self.u_1, frequency=self.f_2, test_collection=self.tl_1)
        resp = self.client.post(self.url_change, self.saved_data(frequency=self.f_2.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('already assigned to this unit at this frequency', resp.content.decode())
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.frequency, self.f_1)

    def test_without_add_permission_the_locked_values_are_hidden_inputs(self):
        self.login_as('change_unittestcollection', 'view_unittestcollection')
        html = self.client.get(self.url_change).content.decode()
        self.assertNotIn('id="qc-saveas-btn"', html)
        self.assertNotIn('Choose another unit for Save as New', html)
        self.assertNotIn('<details class="utc-unlock', html)
        self.assertIn('<input type="hidden" name="unit" value="%d"' % self.u_1.pk, html)
        self.assertIn('<input type="hidden" name="content_type" value="%d"' % self.tl_ct.pk, html)
        self.assertIn('<input type="hidden" name="object_id" value="%d"' % self.tl_1.pk, html)
        # and saving still works
        resp = self.client.post(self.url_change, self.saved_data(frequency=self.f_2.pk))
        self.assertEqual(resp.status_code, 302)
        self.utc.refresh_from_db()
        self.assertEqual(self.utc.frequency, self.f_2)

    def test_cycle_assignment_preview_lists_its_days(self):
        utc = qa_utils.create_unit_test_collection(unit=self.u_2, test_collection=self.cycle)
        html = self.client.get(reverse('admin:qa_unittestcollection_change', args=(utc.pk,))).content.decode()
        self.assertIn('Weekly Cycle', html)
        self.assertIn('2 days', html)
        self.assertIn('Monthly Mechanical', html)
        self.assertIn('Open Test List Cycle', html)
        self.assertIn('href="%s"' % reverse('admin:qa_testlistcycle_change', args=(self.cycle.pk,)), html)

    def test_view_only_user_gets_a_read_only_page(self):
        self.login_as('view_unittestcollection')
        resp = self.client.get(self.url_change)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="qc-readonly"', html)
        self.assertIn('<strong class="utc-chip-name">Morning Output</strong>', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertNotIn('id="qc-delete-btn"', html)
        self.assertNotIn('name="content_type"', html)
        self.assertNotIn('name="object_id"', html)
        self.assertNotIn('id="utc-search-input"', html)
        self.assertIn('>Back<', html)
        # the preview is still shown; no builder link without test list permissions
        self.assertIn('Output 6MV', html)
        self.assertNotIn('Open in Test List Builder', html)


class TestPickerEndpoint(UTCAdminTestCase):
    def test_lists_test_lists(self):
        resp = self.client.get(self.url_search, {'content_type': self.tl_ct.pk, 'q': ''})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('data-object-id="%d"' % self.tl_1.pk, html)
        self.assertIn('data-object-name="Morning Output"', html)
        self.assertIn('2 tests', html)
        self.assertIn('data-object-id="%d"' % self.tl_2.pk, html)

    def test_filters_by_name(self):
        html = self.client.get(self.url_search, {'content_type': self.tl_ct.pk, 'q': 'mechan'}).content.decode()
        self.assertIn('Monthly Mechanical', html)
        self.assertNotIn('Morning Output', html)

    def test_lists_cycles(self):
        html = self.client.get(self.url_search, {'content_type': self.cycle_ct.pk}).content.decode()
        self.assertIn('data-object-id="%d"' % self.cycle.pk, html)
        self.assertIn('2 days', html)
        self.assertIn('data-is-cycle="1"', html)
        self.assertNotIn('Morning Output', html)

    def test_no_match(self):
        html = self.client.get(self.url_search, {'content_type': self.tl_ct.pk, 'q': 'zzz'}).content.decode()
        self.assertIn('No test lists found matching', html)

    def test_other_content_types_are_refused(self):
        other = ContentType.objects.get_for_model(models.Test)
        self.assertEqual(self.client.get(self.url_search, {'content_type': other.pk}).status_code, 400)
        self.assertEqual(self.client.get(self.url_search, {'content_type': 'x'}).status_code, 400)

    def test_needs_add_or_change_permission(self):
        self.login_as('view_unittestcollection')
        self.assertEqual(self.client.get(self.url_search, {'content_type': self.tl_ct.pk}).status_code, 403)
        self.login_as('add_unittestcollection', uname='adder')
        self.assertEqual(self.client.get(self.url_search, {'content_type': self.tl_ct.pk}).status_code, 200)

    def test_needs_staff(self):
        self.client.logout()
        resp = self.client.get(self.url_search, {'content_type': self.tl_ct.pk})
        self.assertEqual(resp.status_code, 302)  # admin login


class TestPreviewEndpoint(UTCAdminTestCase):
    def test_test_list_contents(self):
        resp = self.client.get(self.url_preview, {'content_type': self.tl_ct.pk, 'object_id': self.tl_1.pk})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="utc-preview-card"', html)
        self.assertIn('Output 6MV', html)
        self.assertIn('Door interlock', html)
        self.assertIn('2 tests', html)
        self.assertLess(html.index('Output 6MV'), html.index('Door interlock'))

    def test_sublists_are_included(self):
        child = qa_utils.create_test_list(name='Imaging Sublist')
        qa_utils.create_test_list_membership(test_list=child, test=qa_utils.create_test(name='kV Image'))
        qa_utils.create_sublist(parent_test_list=self.tl_2, child_test_list=child)
        html = self.client.get(
            self.url_preview, {'content_type': self.tl_ct.pk, 'object_id': self.tl_2.pk}
        ).content.decode()
        self.assertIn('kV Image', html)
        self.assertIn('Imaging Sublist', html)

    def test_cycle_contents(self):
        html = self.client.get(
            self.url_preview, {'content_type': self.cycle_ct.pk, 'object_id': self.cycle.pk}
        ).content.decode()
        self.assertIn('Morning Output', html)
        self.assertIn('Monthly Mechanical', html)
        self.assertIn('2 days', html)

    def test_nothing_chosen(self):
        for params in (
            {},
            {'content_type': self.tl_ct.pk, 'object_id': ''},
            {'content_type': self.tl_ct.pk, 'object_id': 99999},
        ):
            with self.subTest(params=params):
                resp = self.client.get(self.url_preview, params)
                self.assertEqual(resp.status_code, 200)
                self.assertIn('Choose a test list or cycle to see what it contains.', resp.content.decode())

    def test_needs_view_permission(self):
        self.login_as('view_testlist')
        params = {'content_type': self.tl_ct.pk, 'object_id': self.tl_1.pk}
        self.assertEqual(self.client.get(self.url_preview, params).status_code, 403)
        self.login_as('view_unittestcollection', uname='viewer')
        self.assertEqual(self.client.get(self.url_preview, params).status_code, 200)


class TestChangeList(UTCAdminTestCase):
    def test_frequency_and_assigned_to_are_tags(self):
        qa_utils.create_unit_test_collection(unit=self.u_2, test_collection=self.tl_2, null_frequency=True)
        resp = self.client.get(self.url_list)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<span class="utc-tag">Daily</span>', html)
        self.assertIn('<span class="utc-tag utc-tag-adhoc">Ad Hoc</span>', html)
        self.assertIn('utc-tag utc-tag-group', html)
        self.assertIn('Physics', html)
        self.assertIn('#result_list .utc-tag', html)
        self.assertIn('class="tl-index-header qc-index-header"', html)

    def test_unassigned_shows_not_assigned(self):
        group = Group.objects.create(name='Doomed')
        qa_utils.create_unit_test_collection(unit=self.u_2, test_collection=self.tl_2, assigned_to=group)
        group.delete()
        html = self.client.get(self.url_list).content.decode()
        self.assertIn('<span class="utc-tag-none">Not assigned</span>', html)

    def test_columns_keep_their_ordering(self):
        cols = qa_admin.UnitTestCollectionAdmin.list_display
        for col in (qa_admin.freq_name, qa_admin.assigned_to_name):
            idx = cols.index(col)
            for order in (str(idx), '-%d' % idx):
                with self.subTest(col=col.__name__, order=order):
                    self.assertEqual(self.client.get(self.url_list, {'o': order}).status_code, 200)

    def test_active_is_editable_in_the_list(self):
        html = self.client.get(self.url_list).content.decode()
        self.assertIn('name="form-0-active"', html)
        data = {
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(self.utc.pk),
            '_save': 'Save',
        }
        resp = self.client.post(self.url_list, data)
        self.assertEqual(resp.status_code, 302)
        self.utc.refresh_from_db()
        self.assertFalse(self.utc.active)

    def test_filters_still_work(self):
        other = qa_utils.create_unit_test_collection(
            unit=self.u_2,
            test_collection=self.tl_2,
            null_frequency=True,
            assigned_to=self.g_2,
            active=False,
        )
        cases = {
            'sitefilter': (self.site.pk, self.utc),
            'unitfilter': (self.u_2.pk, other),
            'freqfilter': ('adhoc', other),
            'assignedtoname': (self.g_1.pk, self.utc),
            'activefilter': (0, other),
        }
        for param, (value, expected) in cases.items():
            with self.subTest(param=param):
                resp = self.client.get(self.url_list, {param: value})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(list(resp.context['cl'].result_list), [expected])

    def test_search(self):
        resp = self.client.get(self.url_list, {'q': 'Morning'})
        self.assertEqual(list(resp.context['cl'].result_list), [self.utc])


class TestAssignMachineDialogUnaffected(TestCase):
    def test_dialog_form_is_not_the_admin_form(self):
        # The Test List builder's dialog keeps UnitTestCollectionForm's own widgets.
        self.assertFalse(issubclass(qa_admin.TestListAssignMachineForm, qa_admin.UnitTestCollectionAdminForm))
        form = qa_admin.TestListAssignMachineForm()
        self.assertNotIsInstance(form.fields['content_type'].widget, qa_admin.forms.RadioSelect)
