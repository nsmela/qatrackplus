"""Browser tests for reviewing QC: review and delete a session, bulk review, the overview, charts and listings.

Reviewing is where a physicist signs off on what a therapist measured, and the
charts are how drift is spotted over weeks. Most of what these pages do happens
in JavaScript (qareview.js, qabulkreview.js, qaoverview.js, qacharts.js), so
these tests drive them in a real browser and then check what was saved.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as e_c
from selenium.webdriver.support.ui import Select

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qatrack_core import scheduling
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log import models as sl_models
from qatrack.service_log.tests import utils as sl_utils


class ReviewTestCase(SeleniumTestCase):
    """A unit with a daily test list of two tests, and the statuses a clinic reviews with."""

    def setUp(self):
        super().setUp()
        self.unit = utils.create_unit(name='Linac One')
        self.group = utils.create_group(name='Physics')
        self.user.groups.add(self.group)
        self.unreviewed = utils.create_status(name='Unreviewed', slug='unreviewed', is_default=True)
        self.approved = utils.create_status(name='Approved', slug='approved', is_default=False, requires_review=False)
        self.rejected = utils.create_status(name='Rejected', slug='rejected', is_default=False, requires_review=False)
        self.daily = utils.create_frequency(name='Daily', slug='daily')

        self.output = utils.create_test(name='Output')
        self.flatness = utils.create_test(name='Flatness')
        self.test_list = utils.create_test_list('Daily Output')
        utils.create_test_list_membership(self.test_list, self.output, order=0)
        utils.create_test_list_membership(self.test_list, self.flatness, order=1)
        self.utc = self.assign(self.test_list)

    # ---- set-up helpers --------------------------------------------------

    def assign(self, test_list, unit=None, frequency=None, **kwargs):
        """Assign `test_list` to a unit; visible to every group, including self.group."""
        return utils.create_unit_test_collection(
            unit=unit or self.unit, frequency=frequency or self.daily, test_collection=test_list,
            assigned_to=self.group, **kwargs
        )

    def make_session(self, values, utc=None, days_ago=0):
        """Save a QC session directly, as if a therapist had performed it `days_ago` days ago.

        `values` is a list of (test, value) pairs, in test list order. Every
        result starts with the default (unreviewed) status.
        """
        utc = utc or self.utc
        work_completed = timezone.now() - timezone.timedelta(days=days_ago)
        tli = utils.create_test_list_instance(
            unit_test_collection=utc, created_by=self.user, work_completed=work_completed
        )
        for order, (test, value) in enumerate(values):
            uti = models.UnitTestInfo.objects.get(unit=utc.unit, test=test)
            models.TestInstance.objects.create(
                unit_test_info=uti,
                value=value,
                skipped=False,
                reference=uti.reference,
                tolerance=uti.tolerance,
                status=self.unreviewed,
                order=order,
                created_by=self.user,
                modified_by=self.user,
                test_list_instance=tli,
                work_started=tli.work_started,
                work_completed=tli.work_completed,
            )
        return tli

    def ti(self, tli, test):
        """The saved result for `test` in session `tli`, fresh from the database."""
        return models.TestInstance.objects.get(test_list_instance=tli, unit_test_info__test=test)

    # ---- page helpers ----------------------------------------------------

    def click_css(self, css):
        self.wait.until(e_c.element_to_be_clickable((By.CSS_SELECTOR, css))).click()

    def wait_for_success_alert(self):
        return self.wait_for_visible('.alert-success')

    def body_text(self):
        return self.driver.find_element(By.TAG_NAME, 'body').text


class TestReviewSession(ReviewTestCase):
    """The review page for one session (testlistinstance_review.html and qareview.js)."""

    def setUp(self):
        super().setUp()
        self.tli = self.make_session([(self.output, 1.0), (self.flatness, 2.0)])
        self.url = reverse('review_test_list_instance', kwargs={'pk': self.tli.pk})

    def row(self, test):
        """The review table row for `test`, found by the test name in its title."""
        return self.driver.find_element(
            By.XPATH, '//tr[contains(@class, "qa-valuerow")][td[contains(@class, "test-name")][@title="%s"]]' % test.name
        )

    def status_select(self, test):
        """The status dropdown on the row for `test`."""
        return Select(self.row(test).find_element(By.CSS_SELECTOR, 'td.review-status select'))

    def selected_checkbox(self, test):
        return self.row(test).find_element(By.CSS_SELECTOR, 'input.test-selected')

    def load_review(self):
        self.login()
        self.open(self.url)
        self.wait_for_element('#review-table')

    def submit_review(self):
        with self.wait_for_page_load():
            self.click_css('#submit-review')
        self.wait_for_success_alert()

    def test_each_test_keeps_the_status_chosen_on_its_own_row(self):
        """A status picked on one row must be saved for that test only, and the session marked reviewed.

        If the rows were mixed up, a physicist's "Rejected" could land on a
        result they approved, and the bad one would drop off the review list.
        """
        self.load_review()
        self.status_select(self.output).select_by_visible_text('Approved')
        self.status_select(self.flatness).select_by_visible_text('Rejected')
        self.submit_review()

        assert self.ti(self.tli, self.output).status == self.approved
        assert self.ti(self.tli, self.flatness).status == self.rejected
        self.tli.refresh_from_db()
        assert self.tli.all_reviewed
        assert self.tli.reviewed_by == self.user
        assert self.tli.reviewed is not None
        assert not models.TestListInstance.objects.unreviewed().filter(pk=self.tli.pk).exists()

    def test_a_row_left_unreviewed_keeps_the_session_on_the_unreviewed_list(self):
        """Approving one test but leaving another Unreviewed must not mark the whole session reviewed."""
        self.load_review()
        self.status_select(self.output).select_by_visible_text('Approved')
        self.submit_review()

        assert self.ti(self.tli, self.output).status == self.approved
        assert self.ti(self.tli, self.flatness).status == self.unreviewed
        self.tli.refresh_from_db()
        assert not self.tli.all_reviewed
        assert models.TestListInstance.objects.unreviewed().filter(pk=self.tli.pk).exists()

    def test_bulk_status_applies_only_to_selected_rows(self):
        """The status at the top of the table must change the ticked rows and leave unticked rows alone.

        This is how a physicist approves everything except the one result they
        want to look at again; if the untick were ignored, that result would be
        approved too.
        """
        self.load_review()
        self.selected_checkbox(self.flatness).click()
        assert not self.selected_checkbox(self.flatness).is_selected()

        Select(self.driver.find_element(By.ID, 'top-status-select')).select_by_visible_text('Approved')

        assert self.status_select(self.output).first_selected_option.text.strip() == 'Approved'
        assert self.status_select(self.flatness).first_selected_option.text.strip() == 'Unreviewed'
        # qareview.js keeps the two bulk dropdowns (top and bottom of the table) in step.
        assert Select(self.driver.find_element(By.ID, 'bot-status-select')).first_selected_option.text == 'Approved'

        self.submit_review()
        assert self.ti(self.tli, self.output).status == self.approved
        assert self.ti(self.tli, self.flatness).status == self.unreviewed

    def test_review_opened_from_a_service_event_returns_the_session_to_the_opener(self):
        """Reviewing in the pop-up from a service event must save, hand the session back and close.

        The service event form opens this pop-up for return-to-service QC; if
        the hand-back failed, the event would never learn the QC was reviewed.
        (The opener here is a stand-in; section 3 covers the service event form.)
        """
        self.login()
        main = self.driver.current_window_handle
        self.driver.execute_script(
            'window.reviewResult = null;'
            'window.setSearchResult = function(form, choice) { window.reviewResult = [form, String(choice)]; };'
        )
        popup_url = reverse('review_test_list_instance', kwargs={'rtsqa_form': 'rtsqa-0', 'pk': self.tli.pk})
        self.driver.execute_script('window.open(arguments[0], "review-popup");', popup_url)
        self.wait.until(lambda d: len(d.window_handles) == 2)
        popup = [h for h in self.driver.window_handles if h != main][0]
        self.driver.switch_to.window(popup)
        try:
            self.wait_for_element('#submit-review-ajax')
            self.wait_for_ajax()
            self.status_select(self.output).select_by_visible_text('Approved')
            self.status_select(self.flatness).select_by_visible_text('Approved')
            self.click_css('#submit-review-ajax')
            self.wait.until(lambda d: len(d.window_handles) == 1, 'the review pop-up did not close')
        finally:
            self.driver.switch_to.window(main)

        assert self.driver.execute_script('return window.reviewResult;') == ['rtsqa-0', str(self.tli.pk)]
        assert self.ti(self.tli, self.output).status == self.approved
        assert self.ti(self.tli, self.flatness).status == self.approved
        self.tli.refresh_from_db()
        assert self.tli.all_reviewed


class TestDeleteSession(ReviewTestCase):
    """Deleting a session from its review page (TestListInstanceDelete)."""

    def setUp(self):
        super().setUp()
        self.keep = self.make_session([(self.output, 1.0), (self.flatness, 2.0)], days_ago=2)
        self.tli = self.make_session([(self.output, 5.0), (self.flatness, 6.0)], days_ago=1)

    def open_review_from_unreviewed_list(self):
        """Go to the session's review page the way a user does: from the Unreviewed list."""
        self.login()
        self.open(reverse('unreviewed'))
        review_href = 'a[href^="%s"]' % reverse('review_test_list_instance', kwargs={'pk': self.tli.pk})
        self.wait_for_element('#listable-table-unreviewed ' + review_href)
        with self.wait_for_page_load():
            self.click_css('#listable-table-unreviewed ' + review_href)
        self.wait_for_element('#review-table')

    def confirm_delete(self):
        delete_href = 'a[href^="%s"]' % reverse('delete_test_list_instance', kwargs={'pk': self.tli.pk})
        with self.wait_for_page_load():
            self.click_css(delete_href)
        self.wait_for_text('.box-body', 'A total of 2 Test Instances')
        with self.wait_for_page_load():
            self.click_css('form button[type="submit"].btn-danger')

    def test_delete_removes_the_session_and_its_results(self):
        """Confirming a delete must remove the session and its results, keep the others, and go back to the list.

        The confirm page is the only warning before results are gone for good,
        so it must say how many results go with the session.
        """
        ti_pks = list(self.tli.testinstance_set.values_list('pk', flat=True))
        self.open_review_from_unreviewed_list()
        self.confirm_delete()

        self.wait_for_element('#listable-table-unreviewed')
        assert urlparse(self.driver.current_url).path == reverse('unreviewed')
        assert not models.TestListInstance.objects.filter(pk=self.tli.pk).exists()
        assert not models.TestInstance.objects.filter(pk__in=ti_pks).exists()
        assert models.TestListInstance.objects.filter(pk=self.keep.pk).exists()
        assert self.keep.testinstance_set.count() == 2

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'qa/views/review.py:248-249 get_success_url returns the empty "next" that '
            'testlistinstance_review.html:559 sends when the review page had no referrer; the browser is left '
            'on a blank page'
        ),
    )
    def test_delete_from_a_review_page_opened_directly_lands_on_a_page(self):
        """Deleting from a review page opened directly (a bookmark, a new tab) must still land on a real page.

        The Delete link carries the referring page as "next"; with no referrer
        it is empty, and the user is left looking at a blank page, unsure
        whether the session was deleted.
        """
        self.login()
        # driver.get, unlike self.open, sends no referrer: like typing the address or opening a bookmark.
        self.driver.get(self.live_server_url + reverse('review_test_list_instance', kwargs={'pk': self.tli.pk}))
        self.wait_for_element('#review-table')
        self.confirm_delete()
        self.wait.until(lambda d: d.execute_script("return document.readyState === 'complete';"))

        assert not models.TestListInstance.objects.filter(pk=self.tli.pk).exists()
        assert urlparse(self.driver.current_url).path != reverse('delete_test_list_instance', kwargs={'pk': self.tli.pk})
        assert self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="logout"]'), 'not left on a QATrack+ page'

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'qa/views/review.py:251-256 TestListInstanceDelete.delete() is never called on Django >= 4.0 '
            '(DeleteView.post calls form_valid), so the service event log never records the lost RTS QC'
        ),
    )
    def test_deleting_return_to_service_qc_is_logged_on_the_service_event(self):
        """Deleting a session used as return-to-service QC must leave a note in that service event's log.

        The view has code for this, but it is in a method Django no longer calls.
        """
        sl_utils.create_service_event_status(is_default=True)
        usa = sl_utils.create_unit_service_area(self.unit)
        se = sl_utils.create_service_event(unit_service_area=usa)
        sl_utils.create_return_to_service_qa(
            service_event=se, unit_test_collection=self.utc, add_test_list_instance=self.tli
        )
        self.open_review_from_unreviewed_list()
        self.confirm_delete()

        self.wait_for_element('#listable-table-unreviewed')
        assert not models.TestListInstance.objects.filter(pk=self.tli.pk).exists()
        assert sl_models.ServiceLog.objects.filter(service_event=se, log_type=sl_models.CHANGED_RTSQA).exists()


class TestBulkReview(ReviewTestCase):
    """Bulk review on the Unreviewed list (qabulkreview.js)."""

    def setUp(self):
        super().setUp()
        self.first = self.make_session([(self.output, 1.0), (self.flatness, 2.0)], days_ago=3)
        self.second = self.make_session([(self.output, 1.1), (self.flatness, 2.1)], days_ago=2)
        self.untouched = self.make_session([(self.output, 1.2), (self.flatness, 2.2)], days_ago=1)

    def row(self, tli):
        select = self.driver.find_element(By.CSS_SELECTOR, '#listable-table-unreviewed select[data-tli="%d"]' % tli.pk)
        return select.find_element(By.XPATH, './ancestor::tr[1]')

    def tick(self, tli):
        box = self.row(tli).find_element(By.CSS_SELECTOR, 'input.test-selected')
        box.click()
        assert box.is_selected()

    def summary_rows(self):
        return [
            [td.text for td in tr.find_elements(By.TAG_NAME, 'td')]
            for tr in self.driver.find_elements(By.CSS_SELECTOR, '#instance-summary tbody tr')
        ]

    def open_confirmation(self):
        self.click_css('#submit-review')
        self.wait_for_visible('#confirm-update')

    def test_bulk_review_summarises_cancels_and_confirms(self):
        """The confirmation must list just the ticked sessions; Cancel must change nothing; Confirm must review them.

        The summary is the physicist's last look at what they are about to
        sign off. If it miscounted, or Cancel still saved, sessions nobody
        looked at would be marked reviewed.
        """
        self.login()
        self.open(reverse('unreviewed'))
        self.wait_for_element('#listable-table-unreviewed select[data-tli="%d"]' % self.untouched.pk)
        self.wait_for_ajax()

        self.tick(self.first)
        self.tick(self.second)
        Select(
            self.driver.find_element(By.CSS_SELECTOR, '#listable-table-unreviewed thead select.bulk-status')
        ).select_by_visible_text('Approved')

        # Only the ticked rows take the bulk status.
        for tli, expected in ((self.first, 'Approved'), (self.second, 'Approved'), (self.untouched, '---')):
            row_select = Select(self.row(tli).find_element(By.CSS_SELECTOR, 'select[data-tli]'))
            assert row_select.first_selected_option.text.strip() == expected

        self.open_confirmation()
        assert self.summary_rows() == [['Daily Output', 'Linac One', '2', 'Approved']]

        self.click_css('#bulk-review-modal .modal-footer button[data-dismiss="modal"]')
        self.wait_for_invisible('#bulk-review-modal')
        assert models.TestListInstance.objects.unreviewed().count() == 3
        assert not models.TestInstance.objects.filter(status=self.approved).exists()

        self.open_confirmation()
        with self.wait_for_page_load():
            self.click_css('#confirm-update')
        self.wait_for_success_alert()
        assert 'Successfully reviewed 2 test list instances' in self.body_text()

        for tli in (self.first, self.second):
            tli.refresh_from_db()
            assert tli.all_reviewed
            assert tli.reviewed_by == self.user
            assert set(tli.testinstance_set.values_list('status', flat=True)) == {self.approved.pk}
        self.untouched.refresh_from_db()
        assert not self.untouched.all_reviewed
        assert set(self.untouched.testinstance_set.values_list('status', flat=True)) == {self.unreviewed.pk}

        # The page reloaded from the server, so the reviewed sessions are gone from the list.
        self.wait_for_element('#listable-table-unreviewed select[data-tli="%d"]' % self.untouched.pk)
        rows = self.driver.find_elements(By.CSS_SELECTOR, '#listable-table-unreviewed tbody select[data-tli]')
        assert [int(r.get_attribute('data-tli')) for r in rows] == [self.untouched.pk]


class TestSessionDetails(ReviewTestCase):

    def test_details_page_shows_each_value_and_status(self):
        """The read-only session page must show every test's value and its review status.

        This is the page a chart point's View link and the history list open.
        """
        tli = self.make_session([(self.output, 1.25), (self.flatness, 2.5)])
        models.TestInstance.objects.filter(test_list_instance=tli, unit_test_info__test=self.flatness).update(
            status=self.approved
        )
        self.login()
        self.open(reverse('view_test_list_instance', kwargs={'pk': tli.pk}))
        self.wait_for_element('#review-table')

        shown = {}
        for value_cell in self.driver.find_elements(By.CSS_SELECTOR, '#review-table tbody td.review-value'):
            row = value_cell.find_element(By.XPATH, './parent::tr')
            name = row.find_element(By.CSS_SELECTOR, 'td:first-child').get_attribute('title')
            shown[name] = (
                row.find_element(By.CSS_SELECTOR, 'td.review-value').text.strip(),
                row.find_element(By.CSS_SELECTOR, 'td.review-status').text.strip(),
            )
        assert shown == {
            'Output': (self.ti(tli, self.output).value_display(), 'Unreviewed'),
            'Flatness': (self.ti(tli, self.flatness).value_display(), 'Approved'),
        }


class TestOverview(ReviewTestCase):
    """The QC Program Overview (/qc/review/, qaoverview.js)."""

    def test_overview_counts_and_lists_assignments_by_due_status(self):
        """The overview boxes must count assignments by due status, and each unit box must list its test lists.

        Supervisors use this page to see at a glance what is overdue; a wrong
        count hides overdue QC.
        """
        now = timezone.now()
        monthly = utils.create_frequency(name='Monthly', slug='monthly', interval=30, window_end=7)
        weekly = utils.create_frequency(name='Weekly', slug='weekly', interval=7, window_end=2)
        mech = utils.create_test_list('Monthly Mechanical')
        utils.create_test_list_membership(mech, self.flatness)
        imaging = utils.create_test_list('Weekly Imaging')
        utils.create_test_list_membership(imaging, self.output)
        adhoc = utils.create_test_list('After Repair')
        utils.create_test_list_membership(adhoc, self.output)
        unit_two = utils.create_unit(name='Linac Two')

        overdue = self.utc  # daily, due ten days ago
        due = self.assign(mech, frequency=monthly)  # due yesterday, inside its 7 day window
        not_due = self.assign(imaging, unit=unit_two, frequency=weekly)
        no_due_date = utils.create_unit_test_collection(
            unit=unit_two, test_collection=adhoc, assigned_to=self.group, null_frequency=True
        )
        for utc, when in ((overdue, now - timezone.timedelta(days=10)), (due, now - timezone.timedelta(days=1)),
                          (not_due, now + timezone.timedelta(days=5)), (no_due_date, None)):
            models.UnitTestCollection.objects.filter(pk=utc.pk).update(due_date=when)
        expected_status = {
            overdue.pk: scheduling.OVERDUE, due.pk: scheduling.DUE, not_due.pk: scheduling.NOT_DUE,
            no_due_date.pk: scheduling.NO_DUE_DATE,
        }
        for utc in models.UnitTestCollection.objects.all():
            assert utc.due_status() == expected_status[utc.pk], 'set-up error for %s' % utc.name

        self.login()
        self.open(reverse('overview'))
        self.wait.until(lambda d: 'loading' not in d.find_element(By.TAG_NAME, 'body').get_attribute('class'))
        self.wait_for_element('#box-%s' % unit_two.number)

        counts = {
            box: self.driver.find_element(By.CSS_SELECTOR, '#%s h3' % box).text
            for box in ('due-count-ndd', 'due-count-nd', 'due-count-d', 'due-count-od')
        }
        assert counts == {'due-count-ndd': '1', 'due-count-nd': '1', 'due-count-d': '1', 'due-count-od': '1'}

        def listed(unit):
            box = self.driver.find_element(By.ID, 'box-%s' % unit.number)
            return {
                a.text: a.get_attribute('href')
                for a in box.find_elements(By.CSS_SELECTOR, 'td.testlist-link a')
            }

        base = self.live_server_url
        assert listed(self.unit) == {
            'Daily Output': base + reverse('review_utc', args=(overdue.pk,)),
            'Monthly Mechanical': base + reverse('review_utc', args=(due.pk,)),
        }
        assert listed(unit_two) == {
            'Weekly Imaging': base + reverse('review_utc', args=(not_due.pk,)),
            'After Repair': base + reverse('review_utc', args=(no_due_date.pk,)),
        }
        overdue_label = self.driver.find_element(
            By.XPATH, '//div[@id="box-%s"]//tr[td/a[text()="Daily Output"]]//span[contains(@class, "due-status")]'
            % self.unit.number
        )
        assert 'action' in overdue_label.get_attribute('class').split()


class TestListings(ReviewTestCase):
    """Choosing a unit and its test lists, as a therapist does before performing QC."""

    def setUp(self):
        super().setUp()
        self.mech = utils.create_test_list('Monthly Mechanical')
        utils.create_test_list_membership(self.mech, self.flatness)
        self.mech_utc = self.assign(self.mech)
        self.table = '#listable-table-qa_by_unit'

    def open_unit_list(self):
        self.login()
        self.open(reverse('choose_unit'))
        with self.wait_for_page_load():
            self.click_css('a[href="%s"]' % reverse('qa_by_unit', kwargs={'unit_number': self.unit.number}))
        self.wait_for_text(self.table + ' tbody', 'Monthly Mechanical')
        self.wait_for_ajax()

    def listed_names(self):
        """The Test List/Cycle column, found by its data-field rather than its position."""
        return self.driver.execute_script(
            "var table = $(arguments[0]);"
            "var col = table.find('thead tr:first th').index(table.find('thead tr:first th[data-field=\"name\"]'));"
            "return table.find('tbody tr').map(function() { return $(this).children().eq(col).text().trim(); }).get();",
            self.table,
        )

    def test_choose_unit_then_perform_opens_that_assignment(self):
        """Unit button, then Perform on a row, must open the Perform page for that row's test list.

        Opening the wrong assignment means results are recorded against the
        wrong test list or unit.
        """
        self.open_unit_list()
        assert sorted(self.listed_names()) == ['Daily Output', 'Monthly Mechanical']

        perform_href = reverse('perform_qa', kwargs={'pk': self.mech_utc.pk})
        with self.wait_for_page_load():
            self.click_css(self.table + ' a[href^="%s"]' % perform_href)
        self.wait_for_element('#perform-qa-table')

        assert urlparse(self.driver.current_url).path == perform_href
        names = [
            td.get_attribute('title')
            for td in self.driver.find_elements(By.CSS_SELECTOR, '#perform-qa-table tr.qa-valuerow td.qa-name')
        ]
        assert names == ['Flatness']

    def test_name_filter_narrows_the_list(self):
        """Typing in the Test List/Cycle filter must narrow the server-side list to matching names."""
        self.open_unit_list()
        name_filter = self.driver.find_element(By.CSS_SELECTOR, self.table + ' thead th[data-field="name"] input.text_filter')
        name_filter.click()
        name_filter.clear()
        name_filter.send_keys('Mech')
        self.wait.until(lambda d: self.listed_names() == ['Monthly Mechanical'])

        name_filter.send_keys(Keys.CONTROL, 'a')
        name_filter.send_keys(Keys.BACKSPACE)
        self.wait.until(lambda d: sorted(self.listed_names()) == ['Daily Output', 'Monthly Mechanical'])


class ChartsTestCase(ReviewTestCase):
    """Three sessions of the daily list, ten to twenty days ago, plus a list on another unit."""

    def setUp(self):
        super().setUp()
        self.sessions = [
            self.make_session([(self.output, value), (self.flatness, 2.0)], days_ago=days)
            for days, value in ((20, 1.0), (15, 1.1), (10, 0.9))
        ]
        # Something the cascade must leave out: a different unit, frequency and test.
        self.other_unit = utils.create_unit(name='CT Sim')
        self.weekly = utils.create_frequency(name='Weekly', slug='weekly', interval=7)
        self.hu = utils.create_test(name='HU Water')
        ct_list = utils.create_test_list('CT Weekly')
        utils.create_test_list_membership(ct_list, self.hu)
        ct_utc = self.assign(ct_list, unit=self.other_unit, frequency=self.weekly)
        self.make_session([(self.hu, 0.0)], utc=ct_utc, days_ago=5)

    def output_ti_ids(self):
        return sorted(
            'ti_%d' % pk for pk in
            models.TestInstance.objects.filter(unit_test_info__test=self.output).values_list('pk', flat=True)
        )

    def option(self, kind, pk):
        return '#felter-option-%s-div-%s' % (kind, pk)

    def is_shown(self, css):
        try:
            return self.driver.find_element(By.CSS_SELECTOR, css).is_displayed()
        except NoSuchElementException:
            return False

    def is_selected_option(self, kind, pk):
        return 'felter-selected' in self.driver.find_element(By.CSS_SELECTOR, self.option(kind, pk)).get_attribute(
            'class'
        )

    def pick(self, kind, pk):
        """Click a filter option once it is shown, as a user would."""
        self.wait_for_visible(self.option(kind, pk))
        self.click_css(self.option(kind, pk))
        self.wait.until(lambda d: self.is_selected_option(kind, pk))
        self.wait_for_ajax()

    def open_charts(self, url=None):
        self.login()
        self.open(url or reverse('charts'))
        self.wait_for_element(self.option('unit', self.unit.pk))
        self.wait.until(
            lambda d: d.execute_script("return $('#filter-box').css('opacity') === '1';")
        )
        self.wait_for_ajax()

    def choose_output(self):
        self.pick('unit', self.unit.pk)
        self.pick('freq', self.daily.pk)
        self.pick('tl', self.test_list.pk)
        self.pick('test', self.output.pk)

    def generate(self):
        self.click_css('#gen-chart')
        self.wait_for_ajax()
        self.wait.until(lambda d: d.find_element(By.ID, 'gen-chart').text == 'Generate Chart')

    def plotted_points(self):
        return sorted(
            c.get_attribute('id') for c in self.driver.find_elements(By.CSS_SELECTOR, '#chart svg circle[id^="ti_"]')
        )

    def table_headers(self):
        return [th.text for th in self.driver.find_elements(By.CSS_SELECTOR, '#data-table-wrapper thead th.header')]

    def table_rows(self):
        return [
            [td.text for td in tr.find_elements(By.TAG_NAME, 'td')]
            for tr in self.driver.find_elements(By.CSS_SELECTOR, '#data-table-wrapper tbody tr')
        ]

    def chart_link(self):
        """The Link box's URL, as a path and query a user could paste."""
        url = urlparse(self.driver.find_element(By.ID, 'chart-url').get_attribute('value'))
        assert url.path == reverse('charts')
        return '%s?%s' % (url.path, url.query)


class TestCharts(ChartsTestCase):

    def test_filters_cascade_and_generate_plots_the_chosen_test(self):
        """Each filter must offer only what fits the choice before it; Generate must plot exactly that data.

        If the cascade offered the wrong test lists, or the chart drew other
        results, a physicist would read a trend from the wrong machine.
        """
        self.open_charts()
        for kind, pk in (('freq', self.daily.pk), ('tl', self.test_list.pk), ('test', self.output.pk)):
            assert not self.is_shown(self.option(kind, pk)), '%s %s shown before a unit was chosen' % (kind, pk)

        self.pick('unit', self.unit.pk)
        self.wait_for_visible(self.option('freq', self.daily.pk))
        assert not self.is_shown(self.option('freq', self.weekly.pk)), 'CT Sim has the only weekly list'
        assert not self.is_shown(self.option('freq', 0)), 'Linac One has no ad hoc lists'
        assert not self.is_shown(self.option('tl', self.test_list.pk)), 'test lists shown before a frequency'

        self.pick('freq', self.daily.pk)
        self.wait_for_visible(self.option('tl', self.test_list.pk))
        assert not self.is_shown(self.option('test', self.output.pk)), 'tests shown before a test list'

        self.pick('tl', self.test_list.pk)
        self.wait_for_visible(self.option('test', self.output.pk))
        self.wait_for_visible(self.option('test', self.flatness.pk))
        assert not self.is_shown(self.option('test', self.hu.pk)), 'a CT test offered for a linac test list'

        self.pick('test', self.output.pk)
        assert self.driver.find_element(By.ID, 'gen-chart').is_enabled()
        self.click_css(self.option('test', self.output.pk))  # and off again
        self.wait.until(lambda d: not d.find_element(By.ID, 'gen-chart').is_enabled())
        self.pick('test', self.output.pk)
        self.wait.until(lambda d: d.find_element(By.ID, 'gen-chart').is_enabled())

        self.generate()
        self.wait_for_element('#chart svg circle')
        assert self.plotted_points() == self.output_ti_ids()
        assert self.table_headers() == ['Linac One - Daily Output :: Output']
        rows = self.table_rows()
        assert len(rows) == 3
        expected_values = [
            ti.value_display() for ti in models.TestInstance.objects.filter(
                unit_test_info__test=self.output
            ).order_by('work_completed')
        ]
        assert [r[1] for r in rows] == expected_values
        assert self.javascript_errors() == []

    def test_range_with_no_data_says_so(self):
        """A date range with no results must say "No data found" rather than draw a broken chart or fail."""
        self.open_charts()
        self.choose_output()

        self.click_css('#date-range')
        self.click_css('.daterangepicker .ranges li[data-range-key="Last 7 Days"]')
        self.wait.until(lambda d: not self.is_shown('.daterangepicker'))

        self.generate()
        self.wait_for_text('#data-table-wrapper tbody', 'No data found')
        assert self.plotted_points() == []
        assert self.table_headers() == []
        assert self.javascript_errors() == []

    def test_control_chart_image_is_drawn_for_the_chosen_test(self):
        """Choosing Control Chart must load the control chart image for the chosen test, and fill the table."""
        self.open_charts()
        self.choose_output()
        Select(self.driver.find_element(By.ID, 'chart-type')).select_by_value('control')
        self.wait_for_visible('#subgroup-size')
        self.generate()

        image = self.wait_for_visible('#control-chart-container img')
        self.wait.until(lambda d: d.execute_script(
            'var img = arguments[0]; return img.complete && img.naturalWidth > 0;', image
        ))
        self.wait.until(lambda d: not self.is_shown('#control-chart-container .please-wait'))
        assert not self.is_shown('#control-chart-container .cc-error')

        src = urlparse(image.get_attribute('src'))
        assert src.path == reverse('control_chart')
        query = parse_qs(src.query)
        assert query['tests[]'] == [str(self.output.pk)]
        assert query['units[]'] == [str(self.unit.pk)]
        assert query['subgroup_size'] == ['1']

        self.wait.until(lambda d: len(self.table_rows()) == 3)
        assert self.table_headers() == ['Linac One - Daily Output :: Output']
        assert self.javascript_errors() == []


class TestChartLink(ChartsTestCase):
    """The Link box: a URL that reopens the same chart (qacharts.js set_chart_url / set_options_from_url)."""

    def test_link_reopens_the_same_chart(self):
        """Opening a chart link must restore the filters and date range and draw the same chart.

        Physicists paste these links into reports and emails; a link that
        opened a different chart would be worse than none.
        """
        self.open_charts()
        self.choose_output()
        self.generate()
        self.wait_for_element('#chart svg circle')
        date_range = self.driver.find_element(By.ID, 'date-range').get_attribute('value')
        link = self.chart_link()

        self.open_charts(link)
        self.wait_for_element('#chart svg circle')
        self.wait_for_ajax()
        for kind, pk in (('unit', self.unit.pk), ('freq', self.daily.pk), ('tl', self.test_list.pk),
                         ('test', self.output.pk)):
            assert self.is_selected_option(kind, pk), '%s %s not restored from the link' % (kind, pk)
        assert not self.is_selected_option('test', self.flatness.pk)
        assert self.driver.find_element(By.ID, 'date-range').get_attribute('value') == date_range
        assert self.plotted_points() == self.output_ti_ids()
        assert len(self.table_rows()) == 3

    @pytest.mark.xfail(
        strict=True,
        reason='qa/static/qa/js/qacharts.js:506,2346 the link writes "relative" but is read back as "relative_diff"',
    )
    def test_link_restores_relative_to_reference(self):
        """A link made with "Relative to reference" ticked must reopen with it ticked."""
        self.open_charts()
        self.choose_output()
        self.click_css('#relative-diff')
        self.generate()
        self.wait_for_element('#chart svg circle')
        assert self.table_headers() == ['Linac One - Daily Output :: Output (relative to ref)']

        self.open_charts(self.chart_link())
        self.wait_for_element('#chart svg circle')
        self.wait_for_ajax()
        assert self.driver.find_element(By.ID, 'relative-diff').is_selected()
        assert self.table_headers() == ['Linac One - Daily Output :: Output (relative to ref)']

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'qa/static/qa/js/qacharts.js:478,2371,2389 an unticked show_events is left out of the link, '
            'and .prop("checked", undefined) leaves the box ticked'
        ),
    )
    def test_link_restores_unticked_service_events(self):
        """A link made with "Show service events?" unticked must reopen with it unticked."""
        self.open_charts()
        self.choose_output()
        self.click_css('#show_events')
        assert not self.driver.find_element(By.ID, 'show_events').is_selected()
        self.generate()
        self.wait_for_element('#chart svg circle')

        self.open_charts(self.chart_link())
        self.wait_for_element('#chart svg circle')
        assert not self.driver.find_element(By.ID, 'show_events').is_selected()

    @pytest.mark.xfail(
        strict=True,
        reason='qa/static/qa/js/qacharts.js:504,2344 the link writes "fit_data" but is read back as "include_fit"',
    )
    def test_link_restores_control_chart_fit(self):
        """A control chart link made with "Fit" ticked must reopen with it ticked."""
        self.open_charts()
        self.choose_output()
        Select(self.driver.find_element(By.ID, 'chart-type')).select_by_value('control')
        self.wait_for_visible('#include-fit')
        self.click_css('#include-fit')
        self.click_css('#gen-chart')
        self.wait_for_visible('#control-chart-container img')

        self.open_charts(self.chart_link())
        self.wait_for_visible('#control-chart-container img')
        assert Select(self.driver.find_element(By.ID, 'chart-type')).first_selected_option.get_attribute('value') \
            == 'control'
        assert self.driver.find_element(By.ID, 'include-fit').is_selected()

