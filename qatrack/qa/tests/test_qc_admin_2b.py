"""QC admin step 2B: the Frequency, Category and Auto Save admin pages.

Frequencies: Details / Due Window / Schedule cards, the Preview card (calendars and the
"Next due dates" list, refreshed over htmx) and the Used In card. Categories: the shared
change form, the tree and grid lists' title row and the Used In card. Auto Saves: the
list's Recover button and the change page's summary card.
"""

import re
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils


def _login_viewer(client, *codenames):
    viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
    for codename in codenames:
        viewer.user_permissions.add(Permission.objects.get(codename=codename))
    client.logout()
    client.login(username='viewer', password='pwd')
    return viewer


class TestFrequencyChangeForm(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.freq = qa_utils.create_frequency(name="Daily", slug="daily", window_end=0)
        self.url = reverse('admin:qa_frequency_change', args=(self.freq.pk,))

    def test_cards_in_order(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        ids = ['id="qc-card-details"', 'id="qc-card-due-window"', 'id="qc-card-schedule"',
               'id="qcf-preview-card"', 'id="qcf-used-card"']
        positions = [html.index(i) for i in ids]
        self.assertEqual(positions, sorted(positions))
        details = html[positions[0]:positions[1]]
        self.assertIn('name="name"', details)
        self.assertIn('name="slug"', details)
        window = html[positions[1]:positions[2]]
        self.assertIn('name="window_start"', window)
        self.assertIn('name="window_end"', window)
        # One save button group, Django's bottom row isn't drawn
        self.assertIn('id="qc-save-btn"', html)
        self.assertNotIn('class="submit-row"', html)

    def test_schedule_card_has_full_width_recurrence_widget(self):
        html = self.client.get(self.url).content.decode()
        self.assertRegex(html, r'class="tlb-field qc-field field-recurrences tl-col-full')
        self.assertIn('class="recurrence-widget"', html)
        self.assertEqual(html.count('name="recurrences"'), 1)
        # django-recurrence's own widget JS still comes through Media
        self.assertIn('recurrence/js/recurrence-widget.js', html)
        self.assertIn('recurrence/js/recurrence-widget.init.js', html)

    def test_preview_card_keeps_what_frequency_admin_js_needs(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('js/frequency_admin.js', html)
        self.assertIn('cal-heatmap/js/cal-heatmap.min.js', html)
        self.assertIn('<div id="cal-1"></div>', html)
        self.assertIn('<div id="cal-2"></div>', html)
        self.assertIn('classic-freq', html)
        self.assertIn('window.recurrenceUrl = "%s"' % reverse('qa_recurrences'), html)
        self.assertIn('id="id_window_start"', html)
        self.assertIn('id="id_window_end"', html)

    def test_next_due_dates_drawn_with_the_page(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="qcf-next-due"', html)
        self.assertIn('hx-post="%s"' % reverse('admin:qa_frequency_next_due'), html)
        self.assertIn('hx-trigger="qcf-schedule-changed delay:400ms"', html)
        self.assertIn('hx-include="#id_recurrences, #id_window_start, #id_window_end"', html)
        self.assertIn('"X-CSRFToken"', html)
        self.assertIn('htmx/js/htmx.min.js', html)
        self.assertEqual(html.count('class="qcf-due-item"'), qa_admin.FREQUENCY_NEXT_DUE_COUNT)
        # A blank window start is a classic frequency: no window start, only an end
        self.assertIn('Overdue after', html)

    def test_add_page_has_no_used_in_and_asks_for_a_rule(self):
        resp = self.client.get(reverse('admin:qa_frequency_add'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Add Frequency', html)
        self.assertIn('id="qcf-preview-card"', html)
        self.assertNotIn('id="qcf-used-card"', html)
        self.assertIn('Add a rule or a date to the schedule', html)
        self.assertNotIn('id="qc-history-btn"', html)

    def test_save_still_saves(self):
        data = {
            'name': 'Weekly',
            'slug': 'weekly',
            'window_start': '1',
            'window_end': '2',
            'recurrences': 'RRULE:FREQ=WEEKLY;BYDAY=MO',
            '_save': 'Save',
        }
        resp = self.client.post(reverse('admin:qa_frequency_add'), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context['adminform'].form.errors)
        freq = models.Frequency.objects.get(slug='weekly')
        self.assertEqual(freq.window_start, 1)
        self.assertEqual(freq.window_end, 2)
        # FrequencyForm/Frequency.save still work out the interval (a week, give or take DST)
        self.assertIn(freq.nominal_interval, (6, 7))
        self.assertIn('FREQ=WEEKLY', str(freq.recurrences))

    def test_change_and_continue_still_saves(self):
        data = {
            'name': 'Daily (renamed)',
            'slug': 'daily',
            'window_start': '',
            'window_end': '1',
            'recurrences': str(self.freq.recurrences),
            '_continue': 'Save and Continue Editing',
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        self.freq.refresh_from_db()
        self.assertEqual(self.freq.name, 'Daily (renamed)')
        self.assertEqual(self.freq.window_end, 1)
        self.assertIsNone(self.freq.window_start)

    def test_schedule_errors_render_inside_the_card(self):
        data = {
            'name': 'Excluded', 'slug': 'excluded', 'window_start': '', 'window_end': '0',
            'recurrences': 'EXRULE:FREQ=WEEKLY;BYDAY=MO', '_save': 'Save',
        }
        resp = self.client.post(reverse('admin:qa_frequency_add'), data)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        schedule = html[html.index('id="qc-card-schedule"'):html.index('id="qcf-preview-card"')]
        self.assertIn('qc-has-error', schedule)
        self.assertIn('exclusion rules only', schedule)
        # The preview reads the posted schedule, not the saved one
        self.assertIn('This schedule only excludes dates.', html)
        self.assertFalse(models.Frequency.objects.filter(slug='excluded').exists())

    def test_required_field_errors_render_inside_the_card(self):
        resp = self.client.post(reverse('admin:qa_frequency_add'), {'name': '', 'slug': '', 'window_end': '', '_save': 'Save'})
        html = resp.content.decode()
        details = html[html.index('id="qc-card-details"'):html.index('id="qc-card-due-window"')]
        self.assertIn('qc-has-error', details)
        self.assertIn('class="errorlist', details)

    def test_view_only_user_gets_read_only_page_with_preview(self):
        _login_viewer(self.client, 'view_frequency')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Frequency', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertNotIn('name="recurrences"', html)
        # The calendars still get the saved schedule, from inputs that aren't submitted
        self.assertIn('<textarea id="id_recurrences" hidden aria-hidden="true">', html)
        self.assertIn('id="cal-1"', html)
        # The list is drawn once with the page; there's nothing to refresh
        self.assertIn('class="qcf-due-item"', html)
        self.assertNotIn('hx-post=', html)


class TestFrequencyNextDueDates(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.url = reverse('admin:qa_frequency_next_due')

    def test_weekly_with_window(self):
        tz = timezone.get_current_timezone()
        now = timezone.datetime(2026, 11, 19, 10, 0, tzinfo=tz)  # a Thursday
        result = qa_admin.frequency_next_due_dates(
            {'recurrences': 'RRULE:FREQ=WEEKLY;BYDAY=MO', 'window_start': '2', 'window_end': '1'}, now=now,
        )
        self.assertFalse(result['is_error'])
        self.assertFalse(result['classic'])
        dates = result['dates']
        self.assertEqual(len(dates), 8)
        self.assertEqual(timezone.localtime(dates[0]['due']).date(), timezone.datetime(2026, 11, 23).date())
        for d in dates:
            due = timezone.localtime(d['due'])
            self.assertEqual(due.weekday(), 0)
            self.assertEqual((due.date() - timezone.localtime(d['window_start']).date()).days, 2)
            self.assertEqual((timezone.localtime(d['window_end']).date() - due.date()).days, 1)
        gaps = {(b['due'] - a['due']).days for a, b in zip(dates, dates[1:])}
        self.assertEqual(gaps, {7})

    def test_classic_monthly(self):
        tz = timezone.get_current_timezone()
        now = timezone.datetime(2026, 11, 19, 10, 0, tzinfo=tz)
        result = qa_admin.frequency_next_due_dates(
            {'recurrences': 'RRULE:FREQ=MONTHLY;BYMONTHDAY=1', 'window_start': '', 'window_end': '3'}, now=now,
        )
        self.assertTrue(result['classic'])
        first = timezone.localtime(result['dates'][0]['due']).date()
        self.assertEqual(first, timezone.datetime(2026, 12, 1).date())
        self.assertIsNone(result['dates'][0]['window_start'])

    def test_problem_messages(self):
        cases = [
            ({'recurrences': ''}, False, 'Add a rule or a date'),
            ({'recurrences': 'EXDATE:20250101T050000Z'}, True, 'only excludes dates'),
            ({'recurrences': 'RRULE:FREQ=NOTAFREQ'}, True, "can't be read yet"),
            ({'recurrences': 'RDATE:20200101T050000Z'}, True, 'no due dates after today'),
            ({'recurrences': 'RRULE:FREQ=DAILY', 'window_start': '-1'}, True, 'whole numbers of days'),
        ]
        for data, is_error, message in cases:
            with self.subTest(data=data):
                result = qa_admin.frequency_next_due_dates(data)
                self.assertEqual(result['dates'], [])
                self.assertEqual(result['is_error'], is_error)
                self.assertIn(message, result['message'])

    def test_endpoint_returns_the_list(self):
        resp = self.client.post(self.url, {
            'recurrences': 'RRULE:FREQ=WEEKLY;BYDAY=MO', 'window_start': '1', 'window_end': '1',
        })
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(html.count('class="qcf-due-item"'), 8)
        self.assertIn('QC window', html)
        self.assertNotIn('<html', html)

    def test_endpoint_invalid_schedule_is_422_with_message(self):
        resp = self.client.post(self.url, {'recurrences': 'EXDATE:20250101T050000Z', 'window_end': '0'})
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'qcf-due-problem', status_code=422)
        self.assertContains(resp, 'only excludes dates', status_code=422)

    def test_endpoint_empty_schedule_is_a_friendly_note(self):
        resp = self.client.post(self.url, {'recurrences': '', 'window_end': '0'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add a rule or a date')
        self.assertNotContains(resp, 'qcf-due-problem')

    def test_endpoint_is_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_endpoint_needs_add_or_change_permission(self):
        _login_viewer(self.client, 'view_frequency')
        resp = self.client.post(self.url, {'recurrences': 'RRULE:FREQ=DAILY', 'window_end': '0'})
        self.assertEqual(resp.status_code, 403)
        _login_viewer(self.client, 'change_frequency')
        resp = self.client.post(self.url, {'recurrences': 'RRULE:FREQ=DAILY', 'window_end': '0'})
        self.assertEqual(resp.status_code, 200)

    def test_endpoint_is_staff_only(self):
        self.client.logout()
        resp = self.client.post(self.url, {'recurrences': 'RRULE:FREQ=DAILY'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])


class TestFrequencyUsedIn(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.freq = qa_utils.create_frequency(name="Weekly", slug="weekly")
        self.unit = qa_utils.create_unit(name="Linac 1")
        self.tl = qa_utils.create_test_list(name="Weekly Output")
        self.utc = qa_utils.create_unit_test_collection(unit=self.unit, frequency=self.freq, test_collection=self.tl)
        self.cycle = qa_utils.create_cycle(test_lists=[qa_utils.create_test_list(name="Cycle day")], name="Monthly Cycle")
        self.utc_cycle = qa_utils.create_unit_test_collection(
            unit=self.unit, frequency=self.freq, test_collection=self.cycle, active=False,
        )
        # Not this frequency: not listed
        qa_utils.create_unit_test_collection(unit=self.unit, test_collection=qa_utils.create_test_list(name="Other"))
        self.url = reverse('admin:qa_frequency_change', args=(self.freq.pk,))

    def _used_card(self):
        html = self.client.get(self.url).content.decode()
        start = html.index('id="qcf-used-card"')
        return html[start:html.index('</form>', start)]

    def test_lists_assignments_with_links(self):
        card = self._used_card()
        self.assertIn('<span class="tl-count-badge">2</span>', card)
        self.assertIn(reverse('admin:qa_unittestcollection_change', args=(self.utc.pk,)), card)
        self.assertIn(reverse('admin:qa_unittestcollection_change', args=(self.utc_cycle.pk,)), card)
        self.assertIn('Linac 1', card)
        self.assertIn('Weekly Output', card)
        self.assertIn('Monthly Cycle', card)
        self.assertIn('Test list cycle', card)
        self.assertEqual(card.count('qcf-tag-inactive'), 1)
        self.assertNotIn('>Other<', card)
        self.assertIn('%s?freqfilter=%d' % (reverse('admin:qa_unittestcollection_changelist'), self.freq.pk), card)

    def test_list_is_capped(self):
        with mock.patch.object(qa_admin, 'FREQUENCY_USED_IN_LIMIT', 1):
            card = self._used_card()
        self.assertEqual(card.count('class="qcf-used-item"'), 1)
        self.assertIn('<span class="tl-count-badge">2</span>', card)
        self.assertIn('And 1 more assignment.', card)

    def test_names_without_links_for_users_who_cant_open_assignments(self):
        _login_viewer(self.client, 'change_frequency')
        card = self._used_card()
        self.assertIn('Weekly Output', card)
        self.assertNotIn(reverse('admin:qa_unittestcollection_change', args=(self.utc.pk,)), card)
        self.assertNotIn('freqfilter', card)


class TestCategoryAdmin(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.parent = qa_utils.create_category(name="Dosimetry", slug="dosimetry", description="Dose")
        self.cat = qa_utils.create_category(name="Output", slug="output", description="Output tests")
        self.cat.parent = self.parent
        self.cat.save()
        self.url = reverse('admin:qa_category_change', args=(self.cat.pk,))

    def test_change_form_is_one_details_card_parent_first(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-header-bar qc-header-bar"', html)
        self.assertIn('Edit Category', html)
        self.assertEqual(html.count('class="tl-details-card qc-card"'), 1)
        fields = re.findall(r'class="tlb-field qc-field field-(\w+)', html)
        self.assertEqual(fields, ['parent', 'name', 'slug', 'description'])
        # mptt's tree select, with the current parent chosen
        select = re.search(r'<select name="parent"[^>]*>(.*?)</select>', html, re.S).group(1)
        self.assertRegex(select, r'<option value="%d" selected>\s*Dosimetry</option>' % self.parent.pk)
        self.assertIn('class="tlb-field qc-field field-description tl-col-full', html)
        self.assertIn('class="tlb-field qc-field field-parent tl-col-full', html)

    def test_used_in_lists_tests_and_links_to_filtered_test_list(self):
        t1 = qa_utils.create_test(name="Output 6X", category=self.cat)
        qa_utils.create_test(name="Output 10X", category=self.cat)
        qa_utils.create_test(name="Not here", category=self.parent)
        html = self.client.get(self.url).content.decode()
        card = html[html.index('id="qcc-used-card"'):]
        self.assertIn('<span class="tl-count-badge">2</span>', card)
        self.assertIn(reverse('admin:qa_test_change', args=(t1.pk,)), card)
        self.assertIn('Output 10X', card)
        self.assertNotIn('Not here', card)
        link = '%s?category__id__exact=%d' % (reverse('admin:qa_test_changelist'), self.cat.pk)
        self.assertIn(link, card)
        self.assertIn('See all 2 tests in the Test list', card)
        # ...and that link opens the Test list filtered to this category
        resp = self.client.get(link)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['cl'].result_count, 2)

    def test_used_in_is_capped(self):
        for i in range(3):
            qa_utils.create_test(name="Test %d" % i, category=self.cat)
        with mock.patch.object(qa_admin, 'CATEGORY_USED_IN_LIMIT', 2):
            html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('class="qcc-used-item"'), 2)
        self.assertIn('And 1 more test.', html)

    def test_used_in_empty_and_subcategory_note(self):
        html = self.client.get(reverse('admin:qa_category_change', args=(self.parent.pk,))).content.decode()
        self.assertIn('No tests are filed under this category yet.', html)
        self.assertIn('This category has 1 subcategory', html)

    def test_add_page_has_no_used_in(self):
        html = self.client.get(reverse('admin:qa_category_add')).content.decode()
        self.assertIn('Add Category', html)
        self.assertNotIn('id="qcc-used-card"', html)

    def test_save_still_saves(self):
        data = {'parent': self.parent.pk, 'name': 'Imaging', 'slug': 'imaging', 'description': 'kV and MV', '_save': 'Save'}
        resp = self.client.post(reverse('admin:qa_category_add'), data)
        self.assertEqual(resp.status_code, 302)
        cat = models.Category.objects.get(slug='imaging')
        self.assertEqual(cat.parent, self.parent)

    def test_errors_render_inside_the_card(self):
        resp = self.client.post(reverse('admin:qa_category_add'), {'name': '', 'slug': '', 'description': '', '_save': 'Save'})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('errornote', html)
        self.assertIn('qc-has-error', html)

    def test_view_only_user_gets_read_only_page(self):
        qa_utils.create_test(name="Output 6X", category=self.cat)
        _login_viewer(self.client, 'view_category')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Category', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        # Test names are listed, but not as links the viewer can't open
        self.assertIn('Output 6X', html)
        self.assertNotIn(reverse('admin:qa_test_changelist'), html)


class TestCategoryLists(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.parent = qa_utils.create_category(name="Dosimetry", slug="dosimetry", description="Dose")
        self.child = qa_utils.create_category(name="Output", slug="output", description="Output tests")
        self.child.parent = self.parent
        self.child.save()

    def test_tree_list_has_title_row_and_keeps_the_tree(self):
        resp = self.client.get(reverse('admin:qa_category_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-index-header qc-index-header"', html)
        self.assertIn('2 categories', html)
        self.assertIn('id="qcc-add-btn"', html)
        self.assertIn('href="%s"' % reverse('admin:qa_category_grid'), html)
        self.assertIn('class="tl-results-head"', html)
        self.assertIn('Category Tree', html)
        # django-mptt-admin's tree: its container, its data URL and its script
        self.assertIn('id="tree"', html)
        self.assertIn('data-url="%s"' % reverse('admin:qa_category_tree_json'), html)
        self.assertIn('django_mptt_admin/django_mptt_admin.js', html)
        # One page title: Django's own content title h1 isn't drawn as well
        self.assertEqual(len(re.findall(r'<h1(?! id="site-name")', html)), 1)

    def test_tree_data_still_served(self):
        resp = self.client.get(reverse('admin:qa_category_tree_json'))
        self.assertEqual(resp.status_code, 200)
        names = [node['name'] for node in resp.json()]
        self.assertIn('Dosimetry', names)

    def test_tree_drag_and_drop_move_still_works(self):
        resp = self.client.post(
            reverse('admin:qa_category_move', args=(self.child.pk,)),
            {'target_id': self.parent.pk, 'position': 'after'},
        )
        self.assertEqual(resp.status_code, 200)
        self.child.refresh_from_db()
        self.assertIsNone(self.child.parent)

    def test_grid_list_uses_shared_list_with_tree_button(self):
        resp = self.client.get(reverse('admin:qa_category_grid'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-index-header qc-index-header"', html)
        self.assertIn('id="qcc-tree-btn"', html)
        self.assertIn('href="%s"' % reverse('admin:qa_category_changelist'), html)
        self.assertIn('class="tl-btn tl-btn-primary"', html)
        self.assertIn('id="result_list"', html)
        self.assertIn('Description', html)
        self.assertNotIn('Get description', html)

    def test_view_only_tree_has_no_add_button(self):
        _login_viewer(self.client, 'view_category')
        resp = self.client.get(reverse('admin:qa_category_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn('id="qcc-add-btn"', html)
        self.assertNotIn('Drag categories', html)


class TestAutoSaveAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.unit = qa_utils.create_unit(name="Linac 2")
        self.tl = qa_utils.create_test_list(name="Daily Checks")
        self.utc = qa_utils.create_unit_test_collection(unit=self.unit, test_collection=self.tl)
        self.auto = models.AutoSave.objects.create(
            unit_test_collection=self.utc,
            test_list=self.tl,
            created_by=self.user,
            modified_by=self.user,
            data={
                'tests': {'output': 1.01, 'temp': 22, 'blank': None, 'empty': ''},
                'comments': {'output': 'looks fine', 'temp': ''},
                'skips': {'blank': True, 'output': False},
                'tli_comment': '',
            },
        )
        self.url = reverse('admin:qa_autosave_change', args=(self.auto.pk,))
        self.recover = reverse('perform_qa', kwargs={'pk': self.utc.pk}) + '?autosave_id=%d&amp;day=1' % self.auto.pk

    def test_list_recover_is_a_button_link(self):
        resp = self.client.get(reverse('admin:qa_autosave_changelist'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="tl-index-header qc-index-header"', html)
        self.assertIn('class="qcas-recover-btn"', html)
        self.assertIn('a.qcas-recover-btn', html)
        self.assertIn('href="%s"' % self.recover, html)
        self.assertIn('Linac 2', html)

    def test_summary_card_above_the_fields(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        summary = html.index('id="qcas-summary-card"')
        self.assertLess(summary, html.index('id="qc-card-details"'))
        card = html[summary:html.index('id="qc-card-details"')]
        self.assertIn('Linac 2', card)
        self.assertIn('Daily Checks', card)
        self.assertIn('2 test values', card)
        self.assertIn('1 skipped', card)
        self.assertIn('1 test comment', card)
        self.assertIn('href="%s"' % self.recover, card)
        self.assertIn(reverse('admin:qa_unittestcollection_change', args=(self.utc.pk,)), card)
        # The usual fields are still there to edit
        self.assertIn('name="work_started_0"', html)

    def test_recover_continues_an_in_progress_session_on_its_cycle_day(self):
        tli = qa_utils.create_test_list_instance(unit_test_collection=self.utc)
        self.auto.test_list_instance = tli
        self.auto.day = 2
        self.auto.save()
        html = self.client.get(self.url).content.decode()
        url = reverse('continue_tli', kwargs={'pk': tli.pk}) + '?autosave_id=%d&amp;day=3' % self.auto.pk
        self.assertIn('href="%s"' % url, html)
        self.assertIn('Changes to a test list already performed', html)

    def test_save_still_saves(self):
        resp = self.client.post(self.url, {
            'work_started_0': '2026-11-19', 'work_started_1': '10:00',
            'work_completed_0': '2026-11-19', 'work_completed_1': '10:30',
            'day': '0', 'data': '{"tests": {"output": 2}}',
            '_continue': 'Save and Continue Editing',
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context['adminform'].form.errors)
        self.auto.refresh_from_db()
        self.assertEqual(self.auto.data, {"tests": {"output": 2}})

    def test_view_only_user_sees_summary_read_only(self):
        _login_viewer(self.client, 'view_autosave')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="qcas-summary-card"', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertNotIn(reverse('admin:qa_unittestcollection_change', args=(self.utc.pk,)), html)

    def test_summary_counts_tolerate_odd_data(self):
        for data in (None, [], {'tests': [1, 2]}, {'tests': None, 'skips': 'x'}):
            with self.subTest(data=data):
                self.auto.data = data
                summary = qa_admin.autosave_summary(self.auto)
                self.assertEqual(summary['values'], 0)
                self.assertEqual(summary['skips'], 0)
