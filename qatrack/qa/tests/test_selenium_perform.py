"""Browser tests for the Perform QC page (qa/js/qa.js).

The perform page decides in JavaScript whether each measurement is shown as
OK, TOL or ACT, long before the server sees it. These tests drive that page in
a real browser and then check the database, so that what a therapist sees
while performing QC is held to the same answer the server records.
"""

import os
import re
import shutil
import tempfile

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.wait import WebDriverWait

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log.tests import utils as sl_utils

# Bootstrap button classes qa.js uses to colour the status cell.
OK_CLASS = 'btn-success'
TOL_CLASS = 'btn-warning'
ACT_CLASS = 'btn-danger'
STATUS_CLASSES = (OK_CLASS, TOL_CLASS, ACT_CLASS, 'btn-info')

# The formats the date pickers write (FLATPICKR_DATE_FMT 'd M Y' and FLATPICKR_DATETIME_FMT 'Y-m-d H:i').
FLATPICKR_DATE = '%d %b %Y'
FLATPICKR_DATETIME = '%Y-%m-%d %H:%M'

# What the status cell says (settings.TEST_STATUS_DISPLAY_SHORT) for each saved pass_fail value.
DISPLAYED_TO_PASS_FAIL = {'OK': models.OK, 'TOL': models.TOLERANCE, 'ACT': models.ACTION}


@pytest.mark.selenium
class PerformQCTestCase(SeleniumTestCase):
    """Shared set-up and helpers for driving the Perform QC page."""

    def setUp(self):
        super().setUp()
        self.unit = utils.create_unit()
        self.group = utils.create_group()
        self.user.groups.add(self.group)
        self.default_status = utils.create_status(name='Unreviewed', slug='unreviewed', is_default=True)
        self.test_list = utils.create_test_list('Daily QC')

        sl_utils.create_service_event_status(is_default=True)
        sl_utils.create_unit_service_area(self.unit)
        sl_utils.create_service_type()

    # ---- set-up helpers --------------------------------------------------

    def make_test(self, name, test_type=models.SIMPLE, **kwargs):
        """Create a test and add it to the end of self.test_list."""
        calc = kwargs.pop('calculation_procedure', None)
        formatting = kwargs.pop('formatting', None)
        test = utils.create_test(name=name, test_type=test_type, **kwargs)
        if calc is not None or formatting is not None:
            test.calculation_procedure = calc or ''
            test.formatting = formatting or ''
            test.save()
        order = models.TestListMembership.objects.filter(test_list=self.test_list).count()
        utils.create_test_list_membership(self.test_list, test, order=order)
        return test

    def assign(self, test_list=None):
        """Assign the test list to the unit (this creates the UnitTestInfos)."""
        self.utc = utils.create_unit_test_collection(unit=self.unit, test_collection=test_list or self.test_list)
        self.url = reverse('perform_qa', kwargs={'pk': self.utc.pk})
        return self.utc

    def set_ref_tol(self, test, ref=None, tol=None):
        uti = models.UnitTestInfo.objects.get(unit=self.unit, test=test)
        if ref is not None:
            ref_type = models.BOOLEAN if test.type == models.BOOLEAN else models.NUMERICAL
            uti.reference = utils.create_reference(name='ref %s' % test.slug, ref_type=ref_type, value=ref)
        uti.tolerance = tol
        uti.save()
        return uti

    def make_limited_user(self):
        """A non-superuser in self.group who may perform QC and nothing more.

        In particular they lack qa.can_view_ref_tol and qa.can_skip_without_comment.
        """
        user = utils.create_user(uname='therapist', pwd=self.password, is_staff=False, is_superuser=False)
        user.groups.add(self.group)
        user.user_permissions.set(Permission.objects.filter(codename='add_testlistinstance'))
        return user

    # ---- page helpers ----------------------------------------------------

    def wait_for_idle(self):
        """Wait until the page has finished loading, calculating and autosaving."""
        self.wait_until(
            lambda: self.driver.execute_script(
                "return typeof jQuery !== 'undefined' && jQuery.active === 0"
                " && !document.body.classList.contains('loading')"
                " && !jQuery('#submit-qa').prop('disabled');"
            ),
            message='perform page never became idle',
        )

    def load_perform(self, url=None, user=None):
        self.login(user=user)
        self.open(url or self.url)
        self.wait_for_element('#perform-qa-table')
        self.wait_for_idle()

    def value_input(self, slug):
        return self.driver.find_element(By.CSS_SELECTOR, '#%s-value .qa-input' % slug)

    def enter_value(self, slug, value):
        """Type a value the way a user would; the change event fires when focus leaves."""
        el = self.value_input(slug)
        el.clear()
        el.send_keys(str(value))
        # Make sure every key landed before focus leaves and the change event fires.
        self.wait_until(
            lambda: el.get_attribute('value') == str(value) or not self._numeric(value),
            message='%s never showed %r after typing' % (slug, value),
        )
        el.send_keys(Keys.TAB)

    def choose(self, slug, text):
        Select(self.driver.find_element(By.CSS_SELECTOR, '#%s-value select' % slug)).select_by_visible_text(text)

    def status_cell(self, slug):
        return self.driver.find_element(By.ID, '%s-status' % slug)

    def status_text(self, slug):
        return self.status_cell(slug).text.strip()

    def status_colour(self, slug):
        classes = self.status_cell(slug).get_attribute('class').split()
        found = [c for c in STATUS_CLASSES if c in classes]
        return found[0] if found else None

    def wait_for_status(self, slug, text, colour=None):
        """Wait for the status cell to read exactly `text` (and have the `colour` class, if given).

        An exact match on purpose: 'TOL' is contained in 'NO TOL'.
        """

        def matches():
            if self.status_text(slug) != text:
                return False
            return colour is None or self.status_colour(slug) == colour

        try:
            self.wait_until(matches)
        except TimeoutException:
            raise AssertionError(
                'status of %s: expected %r/%s, page shows %r/%s' %
                (slug, text, colour, self.status_text(slug), self.status_colour(slug))
            )

    def submit(self):
        """Click Submit once the page is idle, and wait for the next page to load.

        The button is disabled while an autosave or calculation is in flight. An
        autosave can start between our idle check and the click, swallowing it,
        so if the form does not start submitting we wait for idle and try again.
        """
        form = self.driver.find_element(By.ID, 'qa-form')

        def submitting():
            # The page can navigate away between the two checks. A stale form or a
            # missing button both mean the submit went through.
            if self._stale(form):
                return True
            try:
                return self.driver.find_element(By.ID, 'submit-qa').text == 'Submitting...'
            except (NoSuchElementException, StaleElementReferenceException):
                return True

        for attempt in range(3):
            self.wait_for_idle()
            try:
                self.driver.find_element(By.ID, 'submit-qa').click()
            except (NoSuchElementException, StaleElementReferenceException):
                # A slow earlier click was submitted after all.
                break
            try:
                WebDriverWait(self.driver, self.timeout).until(lambda d: submitting())
                break
            except TimeoutException:
                if attempt == 2:
                    raise
        WebDriverWait(self.driver, self.timeout * 3).until(lambda d: self._stale(form))

    @staticmethod
    def _numeric(value):
        """True for a plain number like 10.5 or -2, which a number field shows exactly as typed."""
        return re.fullmatch(r'-?\d+(\.\d+)?', str(value)) is not None

    @staticmethod
    def _stale(element):
        try:
            element.is_enabled()
            return False
        except StaleElementReferenceException:
            return True

    def saved(self, test):
        """The one TestInstance saved for `test`."""
        return models.TestInstance.objects.get(unit_test_info__test=test)

    def open_sidebar_menu(self, menu_id, list_id):
        """Expand the collapsed sidebar and one of its tree menus, as a user would."""
        if 'sidebar-collapse' in self.driver.find_element(By.TAG_NAME, 'body').get_attribute('class'):
            self.click('sidebar-toggle')
            self.wait_until(
                lambda: 'sidebar-collapse' not in self.driver.find_element(By.TAG_NAME, 'body').get_attribute('class')
            )
        self.click(menu_id)
        self.wait_for_visible('#%s' % list_id)

    def make_session(self, values, in_progress=False):
        """Save a test list instance directly, as if it had been performed earlier.

        `values` is a list of (test, value) pairs, in test list order.
        """
        tli = utils.create_test_list_instance(
            unit_test_collection=self.utc, created_by=self.user, in_progress=in_progress
        )
        for order, (test, value) in enumerate(values):
            uti = models.UnitTestInfo.objects.get(unit=self.unit, test=test)
            models.TestInstance.objects.create(
                unit_test_info=uti,
                value=value,
                skipped=False,
                reference=uti.reference,
                tolerance=uti.tolerance,
                status=self.default_status,
                order=order,
                created_by=self.user,
                modified_by=self.user,
                test_list_instance=tli,
                work_started=tli.work_started,
                work_completed=tli.work_completed,
            )
        return tli

    def make_file(self, name, content):
        """Write a small file for uploading and return its absolute path."""
        directory = tempfile.mkdtemp(prefix='qatrack-perform-')
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, name)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def use_temporary_media_root(self):
        """Keep uploaded files out of the working tree."""
        media = tempfile.mkdtemp(prefix='qatrack-media-')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)


    # ---- dates and times ------------------------------------------------

    @staticmethod
    def aware(*args):
        return timezone.make_aware(timezone.datetime(*args))

    def field(self, el_id):
        return self.driver.find_element(By.ID, el_id).get_attribute('value')

    def type_datetime(self, el_id, text, accepted=True):
        """Type into a work time box. Unless told the picker will refuse it, wait until the box shows it."""
        el = self.driver.find_element(By.ID, el_id)
        el.send_keys(Keys.CONTROL, 'a')
        el.send_keys(Keys.BACKSPACE, text, Keys.TAB)
        if accepted:
            self.wait_until(lambda: self.field(el_id) == text, message='%s never showed %r' % (el_id, text))

    def pick_in_calendar(self, slug, day, hour=None, minute=None):
        """Choose `day` (and a time) in the test's flatpickr calendar, as a user would with the mouse.

        The calendar opens on the current month, so this steps back or forward to
        the month of `day` with the arrows first.
        """
        is_datetime = hour is not None
        self.click_by_css_selector('#%s-value .choose-date%s' % (slug, 'time' if is_datetime else ''))
        calendar = self.wait_for_visible('.flatpickr-calendar.open')
        instance = "document.querySelector('#%s-value .qa-input')._flatpickr" % slug

        def shown():
            year, month = self.driver.execute_script('return [%s.currentYear, %s.currentMonth + 1];' % (instance, instance))
            return (year, month)

        for _ in range(36):
            if shown() == (day.year, day.month):
                break
            arrow = '.flatpickr-prev-month' if shown() > (day.year, day.month) else '.flatpickr-next-month'
            calendar.find_element(By.CSS_SELECTOR, arrow).click()
        assert shown() == (day.year, day.month)

        calendar.find_element(
            By.XPATH,
            './/span[contains(@class, "flatpickr-day") and not(contains(@class, "prevMonthDay"))'
            ' and not(contains(@class, "nextMonthDay")) and normalize-space(text())="%d"]' % day.day,
        ).click()

        if is_datetime:
            for css, value in (('.flatpickr-hour', hour), ('.flatpickr-minute', minute), ('.flatpickr-second', 0)):
                box = calendar.find_element(By.CSS_SELECTOR, css)
                box.click()
                # Ctrl+A does not select the text of these number boxes in every browser.
                self.driver.execute_script('arguments[0].select();', box)
                box.send_keys('%02d' % value, Keys.TAB)
            # Closing the calendar is what commits the time to the input.
            self.driver.execute_script('%s.close();' % instance)
        self.wait_for_invisible('.flatpickr-calendar.open')


class TestNumericalTolerances(PerformQCTestCase):

    def test_absolute_tolerance_status_matches_saved_pass_fail(self):
        """Values in the OK, TOL and ACT bands of an absolute tolerance are shown and saved the same way.

        If this fails, a therapist can see OK on screen for a result the server records
        as out of tolerance (or the reverse).
        """
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        tests = [self.make_test(name) for name in ('ok_inside', 'ok_on_border', 'tol_band', 'act_band')]
        self.assign()
        for t in tests:
            self.set_ref_tol(t, ref=10, tol=tol)

        self.load_perform()

        # One input taken through every band shows the status follows the value.
        self.enter_value('act_band', '12.5')
        self.wait_for_status('act_band', 'ACT(2.50)', ACT_CLASS)
        self.enter_value('act_band', '11.5')
        self.wait_for_status('act_band', 'TOL(1.50)', TOL_CLASS)
        self.enter_value('act_band', '10.5')
        self.wait_for_status('act_band', 'OK(0.50)', OK_CLASS)

        entered = {
            'ok_inside': ('9.5', 'OK(-0.50)', OK_CLASS),
            'ok_on_border': ('11', 'OK(1.00)', OK_CLASS),  # exactly on tol_high is still OK
            'tol_band': ('8.5', 'TOL(-1.50)', TOL_CLASS),
            'act_band': ('7.5', 'ACT(-2.50)', ACT_CLASS),
        }
        for slug, (value, text, colour) in entered.items():
            self.enter_value(slug, value)
            self.wait_for_status(slug, text, colour)

        self.submit()

        for t in tests:
            value, text, _ = entered[t.slug]
            ti = self.saved(t)
            assert ti.value == float(value)
            assert ti.pass_fail == DISPLAYED_TO_PASS_FAIL[text.split('(')[0]], t.slug

    def test_percent_tolerance_status_matches_saved_pass_fail(self):
        """Values in each band of a percent tolerance are shown and saved the same way.

        If this fails, the percent difference qa.js shows (and colours) disagrees with the
        pass/fail the server stores.
        """
        tol = utils.create_tolerance(tol_type=models.PERCENT, act_low=-5, tol_low=-1, tol_high=1, act_high=5)
        entered = {
            'pct_ok': ('201', 'OK(0.5%)', OK_CLASS),
            'pct_tol': ('204', 'TOL(2.0%)', TOL_CLASS),
            'pct_on_act_border': ('190', 'TOL(-5.0%)', TOL_CLASS),  # exactly on act_low is still TOL
            'pct_act': ('212', 'ACT(6.0%)', ACT_CLASS),
        }
        tests = [self.make_test(slug) for slug in entered]
        self.assign()
        for t in tests:
            self.set_ref_tol(t, ref=200, tol=tol)

        self.load_perform()
        for slug, (value, text, colour) in entered.items():
            self.enter_value(slug, value)
            self.wait_for_status(slug, text, colour)

        self.submit()

        for t in tests:
            value, text, _ = entered[t.slug]
            ti = self.saved(t)
            assert ti.value == float(value)
            assert ti.pass_fail == DISPLAYED_TO_PASS_FAIL[text.split('(')[0]], t.slug

    def test_wraparound_status_uses_distance_across_the_wrap_point(self):
        """A wraparound reading just below the wrap point is close to a reference just above it.

        With a 0-360 wrap and a reference of 0, 359.5 is only 0.5 away. If this fails, a
        gantry or collimator angle near 0/360 shows as a huge difference (or the browser
        and server disagree about it).
        """
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        entered = {
            'wrap_ok': ('359.5', 'OK(-0.50)', OK_CLASS),
            'wrap_tol': ('358.5', 'TOL(-1.50)', TOL_CLASS),
            'wrap_act': ('357', 'ACT(-3.00)', ACT_CLASS),
            'wrap_tol_above': ('1.5', 'TOL(1.50)', TOL_CLASS),
        }
        tests = [self.make_test(slug, test_type=models.WRAPAROUND, wrap_low=0, wrap_high=360) for slug in entered]
        self.assign()
        for t in tests:
            self.set_ref_tol(t, ref=0, tol=tol)

        self.load_perform()
        for slug, (value, text, colour) in entered.items():
            self.enter_value(slug, value)
            self.wait_for_status(slug, text, colour)

        self.submit()

        for t in tests:
            value, text, _ = entered[t.slug]
            ti = self.saved(t)
            assert ti.value == float(value)
            assert ti.pass_fail == DISPLAYED_TO_PASS_FAIL[text.split('(')[0]], t.slug


class TestChoiceTolerances(PerformQCTestCase):

    def test_boolean_status_and_warning_only_tolerance(self):
        """A boolean answer that differs from its reference is ACT, or TOL with a warning-only tolerance.

        If this fails, a failed yes/no check (an interlock, say) is shown or saved with the
        wrong severity.
        """
        warn_only = models.Tolerance.objects.create(
            type=models.BOOLEAN, bool_warning_only=True, created_by=self.user, modified_by=self.user
        )
        bool_ok = self.make_test('bool_ok', test_type=models.BOOLEAN)
        bool_act = self.make_test('bool_act', test_type=models.BOOLEAN)
        bool_warn = self.make_test('bool_warn', test_type=models.BOOLEAN)
        self.assign()
        self.set_ref_tol(bool_ok, ref=1)
        self.set_ref_tol(bool_act, ref=1)
        self.set_ref_tol(bool_warn, ref=1, tol=warn_only)

        self.load_perform()

        def answer(slug, value):
            self.driver.find_element(By.CSS_SELECTOR, '#%s-value input[value="%d"]' % (slug, value)).click()

        # The status follows the answer both ways.
        answer('bool_act', 1)
        self.wait_for_status('bool_act', 'OK', OK_CLASS)
        answer('bool_act', 0)
        self.wait_for_status('bool_act', 'ACT', ACT_CLASS)

        answer('bool_ok', 1)
        self.wait_for_status('bool_ok', 'OK', OK_CLASS)
        answer('bool_warn', 0)
        self.wait_for_status('bool_warn', 'TOL', TOL_CLASS)

        self.submit()

        assert (self.saved(bool_ok).value, self.saved(bool_ok).pass_fail) == (1, models.OK)
        assert (self.saved(bool_act).value, self.saved(bool_act).pass_fail) == (0, models.ACTION)
        assert (self.saved(bool_warn).value, self.saved(bool_warn).pass_fail) == (0, models.TOLERANCE)

    def test_multiple_choice_tolerance_status_matches_saved_pass_fail(self):
        """Pass, tolerance and other choices of a multiple choice test show OK, TOL and ACT, and save so.

        If this fails, choosing e.g. 'Poor' could be shown as acceptable on screen.
        """
        tol = utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='Good', mc_tol_choices='Fair')
        chosen = {
            'mc_ok': ('Good', 'OK', OK_CLASS),
            'mc_tol': ('Fair', 'TOL', TOL_CLASS),
            'mc_act': ('Poor', 'ACT', ACT_CLASS),
        }
        tests = [self.make_test(slug, test_type=models.MULTIPLE_CHOICE, choices='Good,Fair,Poor') for slug in chosen]
        self.assign()
        for t in tests:
            self.set_ref_tol(t, tol=tol)

        self.load_perform()
        for slug, (choice, text, colour) in chosen.items():
            self.choose(slug, choice)
            self.wait_for_status(slug, text, colour)

        self.submit()

        for t in tests:
            choice, text, _ = chosen[t.slug]
            ti = self.saved(t)
            assert ti.string_value == choice
            assert ti.pass_fail == DISPLAYED_TO_PASS_FAIL[text], t.slug

    def test_string_status_shown_matches_saved_when_case_differs(self):
        """A string answer differing from the tolerance's pass choice only in case is shown as it is saved.

        The tolerance passes 'pass'. A typed 'PASS' and a choice 'Pass' are saved as OK by the
        server, but the browser shows them as ACT. Whichever side is changed, the therapist must
        see the status that gets recorded.
        """
        tol = utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='pass', mc_tol_choices='')
        str_exact = self.make_test('str_exact', test_type=models.STRING)
        str_case = self.make_test('str_case', test_type=models.STRING)
        mc_case = self.make_test('mc_case', test_type=models.MULTIPLE_CHOICE, choices='Pass,Fail')
        self.assign()
        for t in (str_exact, str_case, mc_case):
            self.set_ref_tol(t, tol=tol)

        self.load_perform()
        self.enter_value('str_exact', 'pass')
        self.enter_value('str_case', 'PASS')
        self.choose('mc_case', 'Pass')

        # Control: an exact match works, so a failure below is the case handling and not the test.
        try:
            self.wait_for_status('str_exact', 'OK', OK_CLASS)
        except AssertionError as e:
            pytest.fail('control check failed: %s' % e)
        self.wait_until(lambda: self.status_text('str_case') != 'Not Done' and self.status_text('mc_case') != 'Not Done')
        shown = {slug: self.status_text(slug) for slug in ('str_case', 'mc_case')}

        self.submit()

        if self.saved(str_exact).pass_fail != models.OK:
            pytest.fail('control: exact match "pass" was not saved as OK')
        mismatches = {
            t.slug: 'shown %s, saved %s' % (shown[t.slug], self.saved(t).pass_fail)
            for t in (str_case, mc_case)
            if self.saved(t).pass_fail != DISPLAYED_TO_PASS_FAIL[shown[t.slug]]
        }
        assert mismatches == {}


class TestStatusDisplay(PerformQCTestCase):

    def test_do_not_treat_warning_follows_action_results(self):
        """The test list's 'do not treat' warning appears, and Submit turns red, only while a result is at action.

        If this fails, a therapist can submit an out-of-action result without the warning that
        tells them not to treat.
        """
        self.test_list.warning_message = 'Do not treat'
        self.test_list.save()
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        output = self.make_test('output')
        self.assign()
        self.set_ref_tol(output, ref=100, tol=tol)

        self.load_perform()
        self.wait_for_invisible('.do-not-treat')

        def submit_is(colour):
            classes = self.driver.find_element(By.ID, 'submit-qa').get_attribute('class').split()
            other = 'btn-primary' if colour == 'btn-danger' else 'btn-danger'
            return colour in classes and other not in classes

        self.enter_value('output', '101.5')
        self.wait_for_status('output', 'TOL(1.50)', TOL_CLASS)
        assert not any(e.is_displayed() for e in self.driver.find_elements(By.CSS_SELECTOR, '.do-not-treat'))

        self.enter_value('output', '103')
        self.wait_for_status('output', 'ACT(3.00)', ACT_CLASS)
        self.wait_for_visible('.box-header .do-not-treat')
        assert 'Do not treat' in self.driver.find_element(By.CSS_SELECTOR, '.box-header .do-not-treat').text
        self.wait_until(lambda: submit_is('btn-danger'), message='submit button never turned red')

        self.enter_value('output', '100')
        self.wait_for_status('output', 'OK(0.00)', OK_CLASS)
        self.wait_for_invisible('.do-not-treat')
        self.wait_until(lambda: submit_is('btn-primary'), message='submit button never turned back')

    def test_pass_fail_only_user_does_not_see_tolerance_detail(self):
        """A user without 'can view ref/tol' sees only OK or Fail, with no reference column.

        TOL is shown as OK and ACT as Fail, but the server must still record the real status.
        If this fails, either such users see detail they should not, or hiding it changes
        what is saved.
        """
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        entered = {
            'pf_ok': ('10.5', 'OK', OK_CLASS, models.OK),
            'pf_tol': ('11.5', 'OK', OK_CLASS, models.TOLERANCE),
            'pf_act': ('12.5', 'Fail', ACT_CLASS, models.ACTION),
        }
        tests = [self.make_test(slug) for slug in entered]
        self.assign()
        for t in tests:
            self.set_ref_tol(t, ref=10, tol=tol)
        therapist = self.make_limited_user()

        self.load_perform(user=therapist)
        assert self.driver.find_elements(By.CSS_SELECTOR, '#perform-qa-table .qa-reference') == []
        assert 'Reference' not in self.driver.find_element(By.CSS_SELECTOR, '#perform-qa-table thead').text

        for slug, (value, text, colour, _) in entered.items():
            self.enter_value(slug, value)
            self.wait_for_status(slug, text, colour)

        self.submit()

        for t in tests:
            ti = self.saved(t)
            assert ti.value == float(entered[t.slug][0])
            assert ti.pass_fail == entered[t.slug][3], t.slug

    def test_do_not_treat_warning_shown_when_editing_a_session_already_at_action(self):
        """Opening a saved session with an action-level result shows the warning and a red Submit at once.

        If this fails, someone editing or continuing such a session sees no warning
        until they happen to change a value.
        """
        self.test_list.warning_message = 'Do not treat'
        self.test_list.save()
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        output = self.make_test('output')
        self.assign()
        self.set_ref_tol(output, ref=100, tol=tol)
        tli = self.make_session([(output, 103.0)])

        self.load_perform(url=reverse('edit_tli', kwargs={'pk': tli.pk}))
        self.wait_for_status('output', 'ACT(3.00)', ACT_CLASS)
        self.wait_for_visible('.box-header .do-not-treat')
        assert 'btn-danger' in self.driver.find_element(By.ID, 'submit-qa').get_attribute('class').split()

    def test_pass_fail_only_user_sees_no_tolerance_detail_on_a_continued_session(self):
        """A session reopened by a user without 'can view ref/tol' shows OK or Fail, not TOL(1.50).

        If this fails, such users see the detail hidden from them whenever they
        continue or edit a session.
        """
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        within, tolerance = self.make_test('within'), self.make_test('tolerance')
        self.assign()
        for t in (within, tolerance):
            self.set_ref_tol(t, ref=10, tol=tol)
        therapist = self.make_limited_user()
        tli = self.make_session([(within, 10.5), (tolerance, None)], in_progress=True)
        tli.created_by = therapist
        tli.save()

        self.load_perform(url=reverse('continue_tli', kwargs={'pk': tli.pk}), user=therapist)
        self.wait_for_status('within', 'OK', OK_CLASS)
        self.wait_for_status('tolerance', 'Not Done')
        self.enter_value('tolerance', '11.5')
        self.wait_for_status('tolerance', 'OK', OK_CLASS)

    def test_clearing_a_value_shows_not_done_for_a_pass_fail_only_user(self):
        """Typing a value and then clearing it shows Not Done again, and other untouched tests stay Not Done.

        If this fails, a pass/fail-only user sees "OK" on tests nobody has done.
        """
        tol = utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='yes', mc_tol_choices='')
        answer = self.make_test('answer', test_type=models.STRING)
        untouched = self.make_test('untouched', test_type=models.STRING)
        self.assign()
        for t in (answer, untouched):
            self.set_ref_tol(t, tol=tol)
        therapist = self.make_limited_user()

        self.load_perform(user=therapist)
        self.enter_value('answer', 'yes')
        self.wait_for_status('answer', 'OK', OK_CLASS)
        self.value_input('answer').clear()
        self.value_input('answer').send_keys(Keys.TAB)
        self.wait_for_status('answer', 'Not Done')
        self.enter_value('untouched', 'no')
        self.value_input('untouched').clear()
        self.value_input('untouched').send_keys(Keys.TAB)
        self.wait_for_status('untouched', 'Not Done')
        assert self.status_text('answer') == 'Not Done'


class TestSkipping(PerformQCTestCase):

    def test_skipped_test_requires_comment(self):
        """Skipping opens the comment box, and a skip without a comment is sent back with an error.

        Applies to users without 'can skip without comment'. If this fails, tests can be
        skipped with no explanation for the reviewer.
        """
        flatness = self.make_test('flatness')
        self.assign()
        therapist = self.make_limited_user()

        self.load_perform(user=therapist)
        comment_box = self.driver.find_element(By.CSS_SELECTOR, '#flatness-comment textarea')
        assert not comment_box.is_displayed()

        self.driver.find_element(By.CSS_SELECTOR, '#flatness-skip input[type=checkbox]').click()
        self.wait_for_visible('#flatness-comment textarea')

        self.submit()
        self.wait_for_text('#perform-qa-table .qa-error-text', 'Please add comment when skipping')
        assert models.TestListInstance.objects.count() == 0

        # The re-rendered page keeps the skip ticked, with its comment box open
        # (see test_comment_box_open_when_skip_sent_back below).
        assert self.driver.find_element(By.CSS_SELECTOR, '#flatness-skip input[type=checkbox]').is_selected()
        self.wait_for_visible('#flatness-comment textarea').send_keys('Chamber out for calibration')
        self.submit()

        ti = self.saved(flatness)
        assert ti.skipped
        assert ti.value is None
        assert ti.comment == 'Chamber out for calibration'
        assert ti.pass_fail == models.NOT_DONE

    def test_comment_box_open_when_skip_sent_back(self):
        """When a skip is sent back for a missing comment, its comment box is already open.

        The error says 'Please add comment when skipping'; the box to do that in should be
        open, as it is when the user ticks Skip. If this fails, the user has to find the
        comment icon themselves.
        """
        self.make_test('flatness')
        self.assign()
        therapist = self.make_limited_user()

        self.load_perform(user=therapist)
        self.driver.find_element(By.CSS_SELECTOR, '#flatness-skip input[type=checkbox]').click()
        self.wait_for_visible('#flatness-comment textarea')
        self.submit()
        self.wait_for_text('#perform-qa-table .qa-error-text', 'Please add comment when skipping')
        self.wait_for_idle()

        if not self.driver.find_element(By.CSS_SELECTOR, '#flatness-skip input[type=checkbox]').is_selected():
            pytest.fail('the re-rendered page lost the ticked skip, so this test proves nothing')
        assert self.driver.find_element(By.CSS_SELECTOR, '#flatness-comment textarea').is_displayed()

    def test_entering_a_value_clears_skip(self):
        """Typing a value into a skipped test un-ticks Skip, so the value is saved rather than rejected.

        If this fails, the user gets a 'Clear value if skipping' error for something they
        plainly meant to perform.
        """
        symmetry = self.make_test('symmetry')
        self.assign()

        self.load_perform()
        skip = self.driver.find_element(By.CSS_SELECTOR, '#symmetry-skip input[type=checkbox]')
        skip.click()
        self.wait_until(skip.is_selected)

        self.enter_value('symmetry', '1.2')
        self.wait_until(lambda: not skip.is_selected(), message='skip stayed ticked after entering a value')
        self.submit()

        ti = self.saved(symmetry)
        assert not ti.skipped
        assert ti.value == 1.2


class TestCategoryFilter(PerformQCTestCase):

    def setUp(self):
        super().setUp()
        dosimetry = utils.create_category(name='Dosimetry', slug='dosimetry', description='dose')
        mechanical = utils.create_category(name='Mechanical', slug='mechanical', description='mech')
        self.dose = self.make_test('dose', category=dosimetry)
        self.laser = self.make_test('laser', category=mechanical)
        self.mechanical = mechanical
        self.assign()

    def untick_mechanical(self):
        self.open_sidebar_menu('menu-categories', 'category-list')
        # sidebar.js turns a click anywhere on the row into a click on the iCheck box.
        self.driver.find_element(By.CSS_SELECTOR, '#category-list a:has(#category-%d)' % self.mechanical.pk).click()
        self.wait_for_invisible('#laser-row')

    def test_unticked_category_is_skipped_with_comment(self):
        """Unticking a category hides its tests and saves them as skipped, 'Category not performed'.

        If this fails, a partial session either cannot be submitted or is saved without
        recording why tests were left out.
        """
        self.load_perform()
        self.untick_mechanical()

        assert self.driver.find_element(By.CSS_SELECTOR, '#laser-skip input[type=checkbox]').is_selected()
        assert self.driver.find_element(By.CSS_SELECTOR, '#laser-comment textarea').get_attribute(
            'value'
        ) == 'Category not performed'
        assert self.driver.find_element(By.ID, 'dose-row').is_displayed()

        self.enter_value('dose', '1.01')
        self.submit()

        dose, laser = self.saved(self.dose), self.saved(self.laser)
        assert (dose.value, dose.skipped) == (1.01, False)
        assert laser.skipped
        assert laser.value is None
        assert laser.comment == 'Category not performed'
        assert laser.pass_fail == models.NOT_DONE

    def test_value_entered_before_unticking_category_is_dropped(self):
        """A value typed into a test whose category is then unticked does not block submission.

        qa.js keeps the value in case the category is ticked again ('Filtered values will be
        nulled on submit'). If this fails, the user is sent back with 'Clear value if
        skipping' for a test they cannot even see.
        """
        self.load_perform()
        self.enter_value('laser', '0.5')
        self.wait_for_status('laser', 'NO TOL')
        self.untick_mechanical()

        self.enter_value('dose', '1.01')
        self.submit()

        errors = [e.text for e in self.driver.find_elements(By.CSS_SELECTOR, '.qa-error-text')]
        assert models.TestListInstance.objects.count() == 1, 'session rejected: %s' % errors
        laser = self.saved(self.laser)
        assert laser.skipped
        assert laser.value is None
        assert laser.comment == 'Category not performed'


class TestInputHandling(PerformQCTestCase):

    def test_numeric_input_is_cleaned(self):
        """What is left in a numeric field after typing is exactly the number that is judged and saved.

        qa.js completes a leading '.' to '0.' (qautils.js clean_numerical_value). Letters and a
        second decimal point never reach qa.js in Chromium: the number input drops them as they
        are typed, so the two-dot check in qa.js:627-632 cannot be reached this way. A value the
        browser cannot read at all is shown as not done. If this fails, the status could be
        judged on a different number than the one on screen.
        """
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        dose = self.make_test('dose')
        self.assign()
        self.set_ref_tol(dose, ref=0, tol=tol)

        self.load_perform()
        typed = [
            ('.5', '0.5', 'OK(0.50)'),
            ('1.5abc', '1.5', 'TOL(1.50)'),
            ('--1', '', 'Not Done'),
            ('-.5', '-0.5', 'OK(-0.50)'),
        ]
        for keys, field, status in typed:
            self.enter_value('dose', keys)
            self.wait_for_status('dose', status)
            assert self.value_input('dose').get_attribute('value') == field, keys

        self.submit()
        saved = self.saved(dose)
        assert (saved.value, saved.pass_fail) == (-0.5, models.OK)

    def test_composite_error_shows_failed(self):
        """A composite whose calculation raises shows 'Failed' with the error, and recovers when fixed.

        If this fails, a broken calculation could look like a missing or valid result.
        """
        self.make_test('reading')
        ratio = self.make_test('ratio', test_type=models.COMPOSITE, calculation_procedure='result = 10 / reading')
        self.assign()

        self.load_perform()
        self.enter_value('reading', '0')
        self.wait_for_status('ratio', 'Failed', ACT_CLASS)
        assert 'ZeroDivisionError' in self.status_cell('ratio').get_attribute('title')

        self.enter_value('reading', '4')
        self.wait_for_status('ratio', 'NO TOL')
        assert float(self.value_input('ratio').get_attribute('value')) == 2.5

        self.submit()
        assert self.saved(ratio).value == 2.5

    def test_formatted_values_save_raw_value(self):
        """A composite or constant with display formatting shows the formatted number but saves the full value.

        If this fails, rounding meant only for display ends up in the clinical record.
        """
        self.make_test('reading')
        third = self.make_test(
            'third', test_type=models.COMPOSITE, calculation_procedure='result = reading / 3', formatting='%.2f'
        )
        pi = self.make_test('pi', test_type=models.CONSTANT, constant_value=3.14159265, formatting='%.1f')
        self.assign()

        self.load_perform()
        assert self.value_input('pi').get_attribute('value') == '3.1'
        self.enter_value('reading', '1')
        self.wait_until(lambda: self.value_input('third').get_attribute('value') == '0.33')
        assert self.value_input('third').get_attribute('title') == 'Actual value = %r' % (1 / 3)

        self.submit()
        assert self.saved(third).value == pytest.approx(1 / 3, rel=1e-12)
        assert self.saved(pi).value == 3.14159265

    def test_upload_is_processed_and_saved(self):
        """A file uploaded through the Upload button is processed, feeds composites, and is saved.

        If this fails, an uploaded measurement file is lost or its result never reaches
        the tests that depend on it.
        """
        self.use_temporary_media_root()
        upload = self.make_test('profile', test_type=models.UPLOAD, calculation_procedure='result = float(FILE.read())')
        doubled = self.make_test('doubled', test_type=models.COMPOSITE, calculation_procedure='result = profile * 2')
        self.assign()
        path = self.make_file('profile.txt', '21\n')

        self.load_perform()
        self.driver.find_element(By.CSS_SELECTOR, 'input.dz-hidden-input').send_keys(path)
        self.wait_for_status('profile', 'Success', OK_CLASS)
        self.wait_until(lambda: self.value_input('doubled').get_attribute('value') not in ('', None))
        assert float(self.value_input('doubled').get_attribute('value')) == 42

        self.submit()

        ti = self.saved(upload)
        assert ti.json_value == 21
        attachment = ti.attachment_set.get()
        assert attachment.label == 'profile.txt'
        assert self.saved(doubled).value == 42

    def test_enter_moves_to_next_input_without_submitting(self):
        """Pressing Enter in a value moves to the next test instead of submitting the form.

        If this fails, a habitual Enter submits a half-finished session.
        """
        for name in ('first', 'second', 'third'):
            self.make_test(name)
        self.assign()

        self.load_perform()
        first = self.value_input('first')
        first.click()
        first.send_keys('1', Keys.ENTER)
        self.wait_until(lambda: self.driver.switch_to.active_element == self.value_input('second'))
        self.driver.switch_to.active_element.send_keys('2', Keys.ENTER)
        self.wait_until(lambda: self.driver.switch_to.active_element == self.value_input('third'))

        self.wait_for_status('first', 'NO TOL')
        assert self.driver.current_url.endswith(self.url)
        assert models.TestListInstance.objects.count() == 0

    def test_leave_page_warning_after_value_entered(self):
        """Leaving the page asks for confirmation once a value has been entered, and not before.

        If this fails, a stray Back or link click silently throws away entered results.
        """
        self.make_test('dose')
        self.assign()
        trigger = (
            "var e = jQuery.Event('beforeunload'); jQuery(window).trigger(e);"
            "return e.result === undefined ? null : e.result;"
        )

        self.load_perform()
        assert self.driver.execute_script(trigger) is None

        self.enter_value('dose', '1')
        self.wait_for_status('dose', 'NO TOL')
        assert 'lose all entered values' in self.driver.execute_script(trigger)

    def test_session_attachment_is_saved(self):
        """A file chosen in the test list Attachments box is listed on the page and saved with the session.

        If this fails, supporting files (screenshots, exports) silently go missing.
        """
        self.use_temporary_media_root()
        self.make_test('dose')
        self.assign()
        path = self.make_file('linac-log.txt', 'all good\n')

        self.load_perform()
        self.driver.find_element(By.ID, 'id_tli_attachments').send_keys(path)
        self.wait_for_text('#tli-attachment-names', 'linac-log.txt')
        self.enter_value('dose', '1')
        self.submit()

        tli = models.TestListInstance.objects.get()
        attachment = tli.attachment_set.get()
        assert attachment.label == 'linac-log.txt'


class TestExistingSessions(PerformQCTestCase):

    def setUp(self):
        super().setUp()
        tol = utils.create_tolerance(tol_type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        self.output = self.make_test('output')
        self.energy = self.make_test('energy')
        self.assign()
        self.set_ref_tol(self.output, ref=100, tol=tol)
        self.set_ref_tol(self.energy, ref=100, tol=tol)

    def test_edit_session_repopulates_and_updates(self):
        """Editing a session shows its saved values and statuses, and saving updates the same records.

        If this fails, a correction made while editing is lost, duplicated, or judged
        against the wrong status.
        """
        tli = self.make_session([(self.output, 103.0), (self.energy, 100.5)])
        output_pk = self.saved(self.output).pk

        self.load_perform(url=reverse('edit_tli', kwargs={'pk': tli.pk}))
        assert float(self.value_input('output').get_attribute('value')) == 103
        self.wait_for_status('output', 'ACT(3.00)', ACT_CLASS)
        self.wait_for_status('energy', 'OK(0.50)', OK_CLASS)

        self.enter_value('output', '100.8')
        self.wait_for_status('output', 'OK(0.80)', OK_CLASS)
        self.submit()

        assert models.TestListInstance.objects.count() == 1
        output = self.saved(self.output)
        assert output.pk == output_pk
        assert (output.value, output.pass_fail) == (100.8, models.OK)
        assert self.saved(self.energy).value == 100.5

    def test_continue_in_progress_session(self):
        """Continuing an in-progress session keeps its values and completes it when submitted.

        If this fails, work saved as 'in progress' cannot be finished, or finishing it loses
        what was already entered.
        """
        tli = self.make_session([(self.output, 101.5), (self.energy, None)], in_progress=True)

        self.load_perform(url=reverse('continue_tli', kwargs={'pk': tli.pk}))
        self.wait_for_status('output', 'TOL(1.50)', TOL_CLASS)
        self.wait_for_status('energy', 'Not Done')

        self.enter_value('energy', '99.5')
        self.wait_for_status('energy', 'OK(-0.50)', OK_CLASS)
        self.submit()

        tli.refresh_from_db()
        assert not tli.in_progress
        assert (self.saved(self.output).value, self.saved(self.output).pass_fail) == (101.5, models.TOLERANCE)
        assert (self.saved(self.energy).value, self.saved(self.energy).pass_fail) == (99.5, models.OK)


class TestCycles(PerformQCTestCase):

    def test_cycle_day_selector_switches_test_list(self):
        """Choosing another day of a cycle loads that day's test list, and the session is saved against it.

        If this fails, the wrong day's tests are performed or recorded.
        """
        monday = utils.create_test_list('Monday')
        tuesday = utils.create_test_list('Tuesday')
        utils.create_test_list_membership(monday, utils.create_test('monday_output'))
        tuesday_test = utils.create_test('tuesday_lasers')
        utils.create_test_list_membership(tuesday, tuesday_test)
        cycle = utils.create_cycle([monday, tuesday], name='Weekly cycle')
        self.assign(test_list=cycle)

        self.load_perform()
        assert self.driver.find_elements(By.ID, 'monday_output-row')
        assert not self.driver.find_elements(By.ID, 'tuesday_lasers-row')

        self.open_sidebar_menu('menu-days', 'days-list')
        with self.wait_for_page_load():
            self.driver.find_element(By.CSS_SELECTOR, '#days-list a:has(#day-2)').click()
        self.wait_for_element('#perform-qa-table')
        self.wait_for_idle()
        assert 'day=2' in self.driver.current_url
        assert self.driver.find_elements(By.ID, 'tuesday_lasers-row')
        assert not self.driver.find_elements(By.ID, 'monday_output-row')

        self.enter_value('tuesday_lasers', '1')
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert (tli.test_list, tli.day) == (tuesday, 1)
        assert self.saved(tuesday_test).value == 1


class TestWorkTimes(PerformQCTestCase):

    def test_work_completed_cannot_precede_work_started(self):
        """The Work Completed picker refuses a time before Work Started, and accepts a later one.

        If this fails, a session can be recorded as finishing before it started, which
        breaks durations and the order of results in the history.
        """
        self.make_test('dose')
        self.assign()
        started = (timezone.localtime() - timezone.timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)

        self.load_perform()
        self.type_datetime('id_work_started', started.strftime(FLATPICKR_DATETIME))

        # A later time is accepted, and the duration follows it...
        completed = started + timezone.timedelta(minutes=90)
        self.type_datetime('id_work_completed', completed.strftime(FLATPICKR_DATETIME))
        self.wait_until(lambda: self.field('id_work_duration') == '1hr:30min')

        # ...an earlier one is refused (flatpickr's minDate clears it)...
        too_early = (started - timezone.timedelta(days=1)).strftime(FLATPICKR_DATETIME)
        self.type_datetime('id_work_completed', too_early, accepted=False)
        self.wait_until(
            lambda: self.field('id_work_completed') not in (too_early, completed.strftime(FLATPICKR_DATETIME)),
            message='the completed time did not react to typing',
        )
        assert self.field('id_work_completed') == ''

        # ...and the later time can be entered again.
        self.type_datetime('id_work_completed', completed.strftime(FLATPICKR_DATETIME))

        self.enter_value('dose', '1')
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert timezone.localtime(tli.work_started) == started
        assert timezone.localtime(tli.work_completed) == completed


class TestDatesAndTimes(PerformQCTestCase):
    """Dates and times entered on the perform page are saved, and shown again, exactly as chosen.

    The page formats every date in the browser and the server parses it back in
    TIME_ZONE, so a mismatch shifts a result by hours or a day without any error.
    Times late in the evening are used on purpose: in UTC they already fall on
    the next day, so a conversion done in the wrong zone shows up as a wrong date.
    """

    def setUp(self):
        super().setUp()
        self.dose = self.make_test('dose')

    def add_date_tests(self):
        """Add a date test and a date & time test to the list (they are required, so only where used)."""
        self.date_test = self.make_test('date_checked', test_type=models.DATE)
        self.datetime_test = self.make_test('time_checked', test_type=models.DATETIME)

    def test_chosen_date_and_time_are_saved_and_shown_again_on_edit(self):
        """A date and a late-evening time picked last month are saved as picked, and read back the same.

        If this fails, a date result is recorded on the wrong day: off by one when
        the browser and server disagree about the zone, or a month out when the
        calendar's month arrows and the saved value disagree.
        """
        self.add_date_tests()
        self.assign()
        last_month_end = timezone.localdate().replace(day=1) - timezone.timedelta(days=1)
        first_of_last_month = last_month_end.replace(day=1)

        self.load_perform()
        self.enter_value('dose', '1')
        self.pick_in_calendar('date_checked', first_of_last_month)
        self.pick_in_calendar('time_checked', last_month_end, hour=22, minute=35)

        expected_date = first_of_last_month.strftime(FLATPICKR_DATE)
        expected_datetime = '%s 22:35' % last_month_end.strftime('%Y-%m-%d')
        assert self.value_input('date_checked').get_attribute('value') == expected_date
        assert self.value_input('time_checked').get_attribute('value') == expected_datetime
        self.submit()

        assert self.saved(self.date_test).date_value == first_of_last_month
        assert timezone.localtime(self.saved(self.datetime_test).datetime_value) == self.aware(
            last_month_end.year, last_month_end.month, last_month_end.day, 22, 35
        )

        tli = models.TestListInstance.objects.get()
        self.load_perform(url=reverse('edit_tli', kwargs={'pk': tli.pk}))
        assert self.value_input('date_checked').get_attribute('value') == expected_date
        assert self.value_input('time_checked').get_attribute('value') == expected_datetime

    def test_typed_work_times_are_saved_and_shown_again_on_edit(self):
        """Work started and completed late in the evening are saved as typed, and the edit page shows them again.

        If this fails, the session is filed against the wrong day, which moves it in
        the history, the due dates and every report filtered by date.
        """
        self.assign()
        started = (timezone.localtime() - timezone.timedelta(days=2)).replace(hour=22, minute=10, second=0, microsecond=0)
        completed = started + timezone.timedelta(minutes=95)  # 23:45, still the same day locally

        self.load_perform()
        self.enter_value('dose', '1')
        self.type_datetime('id_work_started', started.strftime(FLATPICKR_DATETIME))
        self.type_datetime('id_work_completed', completed.strftime(FLATPICKR_DATETIME))
        self.wait_until(lambda: self.field('id_work_duration') == '1hr:35min')
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert timezone.localtime(tli.work_started) == started
        assert timezone.localtime(tli.work_completed) == completed

        self.load_perform(url=reverse('edit_tli', kwargs={'pk': tli.pk}))
        assert self.field('id_work_started') == started.strftime(FLATPICKR_DATETIME)
        assert self.field('id_work_completed') == completed.strftime(FLATPICKR_DATETIME)
        assert self.field('id_work_duration') == '1hr:35min'

    def test_duration_across_the_autumn_clock_change_is_the_real_time_taken(self):
        """00:30 to 03:30 on the night the clocks go back took four hours, on the page and in the database.

        If this fails, a session that spans the change from daylight saving time is
        shown or recorded an hour short.
        """
        self.assign()
        started = self.aware(2025, 11, 2, 0, 30)  # America/Toronto falls back at 02:00 on 2 Nov 2025
        completed = self.aware(2025, 11, 2, 3, 30)

        self.load_perform()
        self.enter_value('dose', '1')
        self.type_datetime('id_work_started', '2025-11-02 00:30')
        self.type_datetime('id_work_completed', '2025-11-02 03:30')
        self.wait_until(lambda: self.field('id_work_duration') == '4hr:00min',
                        message='duration shows %r' % self.field('id_work_duration'))
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert (tli.work_started, tli.work_completed) == (started, completed)
        assert tli.duration() == timezone.timedelta(hours=4)

    def test_duration_across_the_spring_clock_change_is_the_real_time_taken(self):
        """01:30 to 03:30 on the night the clocks go forward took one hour, on the page and in the database.

        If this fails, a session that spans the change to daylight saving time is
        shown or recorded an hour long.
        """
        self.assign()
        self.load_perform()
        self.enter_value('dose', '1')
        self.type_datetime('id_work_started', '2026-03-08 01:30')  # America/Toronto springs forward at 02:00
        self.type_datetime('id_work_completed', '2026-03-08 03:30')
        self.wait_until(lambda: self.field('id_work_duration') == '1hr:00min',
                        message='duration shows %r' % self.field('id_work_duration'))
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert tli.duration() == timezone.timedelta(hours=1)

    def test_work_started_defaults_to_now(self):
        """Left alone, Work Started is the time the page was opened, and that is what is saved.

        If this fails, every session performed without touching the times is
        recorded at the wrong time.
        """
        self.assign()
        before = timezone.localtime().replace(second=0, microsecond=0)
        self.load_perform()
        shown = timezone.make_aware(timezone.datetime.strptime(self.field('id_work_started'), FLATPICKR_DATETIME))
        after = timezone.localtime()
        assert before <= shown <= after, 'Work Started shows %s, opened between %s and %s' % (shown, before, after)

        self.enter_value('dose', '1')
        self.submit()
        tli = models.TestListInstance.objects.get()
        assert before <= tli.work_started <= after

    def assert_default_work_started_is_now_from(self, timezone_id):
        self.assign()
        self.use_browser_timezone(timezone_id)
        before = timezone.localtime().replace(second=0, microsecond=0)
        self.load_perform()
        assert self.browser_timezone() == timezone_id
        self.enter_value('dose', '1')
        self.submit()
        after = timezone.localtime()

        tli = models.TestListInstance.objects.get()
        assert before <= tli.work_started <= after, 'saved %s, performed between %s and %s' % (
            timezone.localtime(tli.work_started), before, after
        )

    def test_work_started_defaults_to_now_on_a_workstation_ahead_of_the_server(self):
        """A workstation whose clock is set to a zone ahead of the server's still records the real start time.

        If this fails, sessions performed from a computer set to another zone (a
        laptop brought back from travel, a remote reviewer) are recorded hours off.
        """
        self.assert_default_work_started_is_now_from('Asia/Tokyo')

    def test_work_started_defaults_to_now_on_a_workstation_behind_the_server(self):
        """A workstation whose clock is set to a zone behind the server's still records the real start time.

        The start picker refuses times after the browser's "now", so a browser
        behind the server could reject the server's default and put its own clock in.
        """
        self.assert_default_work_started_is_now_from('America/Vancouver')

    def test_autosaved_dates_and_times_are_restored_exactly(self):
        """A date result, a time result and the work times come back unchanged when an autosave is reopened.

        If this fails, resuming interrupted QC silently changes the dates that were
        already entered.
        """
        self.add_date_tests()
        self.assign()
        day = timezone.localdate().replace(day=1)
        started = (timezone.localtime() - timezone.timedelta(days=1)).replace(hour=22, minute=5, second=0, microsecond=0)

        self.load_perform()
        self.type_datetime('id_work_started', started.strftime(FLATPICKR_DATETIME))
        self.enter_value('dose', '1')
        self.pick_in_calendar('date_checked', day)
        self.pick_in_calendar('time_checked', day, hour=23, minute=50)
        expected = {
            'date_checked': day.strftime(FLATPICKR_DATE),
            'time_checked': '%s 23:50' % day.strftime('%Y-%m-%d'),
        }

        # Autosave is debounced by four seconds after the last change.
        self.wait_until(
            lambda: any(a.data['tests'].get('time_checked') for a in models.AutoSave.objects.all()),
            timeout=self.timeout + 10, message='the time result was never autosaved',
        )
        self.wait_for_idle()
        autosave = models.AutoSave.objects.get()

        self.open(self.url + '?autosave_id=%d' % autosave.pk)
        self.wait_for_element('#perform-qa-table')
        self.wait_for_idle()
        for slug, text in expected.items():
            self.wait_until(lambda: self.value_input(slug).get_attribute('value') == text,
                            message='%s shows %r, not %r' % (slug, self.value_input(slug).get_attribute('value'), text))
        assert self.field('id_work_started') == started.strftime(FLATPICKR_DATETIME)


class TestDatesAndTimesInFrench(PerformQCTestCase):
    """The same date entry, with the user's language set to French.

    French has its own date input formats (formats/fr/formats.py, day/month/year),
    while the calendars write the same English formats in every language. A
    French user must still be able to submit, and see their dates again.
    """

    def setUp(self):
        super().setUp()
        self.dose = self.make_test('dose')
        self.date_test = self.make_test('date_checked', test_type=models.DATE)
        self.datetime_test = self.make_test('time_checked', test_type=models.DATETIME)
        self.assign()

    def switch_to_french(self):
        self.driver.add_cookie({'name': settings.LANGUAGE_COOKIE_NAME, 'value': 'fr'})

    def test_french_user_saves_dates_and_work_times_and_sees_them_again(self):
        """In French, a date, a date & time and the work times are saved as entered and shown again on edit.

        If this fails, French-speaking staff cannot submit QC containing a date, or
        their dates change when the session is edited.
        """
        day = timezone.localdate().replace(day=1)
        started = (timezone.localtime() - timezone.timedelta(days=1)).replace(hour=21, minute=40, second=0, microsecond=0)

        self.login()
        self.switch_to_french()
        self.load_perform()
        assert self.driver.find_element(By.TAG_NAME, 'html').get_attribute('lang').startswith('fr')

        self.type_datetime('id_work_started', started.strftime('%Y-%m-%d %H:%M'))
        self.enter_value('dose', '1')
        self.pick_in_calendar('date_checked', day)
        self.pick_in_calendar('time_checked', day, hour=23, minute=15)
        self.submit()

        tli = models.TestListInstance.objects.get()
        assert timezone.localtime(tli.work_started) == started
        assert self.saved(self.date_test).date_value == day
        assert timezone.localtime(self.saved(self.datetime_test).datetime_value) == timezone.make_aware(
            timezone.datetime(day.year, day.month, day.day, 23, 15)
        )

        self.open(reverse('edit_tli', kwargs={'pk': tli.pk}))
        self.wait_for_element('#perform-qa-table')
        self.wait_for_idle()
        assert self.value_input('date_checked').get_attribute('value') == day.strftime('%d %b %Y')
        assert self.value_input('time_checked').get_attribute('value') == '%s 23:15' % day.strftime('%Y-%m-%d')
        assert self.driver.find_element(By.ID, 'id_work_started').get_attribute('value') == started.strftime(
            '%Y-%m-%d %H:%M'
        )
