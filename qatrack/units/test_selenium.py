"""Browser tests for changing unit available time (qatrack/units).

The "Change Unit Available Times" page is drawn almost entirely in the browser
(units/js/unit_available_time.js): a d3 calendar of six weeks, one bar per
selected unit per day, a felter list for choosing units, and three modal
windows that post to the server by ajax. Which days and units a change applies
to is decided by clicks on the calendar, so a Django test client cannot reach
any of it. These tests click like a user would and then check what was saved.

Available time feeds the downtime and utilisation figures in service-log
reports, so a change saved against the wrong day or the wrong unit quietly
skews those figures. That is what most of these tests guard against.

The page sends each day as a timestamp at the browser's midnight and the
server turns it back into a date, so the browser's time zone matters here. The
harness starts the browser in TIME_ZONE; these tests also pin it per page
(Chromium only) so one class can put the browser in another zone on purpose.
"""

import calendar
import datetime

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from qatrack.qa.tests import utils as qa_utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.units.models import UnitAvailableTime, UnitAvailableTimeEdit

ACCEPTANCE = datetime.date(2020, 1, 15)

DEFAULT_HOURS = {
    'sunday': datetime.timedelta(0),
    'monday': datetime.timedelta(hours=8),
    'tuesday': datetime.timedelta(hours=8),
    'wednesday': datetime.timedelta(hours=8),
    'thursday': datetime.timedelta(hours=8),
    'friday': datetime.timedelta(hours=8),
    'saturday': datetime.timedelta(0),
}

MINUTES_PER_DAY = 1440


def first_displayed_day(year, month):
    """The Sunday the calendar starts on for `month` (1-12): the 1st, or the Sunday before it."""
    first = datetime.date(year, month, 1)
    return first - datetime.timedelta(days=(first.weekday() + 1) % 7)


def create_schedule(unit, date_changed, **hours):
    """A UnitAvailableTime for `unit` from `date_changed`; `hours` overrides the defaults by weekday name."""
    values = dict(DEFAULT_HOURS, **hours)
    return UnitAvailableTime.objects.create(
        unit=unit,
        date_changed=date_changed,
        **{'hours_%s' % day: duration for day, duration in values.items()},
    )


class UnitAvailableTimeTestCase(SeleniumTestCase):
    """Two active units (Linac A and Linac B) and one inactive one (Old Linac).

    Each was accepted on 15 Jan 2020 and has the default schedule from that
    day (8 hours Monday to Friday, none at the weekend), so every day the
    calendar shows has 8 or 0 hours unless a test changes it.
    """

    timezone_id = settings.TIME_ZONE

    def setUp(self):
        super().setUp()
        self.unit_a = qa_utils.create_unit(name='Linac A')
        self.unit_b = qa_utils.create_unit(name='Linac B')
        self.old_unit = qa_utils.create_unit(name='Old Linac', active=False)
        for unit in (self.unit_a, self.unit_b, self.old_unit):
            unit.date_acceptance = ACCEPTANCE
            unit.save()
            create_schedule(unit, ACCEPTANCE)

    # -- the browser's clock -----------------------------------------------------------------------

    def browser_today(self):
        """Today's date as the page sees it."""
        y, m, d = self.driver.execute_script(
            'var d = new Date(); return [d.getFullYear(), d.getMonth() + 1, d.getDate()];'
        )
        return datetime.date(y, m, d)

    # -- loading the page --------------------------------------------------------------------------

    def load_page(self, timezone_id=None):
        """Log in and open the page with the calendar fully drawn.

        The calendar draws its day rectangles only on the second pass, after
        the unit data has arrived, so 42 of them (six weeks) means it is ready.
        """
        self.use_browser_timezone(timezone_id or self.timezone_id)
        self.login()
        self.open(reverse('unit_available_time'))
        self.wait_until(lambda: len(self.driver.find_elements(By.CSS_SELECTOR, 'rect.day-rect')) == 42)
        self.wait_until_idle()
        today = self.browser_today()
        self.shown_month = (today.year, today.month)

    def wait_until_idle(self):
        """No ajax in flight and the calendar has finished redrawing (it marks <body> while it works)."""
        self.wait_for_ajax()
        self.wait_until(lambda: 'loading' not in self.driver.find_element(By.TAG_NAME, 'body').get_attribute('class'))

    # -- the calendar ------------------------------------------------------------------------------

    def cell_date(self, x, y):
        """The date drawn in column `x` (0 = Sunday), row `y` of the calendar for the month shown."""
        start = first_displayed_day(*self.shown_month)
        return start + datetime.timedelta(days=7 * y + x)

    def day_rect(self, x, y):
        return self.driver.find_element(By.CSS_SELECTOR, '#day-%d_%d rect.day-rect' % (x, y))

    def click_day(self, x, y, key=None):
        """Click a day like a user would, holding `key` (Keys.CONTROL or Keys.SHIFT) if given.

        The click lands near the right-hand edge of the day, halfway down. Bars
        are drawn over the middle of the day and labels over its top left, and
        neither passes clicks through to the day underneath.
        """
        rect = self.day_rect(x, y)
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", rect)
        width = rect.size['width']
        chain = ActionChains(self.driver)
        if key:
            chain.key_down(key)
        chain.move_to_element_with_offset(rect, int(width / 2) - 4, 0).click()
        if key:
            chain.key_up(key)
        chain.perform()

    def selected_cells(self):
        """(x, y) of every day drawn as selected."""
        cells = set()
        for el in self.driver.find_elements(By.CSS_SELECTOR, 'g.day-g.selected-day'):
            x, y = el.get_attribute('id')[len('day-'):].split('_')
            cells.add((int(x), int(y)))
        return cells

    def wait_for_selected_cells(self, expected):
        expected = set(expected)
        try:
            self.wait_until(lambda: self.selected_cells() == expected)
        except Exception:
            self.assertEqual(self.selected_cells(), expected)
            raise

    def cell_labels(self, x, y):
        """The edit labels drawn on a day, without the leading dash, ignoring any on their way out."""
        labels = []
        for el in self.driver.find_elements(By.CSS_SELECTOR, '#day-%d_%d text.day-label' % (x, y)):
            opacity = el.value_of_css_property('opacity')
            if opacity and float(opacity) < 0.5:
                continue
            labels.append(el.text.lstrip('- '))
        return labels

    def bar_heights(self, x, y):
        """The height of each bar in a day, as drawn (excluding bars being removed)."""
        try:
            return [
                float(el.get_attribute('height'))
                for el in self.driver.find_elements(By.CSS_SELECTOR, '#day-%d_%d rect.bar-rect:not(.exit)' % (x, y))
            ]
        except StaleElementReferenceException:
            return None

    def expected_bar_height(self, minutes):
        day_height = float(self.day_rect(0, 0).get_attribute('height'))
        return day_height * minutes / MINUTES_PER_DAY

    def wait_for_bar_heights(self, x, y, minutes):
        """Wait until day (x, y) shows one bar per entry of `minutes`, each that tall."""
        expected = [self.expected_bar_height(m) for m in minutes]

        def matches():
            heights = self.bar_heights(x, y)
            return heights is not None and len(heights) == len(expected) and all(
                abs(h - e) < 0.5 for h, e in zip(sorted(heights), sorted(expected))
            )

        try:
            self.wait_until(matches)
        except Exception:
            self.assertEqual(self.bar_heights(x, y), expected)
            raise

    # -- units and buttons -------------------------------------------------------------------------

    def unit_option(self, unit):
        return self.driver.find_element(By.ID, 'felter-option-div-%d' % unit.pk)

    def toggle_unit(self, unit):
        """Click a unit in the Serviceable Units list (selects it, or deselects it if selected)."""
        option = self.unit_option(unit)
        was_selected = 'felter-selected' in option.get_attribute('class')
        option.click()
        self.wait_until(lambda: ('felter-selected' in self.unit_option(unit).get_attribute('class')) != was_selected)
        self.wait_until_idle()

    def button_enabled(self, el_id):
        return self.driver.find_element(By.ID, el_id).is_enabled()

    def action_buttons_enabled(self):
        return [self.button_enabled(b) for b in ('open_edit_modal', 'open_uat_modal', 'open_delete_modal')]

    def open_modal(self, button_id, modal_id):
        self.driver.find_element(By.ID, button_id).click()
        self.wait_for_visible('#%s' % modal_id)
        # Bootstrap fades the window in; typing before it settles can lose keys.
        self.wait_until(lambda: 'in' in self.driver.find_element(By.ID, modal_id).get_attribute('class').split())

    def type_into(self, el_id, text):
        element = self.wait_for_visible('#%s' % el_id)
        element.click()
        element.send_keys(Keys.CONTROL, 'a')
        element.send_keys(Keys.DELETE)
        element.send_keys(text)

    def value_of(self, el_id):
        return self.driver.execute_script('return $(document.getElementById(arguments[0])).val();', el_id)

    def choose_select2(self, el_id, text):
        """Pick `text` in the select2 widget for <select id=el_id>, through its own drop-down."""
        self.driver.find_element(By.CSS_SELECTOR, '#select2-%s-container' % el_id).click()
        self.wait_for_visible('.select2-results__option')
        for option in self.driver.find_elements(By.CSS_SELECTOR, '.select2-results__option'):
            if option.text == text:
                option.click()
                break
        else:
            raise AssertionError('%r is not offered in #%s' % (text, el_id))
        self.wait_for_invisible('.select2-results__option')
        self.wait_until_idle()

    def current_month_day_numbers(self):
        """The day numbers drawn in the cells the calendar marks as the month being shown."""
        return [
            el.text for el in self.driver.find_elements(By.CSS_SELECTOR, 'g.day-g.current-month text.day-num')
        ]

    def wait_for_month_shown(self, year, month):
        """Wait until the calendar draws `month` (1-12) of `year`, and remember it for cell_date()."""
        self.shown_month = (year, month)
        start = first_displayed_day(year, month)
        n_days = calendar.monthrange(year, month)[1]
        expected = ['%02d' % d for d in range(1, n_days + 1)]

        def drawn():
            try:
                first = self.driver.find_element(By.CSS_SELECTOR, '#day-0_0 text.day-num').text
                return first == '%02d' % start.day and self.current_month_day_numbers() == expected
            except StaleElementReferenceException:
                return False

        try:
            self.wait_until(drawn)
        except Exception:
            self.assertEqual(self.current_month_day_numbers(), expected)
            raise

        self.assertEqual(self.value_of('id_month_select'), str(month - 1))
        self.assertEqual(self.value_of('id_year_select'), str(year))
        self.assertEqual(
            self.driver.find_element(By.ID, 'select2-id_month_select-container').text, calendar.month_name[month]
        )
        self.assertEqual(self.driver.find_element(By.ID, 'select2-id_year_select-container').text, str(year))


class TestCalendarAndSelection(UnitAvailableTimeTestCase):

    def test_page_shows_calendar_for_current_month(self):
        """The calendar opens on this month, six weeks from a Sunday, with nothing selected.

        Fails if the page breaks while loading (a JavaScript error, a failed
        data request) or opens on the wrong month.
        """
        self.load_page()

        headings = [el.text for el in self.driver.find_elements(By.CSS_SELECTOR, 'text.day-heading')]
        self.assertEqual(
            headings, ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        )
        self.wait_for_month_shown(*self.shown_month)
        self.assertEqual(self.selected_cells(), set())
        self.assertEqual(self.action_buttons_enabled(), [False, False, False])
        self.assertEqual(self.javascript_errors(), [])

    def test_action_buttons_need_both_units_and_days(self):
        """Edit, schedule and delete stay disabled until at least one unit AND one day are chosen.

        Fails if a change could be opened with nothing to apply it to, or if
        the buttons never come on.
        """
        self.load_page()

        self.click_day(3, 1)
        self.wait_for_selected_cells({(3, 1)})
        self.assertEqual(self.action_buttons_enabled(), [False, False, False])

        self.toggle_unit(self.unit_a)
        self.wait_until(lambda: self.action_buttons_enabled() == [True, True, True])

        self.toggle_unit(self.unit_a)
        self.wait_until(lambda: self.action_buttons_enabled() == [False, False, False])

        # Select All picks every unit on show; with the day still selected the buttons come back on.
        self.driver.find_element(By.CSS_SELECTOR, '.felter-selectall').click()
        self.wait_until_idle()
        self.assertEqual(self.value_of('units'), [str(self.unit_a.pk), str(self.unit_b.pk)])
        self.assertEqual(self.action_buttons_enabled(), [True, True, True])

        self.driver.find_element(By.CSS_SELECTOR, '.felter-selectnone').click()
        self.wait_until(lambda: self.action_buttons_enabled() == [False, False, False])

    def test_click_selects_only_that_day(self):
        """A plain click selects one day and replaces any earlier selection.

        Fails if a click adds to the selection, so a later change would also
        land on days the user is no longer looking at.
        """
        self.load_page()

        self.click_day(2, 1)
        self.wait_for_selected_cells({(2, 1)})
        self.click_day(5, 2)
        self.wait_for_selected_cells({(5, 2)})
        self.assertEqual(self.value_of('effective_date'), self.cell_date(5, 2).strftime('%d %b %Y'))

    def test_ctrl_click_adds_and_removes_days(self):
        """Ctrl-click adds a day to the selection, and ctrl-clicking a selected day takes it out again."""
        self.load_page()

        self.click_day(1, 1)
        self.click_day(3, 1, key=Keys.CONTROL)
        self.click_day(4, 3, key=Keys.CONTROL)
        self.wait_for_selected_cells({(1, 1), (3, 1), (4, 3)})

        self.click_day(3, 1, key=Keys.CONTROL)
        self.wait_for_selected_cells({(1, 1), (4, 3)})

        # The effective date for a schedule change is the earliest selected day.
        self.assertEqual(self.value_of('effective_date'), self.cell_date(1, 1).strftime('%d %b %Y'))

    def test_shift_click_selects_a_range_of_days(self):
        """Shift-click selects every day from the last clicked day to this one, across weeks and either way."""
        self.load_page()

        self.click_day(4, 1)
        self.click_day(2, 2, key=Keys.SHIFT)
        self.wait_for_selected_cells({(4, 1), (5, 1), (6, 1), (0, 2), (1, 2), (2, 2)})

        # Backwards from the same starting day.
        self.click_day(1, 1, key=Keys.SHIFT)
        self.wait_for_selected_cells({(1, 1), (2, 1), (3, 1), (4, 1)})

        self.toggle_unit(self.unit_a)
        self.open_modal('open_edit_modal', 'available_edits_modal')
        self.wait_for_text('#available_edits_modal .num-days-selected', 'Currently 4 days selected for 1 unit')


class TestMonthNavigation(UnitAvailableTimeTestCase):

    def test_month_and_year_selects_change_month_shown(self):
        """Choosing a month, then a year, redraws the calendar for that month."""
        self.load_page()
        year, month = self.shown_month
        other_month = 2 if month != 2 else 3

        self.choose_select2('id_month_select', calendar.month_name[other_month])
        self.wait_for_month_shown(year, other_month)

        self.choose_select2('id_year_select', str(year - 1))
        self.wait_for_month_shown(year - 1, other_month)

    def test_next_and_prev_buttons_change_month_across_year_end(self):
        """The arrows step one month at a time, rolling over into the next or previous year.

        Fails if December -> next shows December again, or January of the
        same year, instead of January of the next year.
        """
        self.load_page()
        year, _ = self.shown_month

        self.choose_select2('id_month_select', 'November')
        self.wait_for_month_shown(year, 11)

        self.driver.find_element(By.ID, 'next-month').click()
        self.wait_for_month_shown(year, 12)

        self.driver.find_element(By.ID, 'next-month').click()
        self.wait_for_month_shown(year + 1, 1)

        self.driver.find_element(By.ID, 'prev-month').click()
        self.wait_for_month_shown(year, 12)

    def test_change_saved_on_day_chosen_in_another_month(self):
        """After moving to another month, a change lands on the day clicked in that month, not this one."""
        self.load_page()
        year, month = self.shown_month
        self.driver.find_element(By.ID, 'prev-month').click()
        prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
        self.wait_for_month_shown(prev_year, prev_month)

        self.toggle_unit(self.unit_b)
        self.click_day(3, 2)
        self.open_modal('open_edit_modal', 'available_edits_modal')
        self.type_into('edit_input', '0600')
        self.driver.find_element(By.ID, 'insert_change_edit').click()
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTimeEdit.objects.count() == 1)
        edit = UnitAvailableTimeEdit.objects.get()
        self.assertEqual((edit.unit, edit.date), (self.unit_b, self.cell_date(3, 2)))
        self.assertEqual(edit.date.month, prev_month)


class TestUnitFilter(UnitAvailableTimeTestCase):

    def test_inactive_units_hidden_until_filter_chosen(self):
        """Inactive units are left out of the list until "Show Inactive Units" is chosen.

        Fails if retired units clutter the list by default, or if they cannot
        be reached at all to correct their history.
        """
        self.load_page()

        self.assertTrue(self.unit_option(self.unit_a).is_displayed())
        self.assertTrue(self.unit_option(self.unit_b).is_displayed())
        self.wait_until(lambda: not self.unit_option(self.old_unit).is_displayed())

        # Select All only picks the units on show.
        self.driver.find_element(By.CSS_SELECTOR, '.felter-selectall').click()
        self.wait_until_idle()
        self.assertEqual(self.value_of('units'), [str(self.unit_a.pk), str(self.unit_b.pk)])

        filters = self.driver.find_elements(By.CSS_SELECTOR, '.felter-top-option')
        show_inactive = [f for f in filters if f.text == 'Show Inactive Units'][0]
        show_inactive.click()
        self.wait_until(lambda: self.unit_option(self.old_unit).is_displayed())
        self.assertIn('(inactive)', self.unit_option(self.old_unit).get_attribute('title'))

        self.toggle_unit(self.old_unit)
        self.assertEqual(
            self.value_of('units'), [str(self.unit_a.pk), str(self.unit_b.pk), str(self.old_unit.pk)]
        )

        show_inactive.click()
        self.wait_until(lambda: not self.unit_option(self.old_unit).is_displayed())
        # Hiding a unit also drops it from the selection, so a change cannot reach it unseen.
        self.wait_until(lambda: self.value_of('units') == [str(self.unit_a.pk), str(self.unit_b.pk)])


class TestEditAvailableTime(UnitAvailableTimeTestCase):

    def save_edit(self, hours, label):
        self.open_modal('open_edit_modal', 'available_edits_modal')
        self.type_into('edit_input', hours)
        self.type_into('name_input', label)
        self.driver.find_element(By.ID, 'insert_change_edit').click()
        self.wait_for_invisible('#available_edits_modal')
        self.wait_until_idle()

    def test_edit_available_time_saves_each_unit_and_day(self):
        """Edit Available Time stores the hours and label for every selected unit on every selected day.

        Fails if an edit is lost for one of the units, lands on the wrong day,
        or saves different hours from those typed.
        """
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.toggle_unit(self.unit_b)
        self.click_day(2, 1)
        self.click_day(4, 2, key=Keys.CONTROL)

        self.open_modal('open_edit_modal', 'available_edits_modal')
        self.wait_for_text('#available_edits_modal .num-days-selected', 'Currently 2 days selected for 2 units')
        self.type_into('edit_input', '0430')
        self.assertEqual(self.value_of('edit_input'), '04:30')
        self.type_into('name_input', 'Holiday')
        self.driver.find_element(By.ID, 'insert_change_edit').click()
        self.wait_for_invisible('#available_edits_modal')
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTimeEdit.objects.count() == 4)
        saved = {
            (e.unit_id, e.date, e.hours, e.name) for e in UnitAvailableTimeEdit.objects.all()
        }
        four_thirty = datetime.timedelta(hours=4, minutes=30)
        expected = {
            (unit.pk, self.cell_date(*cell), four_thirty, 'Holiday')
            for unit in (self.unit_a, self.unit_b)
            for cell in ((2, 1), (4, 2))
        }
        self.assertEqual(saved, expected)
        self.assertEqual(UnitAvailableTime.objects.count(), 3, 'an edit must not touch the weekly schedules')

        # The page shows the label on both days, and the modal is cleared for next time.
        self.wait_until(lambda: self.cell_labels(2, 1) == ['Holiday'])
        self.wait_until(lambda: self.cell_labels(4, 2) == ['Holiday'])
        self.assertEqual(self.cell_labels(3, 1), [])
        self.assertEqual(self.value_of('edit_input'), '')
        self.assertEqual(self.value_of('name_input'), '')

    def test_day_with_edit_shows_edited_hours(self):
        """A day with an edit draws its bar for the edited hours, not the weekly schedule's.

        Fails if the calendar keeps showing the old hours after an edit, which
        would hide the change from whoever checks the schedule next.
        """
        UnitAvailableTimeEdit.objects.create(
            unit=self.unit_a, date=self.cell_date_for_setup(1, 2), hours=datetime.timedelta(hours=2), name='Short day'
        )
        self.load_page()
        self.toggle_unit(self.unit_a)

        # Monday with the edit: 2 hours. The Monday before it keeps the scheduled 8.
        self.wait_for_bar_heights(1, 2, [120])
        self.wait_for_bar_heights(1, 1, [480])
        self.assertEqual(self.cell_labels(1, 2), ['Short day'])

        # Edit it again from the page: 0:00 means the unit is not available at all that day.
        self.click_day(1, 2)
        self.save_edit('0000', 'Closed')
        self.wait_until(lambda: UnitAvailableTimeEdit.objects.filter(name='Closed').exists())
        edit = UnitAvailableTimeEdit.objects.get()
        self.assertEqual((edit.date, edit.hours), (self.cell_date(1, 2), datetime.timedelta(0)))
        self.wait_for_bar_heights(1, 2, [])
        self.wait_until(lambda: self.cell_labels(1, 2) == ['Closed'])

    def cell_date_for_setup(self, x, y):
        """cell_date() before the page is open, using the site's date (the browser is pinned to the site's zone)."""
        today = timezone.localdate()
        self.shown_month = (today.year, today.month)
        return self.cell_date(x, y)

    @pytest.mark.xfail(
        strict=True,
        reason='unit_available_time.js:490 duration_readable() does not pad minutes, so 2 hours reads "2:0"',
    )
    def test_hours_tooltip_shows_hours_and_minutes(self):
        """Hovering a bar shows the unit and its available time as h:mm."""
        UnitAvailableTimeEdit.objects.create(
            unit=self.unit_a, date=self.cell_date_for_setup(1, 2), hours=datetime.timedelta(hours=2), name='Short day'
        )
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.wait_for_bar_heights(1, 2, [120])

        bar = self.driver.find_element(By.CSS_SELECTOR, '#day-1_2 rect.bar-rect')
        ActionChains(self.driver).move_to_element(bar).perform()

        def tooltip_text():
            shown = [
                el.get_attribute('textContent')
                for el in self.driver.find_elements(By.CSS_SELECTOR, 'div.hours-tooltip')
                if float(el.value_of_css_property('opacity') or 0) > 0.5
            ]
            return shown[0] if shown else None

        text = self.wait_until(tooltip_text)
        self.assertIn('Linac A', text)
        self.assertIn('2:00', text)


class TestEditSchedule(UnitAvailableTimeTestCase):

    def test_edit_schedule_saves_weekly_hours_from_effective_date(self):
        """Edit Schedule stores a new weekly schedule for the chosen unit, starting on the effective date.

        Fails if the schedule is saved for the wrong unit or from the wrong
        day, or with hours other than those typed, and checks the calendar
        redraws with the new hours from that day on.
        """
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.click_day(3, 1)
        effective = self.cell_date(3, 1)

        self.open_modal('open_uat_modal', 'available_modal')
        self.assertEqual(self.value_of('effective_date'), effective.strftime('%d %b %Y'))
        self.assertEqual(self.value_of('id_hours_monday'), '08:00')
        self.type_into('id_hours_monday', '1000')
        self.type_into('id_hours_saturday', '0415')
        self.driver.find_element(By.ID, 'insert_change_uat').click()
        self.wait_for_invisible('#available_modal')
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTime.objects.filter(date_changed=effective).exists())
        new = UnitAvailableTime.objects.get(date_changed=effective)
        self.assertEqual(new.unit, self.unit_a)
        expected = dict(DEFAULT_HOURS, monday=datetime.timedelta(hours=10),
                        saturday=datetime.timedelta(hours=4, minutes=15))
        self.assertEqual({day: getattr(new, 'hours_%s' % day) for day in DEFAULT_HOURS}, expected)
        self.assertEqual(UnitAvailableTime.objects.filter(unit=self.unit_b).count(), 1)

        # Mondays and Saturdays from the effective date on show the new hours; earlier ones keep the old.
        self.wait_for_bar_heights(1, 2, [600])
        self.wait_for_bar_heights(6, 2, [255])
        self.wait_for_bar_heights(1, 1, [480])
        self.wait_for_bar_heights(6, 0, [])

    def test_effective_date_can_be_typed(self):
        """An effective date typed into the window is the one used, not the day clicked."""
        self.load_page()
        self.toggle_unit(self.unit_b)
        self.click_day(3, 1)
        typed = self.cell_date(5, 3)

        self.open_modal('open_uat_modal', 'available_modal')
        self.type_into('effective_date', typed.strftime('%d %b %Y'))
        # Close flatpickr's calendar so it does not cover the button.
        self.driver.find_element(By.CSS_SELECTOR, '#available_modal .modal-title').click()
        self.type_into('id_hours_friday', '0600')
        self.driver.find_element(By.ID, 'insert_change_uat').click()
        self.wait_for_invisible('#available_modal')
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTime.objects.count() == 4)
        new = UnitAvailableTime.objects.exclude(date_changed=ACCEPTANCE).get()
        self.assertEqual((new.unit, new.date_changed), (self.unit_b, typed))
        self.assertEqual(new.hours_friday, datetime.timedelta(hours=6))

    @pytest.mark.xfail(
        strict=True,
        reason='unit_available_time.js:383 formats with siteConfig.MOMEN_DATE_DATA_FMT (typo), '
        'so no day ever matches a schedule change and the "C" marker is never drawn',
    )
    def test_schedule_change_marked_with_c(self):
        """The first day of a schedule change carries a "C" marker, as the page's own instructions promise."""
        today = timezone.localdate()
        changed = first_displayed_day(today.year, today.month) + datetime.timedelta(days=7 + 3)
        create_schedule(self.unit_a, changed, wednesday=datetime.timedelta(hours=10))

        self.load_page()
        self.toggle_unit(self.unit_a)
        # The schedule itself is applied (10 hours from that Wednesday), so the data reached the page.
        self.wait_for_bar_heights(3, 1, [600])

        self.wait_until(lambda: self.driver.find_elements(By.CSS_SELECTOR, '#day-3_1 text.uat-change-icon'))
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, '#day-3_2 text.uat-change-icon'), [])


class TestDeleteChanges(UnitAvailableTimeTestCase):

    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        start = first_displayed_day(today.year, today.month)
        self.day1 = start + datetime.timedelta(days=8)    # cell (1, 1)
        self.day2 = start + datetime.timedelta(days=9)    # cell (2, 1)
        self.day3 = start + datetime.timedelta(days=10)   # cell (3, 1)
        for unit in (self.unit_a, self.unit_b):
            for day in (self.day1, self.day2, self.day3):
                UnitAvailableTimeEdit.objects.create(unit=unit, date=day, hours=datetime.timedelta(hours=1), name='Hol')
        create_schedule(self.unit_a, self.day1, monday=datetime.timedelta(hours=12))
        create_schedule(self.unit_b, self.day1, monday=datetime.timedelta(hours=12))

    def test_delete_changes_removes_edits_and_schedules_for_selected_units_and_days(self):
        """Delete Changes removes edits and schedule changes on the selected days for the selected units only.

        Fails if it removes too little (the change stays in force) or too much
        (another unit's, or another day's, history disappears).
        """
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.wait_until(lambda: self.cell_labels(1, 1) == ['Hol'])
        self.click_day(1, 1)
        self.click_day(2, 1, key=Keys.CONTROL)

        self.open_modal('open_delete_modal', 'delete_modal')
        self.wait_for_text('#delete_modal .num-days-selected', 'Currently 2 days selected for 1 unit')
        self.driver.find_element(By.ID, 'delete_go').click()
        self.wait_for_invisible('#delete_modal')
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTimeEdit.objects.count() == 4)
        self.assertEqual(
            set(UnitAvailableTimeEdit.objects.values_list('unit_id', 'date')),
            {
                (self.unit_a.pk, self.day3),
                (self.unit_b.pk, self.day1), (self.unit_b.pk, self.day2), (self.unit_b.pk, self.day3),
            },
        )
        self.assertEqual(
            set(UnitAvailableTime.objects.values_list('unit_id', 'date_changed')),
            {
                (self.unit_a.pk, ACCEPTANCE), (self.unit_b.pk, ACCEPTANCE), (self.old_unit.pk, ACCEPTANCE),
                (self.unit_b.pk, self.day1),
            },
        )

        # The labels go from the cleared days and stay on the day left alone.
        self.wait_until(lambda: self.cell_labels(1, 1) == [] and self.cell_labels(2, 1) == [])
        self.assertEqual(self.cell_labels(3, 1), ['Hol'])
        # With the 12-hour Monday schedule gone, the Monday falls back to the original 8 hours.
        self.wait_for_bar_heights(1, 1, [480])

    def test_cancel_delete_keeps_changes(self):
        """Cancel closes the delete window without removing anything."""
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.click_day(1, 1)

        self.open_modal('open_delete_modal', 'delete_modal')
        self.driver.find_element(By.ID, 'delete_cancel').click()
        self.wait_for_invisible('#delete_modal')
        self.wait_until_idle()

        self.assertEqual(UnitAvailableTimeEdit.objects.count(), 6)
        self.assertEqual(UnitAvailableTime.objects.count(), 5)
        self.assertEqual(self.cell_labels(1, 1), ['Hol'])


class TestBrowserEastOfServer(UnitAvailableTimeTestCase):
    """A browser in a time zone ahead of the server's (here London, server in Toronto)."""

    timezone_id = 'Europe/London'

    @pytest.mark.xfail(
        strict=True,
        reason='units/views.py:128 converts the browser-midnight timestamp to the server zone with '
        'timezone.localtime() before taking .date(), so a browser ahead of the server saves the day before',
    )
    def test_edit_saved_on_day_clicked(self):
        """An edit made from a browser ahead of the server still lands on the day that was clicked."""
        self.load_page()
        self.toggle_unit(self.unit_a)
        self.click_day(3, 1)
        self.open_modal('open_edit_modal', 'available_edits_modal')
        self.type_into('edit_input', '0500')
        self.driver.find_element(By.ID, 'insert_change_edit').click()
        self.wait_for_invisible('#available_edits_modal')
        self.wait_until_idle()

        self.wait_until(lambda: UnitAvailableTimeEdit.objects.exists())
        self.assertEqual(UnitAvailableTimeEdit.objects.get().date, self.cell_date(3, 1))


class TestChooseUnitCollapse(SeleniumTestCase):
    """The unit-type sections on the choose-unit pages fold and unfold (units/js/unit_choose.js)."""

    def setUp(self):
        super().setUp()
        unit_type = qa_utils.create_unit_type(name='Versa HD')
        unit_type.collapse = True
        unit_type.save()
        self.unit = qa_utils.create_unit(name='Linac C', tipe=unit_type)
        qa_utils.create_unit_test_collection(unit=self.unit)
        self.user.groups.add(Group.objects.get(name='group'))

    def test_unit_type_section_folds_and_unfolds(self):
        """A unit type set to start collapsed opens and closes on its toggle, and the caret and hint follow.

        Fails if a collapsed unit type cannot be opened, leaving its units out of reach on this page.
        """
        self.login()
        self.open(reverse('choose_unit'))
        toggle = self.wait_for_element('a[data-toggle="collapse"]')
        section = self.driver.find_element(By.CSS_SELECTOR, toggle.get_attribute('data-target'))
        caret = toggle.find_element(By.TAG_NAME, 'i')
        # Found by its link, because WebDriver gives a hidden link no text to match.
        unit_button = section.find_element(
            By.CSS_SELECTOR, 'a[href="%s"]' % reverse('qa_by_unit', kwargs={'unit_number': self.unit.number})
        )

        self.assertFalse(unit_button.is_displayed())
        self.assertIn('fa-caret-right', caret.get_attribute('class'))
        self.assertEqual(toggle.get_attribute('title'), 'Click to show Versa HD units')

        toggle.click()
        self.wait_until(lambda: unit_button.is_displayed())
        self.wait_until(lambda: 'fa-caret-down' in caret.get_attribute('class'))
        self.assertNotIn('fa-caret-right', caret.get_attribute('class'))
        self.assertEqual(toggle.get_attribute('title'), 'Click to hide Versa HD units')

        # Wait for Bootstrap to finish opening; a click while it animates is ignored.
        self.wait_until(lambda: 'collapsing' not in section.get_attribute('class'))
        toggle.click()
        self.wait_until(lambda: not unit_button.is_displayed())
        self.wait_until(lambda: 'fa-caret-right' in caret.get_attribute('class'))
        self.assertEqual(toggle.get_attribute('title'), 'Click to show Versa HD units')
