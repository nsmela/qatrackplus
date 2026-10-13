"""Browser tests for the service log: creating, editing and deleting service events.

Most of the service event form is driven by JavaScript (sl_serviceevent.js):
choosing a unit reloads its service areas and test lists by ajax, the service
type decides whether review is forced, return to service QC and parts rows are
added on the fly, and templates fill the form in. None of that can be proven
by a plain Django test client test, which is why these tests use a browser.

Every test waits for the page the server redirects to after a save before it
looks at the database. The test database is SQLite in memory, shared with the
live server thread, so reading it while the save is still in its transaction
could see half a save.
"""

import csv
import os
import shutil
import tempfile

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from qatrack.accounts.tests.utils import create_user
from qatrack.attachments.models import Attachment
from qatrack.parts import models as p_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log import models as sl_models
from qatrack.service_log.tests import utils as sl_utils


def local_minute(dt):
    """(year, month, day, hour, minute) of an aware datetime in the site's time zone."""
    dt = timezone.localtime(dt)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute)


def aware(year, month, day, hour=12, minute=0):
    return timezone.make_aware(timezone.datetime(year, month, day, hour, minute))


class ServiceLogSeleniumTestCase(SeleniumTestCase):
    """Common data and helpers for the service log browser tests.

    Two serviceable units with one service area each, two service types (one
    of which forces review), a default service event status, and one test
    list assigned to each unit.

    The harness's live server answers one request at a time, because choosing a
    unit fires two ajax requests at once (see SerialLiveServerThread in live.py).
    """

    def setUp(self):
        super().setUp()

        qa_utils.create_status(is_default=True)
        self.default_status = sl_utils.create_service_event_status(name='Pending', is_default=True)

        self.unit = qa_utils.create_unit(name='Linac One')
        self.other_unit = qa_utils.create_unit(name='Linac Two')
        self.service_area = sl_utils.create_service_area(name='Gantry')
        self.other_service_area = sl_utils.create_service_area(name='Couch')
        self.usa = sl_utils.create_unit_service_area(unit=self.unit, service_area=self.service_area)
        self.other_usa = sl_utils.create_unit_service_area(
            unit=self.other_unit, service_area=self.other_service_area
        )

        self.plain_type = sl_utils.create_service_type(name='Preventive', is_review_required=False)
        self.review_type = sl_utils.create_service_type(name='Repair', is_review_required=True)

        self.test_list = qa_utils.create_test_list(name='Output Check')
        self.utc = qa_utils.create_unit_test_collection(unit=self.unit, test_collection=self.test_list)
        other_test_list = qa_utils.create_test_list(name='Couch Check')
        self.other_utc = qa_utils.create_unit_test_collection(unit=self.other_unit, test_collection=other_test_list)
        # Completed QC is only listed for users in a group it is visible to.
        self.user.groups.add(Group.objects.get(name='group'))

    def tearDown(self):
        super().tearDown()
        # A test that failed inside a popup window would leave the next test
        # driving the popup; close every window but the first.
        try:
            handles = self.driver.window_handles
            for handle in handles[1:]:
                self.driver.switch_to.window(handle)
                self.driver.close()
            self.driver.switch_to.window(handles[0])
        except WebDriverException:
            pass

    def create_service_event(self, **kwargs):
        defaults = {
            'unit_service_area': self.usa,
            'service_type': self.plain_type,
            'service_status': self.default_status,
            'user_created_by': self.user,
            'datetime_service': aware(2026, 10, 1, 8, 0),
            'problem_description': 'Existing problem',
        }
        defaults.update(kwargs)
        return sl_utils.create_service_event(**defaults)

    # -- clicking and typing ---------------------------------------------------------------------

    def click_element(self, element):
        """Scroll `element` to the middle of the window and click it like a mouse would.

        The harness's patched WebElement.click scrolls the element to the very
        top of the window, where the fixed navigation bar then covers it.
        """
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        ActionChains(self.driver).move_to_element(element).click().perform()

    def click_css(self, css):
        self.click_element(self.wait_for_visible(css))

    def type_into(self, el_id, text, clear=False):
        element = self.wait_for_visible('#%s' % el_id)
        self.click_element(element)
        if clear:
            element.send_keys(Keys.CONTROL, 'a')
            element.send_keys(Keys.DELETE)
        element.send_keys(text)

    def value_of(self, el_id):
        return self.driver.execute_script('return document.getElementById(arguments[0]).value;', el_id)

    def is_checked(self, el_id):
        return self.driver.execute_script('return document.getElementById(arguments[0]).checked;', el_id)

    def is_disabled(self, el_id):
        return self.driver.execute_script('return document.getElementById(arguments[0]).disabled;', el_id)

    def option_texts(self, el_id):
        """The text of every <option> currently in <select id=el_id>."""
        return self.driver.execute_script(
            'return Array.from(document.getElementById(arguments[0]).options).map(function(o) {'
            '  return o.text.trim(); });', el_id
        )

    # -- select2 -----------------------------------------------------------------------------------

    def select2_choose(self, el_id, text, exact=True):
        """Open the select2 widget for <select id=el_id> and click the option showing `text`.

        This goes through select2's own dropdown the way a person would, so
        the page's change handlers run exactly as they do for a real user.
        """
        self.click_css('#%s + .select2 .select2-selection' % el_id)
        option = self.wait.until(lambda d: self._open_select2_option(text, exact))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def select2_search(self, el_id, term, text):
        """Type `term` into an ajax select2 for <select id=el_id> and click the result containing `text`."""
        self.click_css('#%s + .select2 .select2-selection' % el_id)
        search = self.wait_for_visible('.select2-container--open .select2-search__field')
        search.send_keys(term)
        option = self.wait.until(lambda d: self._open_select2_option(text, exact=False))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def _open_select2_option(self, text, exact=True):
        options = self.driver.find_elements(By.CSS_SELECTOR, '.select2-container--open li.select2-results__option')
        for option in options:
            option_text = option.text.strip()
            if (exact and option_text == text) or (not exact and text in option_text):
                return option
        return False

    # -- the service event form --------------------------------------------------------------------

    def open_new_form(self):
        self.login()
        self.open(reverse('sl_new'))
        self.wait_for_visible('#id_unit_field_fake + .select2')
        self.wait_for_ajax()

    def open_edit_form(self, se):
        self.login()
        self.open(reverse('sl_edit', kwargs={'pk': se.pk}))
        self.wait_for_visible('#id_service_type + .select2')
        self.wait_for_ajax()

    def choose_unit(self, unit_name='Linac One', service_area='Gantry'):
        """Choose a unit and wait until its service areas have been loaded."""
        self.select2_choose('id_unit_field_fake', unit_name)
        self.wait_for_ajax()
        self.wait.until(lambda d: service_area in self.option_texts('id_service_area_field_fake'))

    def enter_service_date(self, text):
        """Type a date into the flatpickr service date input.

        Opening the picker fills in "now" when the box is empty, so the box is
        cleared before typing, as a person would have to do.
        """
        self.type_into('id_datetime_service', text, clear=True)
        self.driver.find_element(By.ID, 'id_datetime_service').send_keys(Keys.TAB)
        self.wait.until(lambda d: self.value_of('id_datetime_service') == text)

    def fill_required_fields(self, service_type='Preventive', problem='Gantry squeaks at 270 degrees'):
        """Fill in everything a new service event needs, for Linac One / Gantry."""
        self.choose_unit()
        self.select2_choose('id_service_area_field_fake', 'Gantry')
        self.select2_choose('id_service_type', service_type)
        self.enter_service_date('2026-10-05 09:15')
        self.type_into('id_problem_description', problem)

    def save_service_event(self):
        """Click Save and wait for the service log dashboard the form redirects to."""
        self.click_css('#save-se')
        self.wait_for_element('#se_toggle')

    def save_service_event_expecting_errors(self):
        """Click Save and wait for the form to come back with an error message."""
        self.click_css('#save-se')
        return self.wait_for_visible('.alert-error, .alert-danger')


class TestNewServiceEvent(ServiceLogSeleniumTestCase):

    def test_choosing_a_unit_loads_its_service_areas_and_test_lists(self):
        """Choosing a unit must replace the service areas and test lists with that unit's own.

        If the ajax reload broke, the form would offer another unit's service
        areas or QC, and the event could be logged against the wrong machine.
        """
        self.open_new_form()
        assert self.is_disabled('id_service_area_field_fake')

        self.choose_unit('Linac Two', 'Couch')
        assert 'Gantry' not in self.option_texts('id_service_area_field_fake')
        assert 'Couch Check' in self.option_texts('id_rtsqa-0-unit_test_collection')

        self.choose_unit('Linac One', 'Gantry')

        assert 'Couch' not in self.option_texts('id_service_area_field_fake')
        assert not self.is_disabled('id_service_area_field_fake')
        assert self.value_of('id_unit_field') == str(self.unit.pk)
        rts_options = self.option_texts('id_rtsqa-0-unit_test_collection')
        assert 'Output Check' in rts_options
        assert 'Couch Check' not in rts_options
        initiated_options = self.option_texts('id_initiated_utc_field')
        assert any('Output Check' in o for o in initiated_options)
        assert not any('Couch Check' in o for o in initiated_options)
        assert self.javascript_errors() == []

    def test_new_service_event_is_saved_with_the_entered_values(self):
        """Filling in the blank form and saving must create one service event holding what was entered."""
        self.open_new_form()
        self.fill_required_fields()
        self.type_into('id_work_description', 'Greased the bearing')

        self.save_service_event()

        se = sl_models.ServiceEvent.objects.get()
        assert se.unit_service_area == self.usa
        assert se.service_type == self.plain_type
        assert se.service_status == self.default_status
        assert se.problem_description == 'Gantry squeaks at 270 degrees'
        assert se.work_description == 'Greased the bearing'
        assert se.user_created_by == self.user
        assert local_minute(se.datetime_service) == (2026, 10, 5, 9, 15)
        assert se.is_active
        assert sl_models.ServiceLog.objects.filter(service_event=se, log_type=sl_models.NEW_SERVICE_EVENT).exists()

    def test_service_type_requiring_review_forces_and_locks_review_required(self):
        """A service type that requires review must tick "Review required" and stop it being unticked.

        Otherwise a repair that policy says must be reviewed could be saved
        without ever showing up in the review queue.
        """
        self.open_new_form()
        self.fill_required_fields(service_type='Preventive')
        self.click_css('#id_is_review_required_fake')
        assert not self.is_checked('id_is_review_required_fake')
        assert not self.is_disabled('id_is_review_required_fake')

        self.select2_choose('id_service_type', 'Repair')

        assert self.is_checked('id_is_review_required_fake')
        assert self.is_disabled('id_is_review_required_fake')
        assert self.is_checked('id_is_review_required')

        self.save_service_event()

        se = sl_models.ServiceEvent.objects.get()
        assert se.service_type == self.review_type
        assert se.is_review_required

    def test_unticking_review_required_is_saved_for_a_type_that_does_not_force_it(self):
        """For a service type that does not force review, unticking "Review required" must be saved.

        The visible checkbox is a stand-in that JavaScript copies into a hidden
        one; if the copy broke, the saved event would not match the screen.
        """
        self.open_new_form()
        self.fill_required_fields(service_type='Preventive')
        assert self.is_checked('id_is_review_required_fake')

        self.click_css('#id_is_review_required_fake')
        self.save_service_event()

        assert not sl_models.ServiceEvent.objects.get().is_review_required

    def test_service_and_lost_time_masks_save_as_durations(self):
        """Digits typed into the hh:mm duration masks must be saved as those durations.

        The mask fills from the right, so typing 245 must mean 02:45, not 24:50.
        """
        self.open_new_form()
        self.fill_required_fields()

        self.type_into('id_duration_service_time', '245')
        self.type_into('id_duration_lost_time', '30')
        # Unfilled places in the mask show as underscores: "_2:45".
        assert self.value_of('id_duration_service_time').replace('_', '0') == '02:45'
        assert self.value_of('id_duration_lost_time').replace('_', '0') == '00:30'

        self.save_service_event()

        se = sl_models.ServiceEvent.objects.get()
        assert se.duration_service_time == timezone.timedelta(hours=2, minutes=45)
        assert se.duration_lost_time == timezone.timedelta(minutes=30)

    def test_hours_row_saves_the_user_and_time_entered(self):
        """A user and an hh:mm time entered in a work hours row must be saved as that person's hours."""
        tech = create_user(is_superuser=False, uname='tech')
        tech.first_name, tech.last_name = 'Terry', 'Tech'
        tech.save()
        tech.user_permissions.add(Permission.objects.get(codename='can_have_hours'))

        self.open_new_form()
        self.fill_required_fields()

        self.select2_choose('id_hours-0-user_or_thirdparty', 'Terry Tech')
        self.type_into('id_hours-0-time', '130')
        assert self.value_of('id_hours-0-time').replace('_', '0') == '01:30'

        self.save_service_event()

        hours = sl_models.Hours.objects.get()
        assert hours.service_event == sl_models.ServiceEvent.objects.get()
        assert hours.user == tech
        assert hours.third_party is None
        assert hours.time == timezone.timedelta(hours=1, minutes=30)

    def test_return_to_service_qc_row_is_saved_and_shown_again_on_edit(self):
        """A return to service QC row added on the form must be saved and still be there when editing.

        Losing it would let a machine go back into clinical use without the QC
        that was asked for.
        """
        self.open_new_form()
        self.fill_required_fields()

        rows_before = len(self.driver.find_elements(By.CSS_SELECTOR, '#rtsqa-tbody .rtsqa-row'))
        self.click_css('#add-rtsqa')
        new_prefix = 'rtsqa-%d' % rows_before
        self.wait_for_element('#%s' % new_prefix)
        assert self.value_of('id_rtsqa-TOTAL_FORMS') == str(rows_before + 1)

        self.select2_choose('id_%s-unit_test_collection' % new_prefix, 'Output Check')
        performed = self.wait_for_visible('#select-tli-%s' % new_prefix)
        assert '/%d/%s/' % (self.utc.pk, new_prefix) in performed.get_attribute('data-link')

        self.save_service_event()

        se = sl_models.ServiceEvent.objects.get()
        rtsqa = sl_models.ReturnToServiceQA.objects.get()
        assert rtsqa.service_event == se
        assert rtsqa.unit_test_collection == self.utc
        assert rtsqa.test_list_instance is None
        assert rtsqa.user_assigned_by == self.user

        self.open(reverse('sl_edit', kwargs={'pk': se.pk}))
        self.wait_for_visible('#select-tli-rtsqa-0')
        assert self.value_of('id_rtsqa-0-id') == str(rtsqa.pk)
        assert self.value_of('id_rtsqa-0-unit_test_collection') == str(self.utc.pk)
        # The unit can no longer be changed once return to service QC is attached.
        assert self.is_disabled('id_unit_field_fake')

    def test_initiated_by_qc_session_chosen_in_popup_is_linked(self):
        """Choosing the QC session that started the event, in the popup window, must link it to the event."""
        tli = qa_utils.create_test_list_instance(unit_test_collection=self.utc, created_by=self.user)

        self.open_new_form()
        self.fill_required_fields()
        main_window = self.driver.current_window_handle

        self.select2_choose('id_initiated_utc_field', 'Output Check', exact=False)
        self.wait.until(lambda d: len(d.window_handles) == 2)
        popup = [h for h in self.driver.window_handles if h != main_window][0]
        self.driver.switch_to.window(popup)
        self.click_css('#select-%d' % tli.pk)
        self.wait.until(lambda d: len(d.window_handles) == 1)
        self.driver.switch_to.window(main_window)

        self.wait.until(lambda d: self.value_of('id_test_list_instance_initiated_by') == str(tli.pk))
        def linked_view_href():
            # The View button is re-rendered as the choice arrives from the
            # popup, so look it up afresh on each try rather than holding on to
            # an element that may go stale.
            try:
                button = self.driver.find_element(By.CSS_SELECTOR, '#view-tli-btn')
                href = button.get_attribute('href') if button.is_displayed() else None
            except (NoSuchElementException, StaleElementReferenceException):
                return None
            return href if href and href.rstrip('/').endswith('/%d' % tli.pk) else None

        view_href = self.wait_until(linked_view_href, message='View link never pointed at the chosen QC session')
        assert reverse('view_test_list_instance') in view_href

        self.save_service_event()

        assert sl_models.ServiceEvent.objects.get().test_list_instance_initiated_by == tli

    def test_related_service_event_found_by_search_is_linked(self):
        """A service event found through the related events search must be linked to the new one."""
        earlier = self.create_service_event(problem_description='Earlier gantry fault')

        self.open_new_form()
        self.fill_required_fields()
        self.select2_search('id_service_event_related_field', str(earlier.pk), str(earlier.pk))
        self.wait.until(lambda d: str(earlier.pk) in self.driver.execute_script(
            "return $('#id_service_event_related_field').val();"
        ))

        self.save_service_event()

        new_se = sl_models.ServiceEvent.objects.exclude(pk=earlier.pk).get()
        assert list(new_se.service_event_related.all()) == [earlier]


class TestPartsUsed(ServiceLogSeleniumTestCase):

    def setUp(self):
        super().setUp()
        self.part = sl_utils.create_part(part_number='P-100', name='Bearing', quantity_current=5)
        site = sl_utils.create_site(name='Main')
        room = sl_utils.create_room(site=site, name='Stores')
        self.storage = sl_utils.create_storage(room=room, location='Shelf A')
        self.psc = sl_utils.create_part_storage_collection(part=self.part, storage=self.storage, quantity=5)

    def test_part_used_is_saved_and_taken_out_of_storage(self):
        """Using parts from storage must record them and lower the stock left in that storage.

        If stock were not taken out, the parts inventory would claim parts that
        are already inside a machine.
        """
        self.open_new_form()
        self.fill_required_fields()

        self.select2_search('id_parts-0-part', 'Bear', 'P-100')
        self.wait_for_ajax()
        self.wait.until(lambda d: any('Shelf A' in o for o in self.option_texts('id_parts-0-from_storage')))
        self.select2_choose('id_parts-0-from_storage', 'Shelf A', exact=False)
        self.type_into('id_parts-0-quantity', '2', clear=True)

        self.save_service_event()

        part_used = p_models.PartUsed.objects.get()
        assert part_used.service_event == sl_models.ServiceEvent.objects.get()
        assert part_used.part == self.part
        assert part_used.from_storage == self.storage
        assert part_used.quantity == 2
        self.psc.refresh_from_db()
        assert self.psc.quantity == 3
        self.part.refresh_from_db()
        assert self.part.quantity_current == 3

    def test_deleting_a_part_used_row_puts_the_parts_back_in_storage(self):
        """Deleting a parts row on edit must remove it and return its parts to the storage they came from."""
        se = self.create_service_event()
        p_models.PartUsed.objects.create(service_event=se, part=self.part, from_storage=self.storage, quantity=2)
        self.psc.quantity = 3
        self.psc.save()

        self.open_edit_form(se)
        self.click_css('#id_parts-0-DELETE')
        self.save_service_event()

        assert not p_models.PartUsed.objects.exists()
        self.psc.refresh_from_db()
        assert self.psc.quantity == 5
        self.part.refresh_from_db()
        assert self.part.quantity_current == 5


class TestServiceEventTemplates(ServiceLogSeleniumTestCase):

    def create_template(self, is_review_required):
        template = sl_utils.create_service_event_template(
            name='Annual PM',
            service_type=self.plain_type,
            service_area=self.service_area,
            problem_description='Annual preventive maintenance',
            work_description='Follow the PM checklist',
            created_by=self.user,
        )
        template.is_review_required = is_review_required
        template.save()
        template.return_to_service_test_lists.add(self.test_list)
        return template

    def apply_template(self):
        self.open_new_form()
        self.choose_unit()
        self.wait_for_ajax()
        self.wait.until(lambda d: 'Annual PM' in self.option_texts('id_service_event_template'))
        self.select2_choose('id_service_event_template', 'Annual PM')
        self.wait.until(lambda d: self.value_of('id_problem_description') == 'Annual preventive maintenance')

    def test_applying_a_template_fills_in_the_form_and_its_return_to_service_qc(self):
        """Choosing a template must fill in its type, area, descriptions, review flag and RTS QC, and save them."""
        template = self.create_template(is_review_required=True)

        self.apply_template()

        assert self.value_of('id_service_type') == str(self.plain_type.pk)
        assert self.value_of('id_service_area_field_fake') == str(self.service_area.pk)
        assert self.value_of('id_work_description') == 'Follow the PM checklist'
        assert self.is_checked('id_is_review_required_fake')
        rows = self.driver.find_elements(By.CSS_SELECTOR, '#rtsqa-tbody .rtsqa-row')
        assert len(rows) == 1
        assert self.value_of('id_rtsqa-0-unit_test_collection') == str(self.utc.pk)
        self.wait_for_visible('#select-tli-rtsqa-0')

        self.enter_service_date('2026-10-05 09:15')
        self.save_service_event()

        se = sl_models.ServiceEvent.objects.get()
        assert se.service_event_template == template
        assert se.service_type == self.plain_type
        assert se.unit_service_area == self.usa
        assert se.problem_description == 'Annual preventive maintenance'
        assert se.work_description == 'Follow the PM checklist'
        assert se.is_review_required
        assert list(se.returntoserviceqa_set.values_list('unit_test_collection', flat=True)) == [self.utc.pk]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'sl_serviceevent.js:916 sets the visible "Review required" box from the template without '
            'triggering change, so the hidden is_review_required field keeps its old value'
        ),
    )
    def test_template_that_does_not_require_review_is_saved_without_review(self):
        """A template that does not require review must save an event that does not require review.

        The form shows "Review required" unticked after the template is chosen;
        what is saved must match what the user saw.
        """
        self.create_template(is_review_required=False)

        self.apply_template()
        assert not self.is_checked('id_is_review_required_fake')

        self.enter_service_date('2026-10-05 09:15')
        self.save_service_event()

        assert not sl_models.ServiceEvent.objects.get().is_review_required


class TestAttachments(ServiceLogSeleniumTestCase):

    def setUp(self):
        super().setUp()
        # Keep uploaded files out of the repository's media directory.
        self.media_root = tempfile.mkdtemp(prefix='qatrack-sl-selenium-')
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media_settings = self.settings(
            MEDIA_ROOT=self.media_root, UPLOAD_ROOT=os.path.join(self.media_root, 'uploads')
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def test_uploaded_attachment_is_saved_with_the_service_event(self):
        """A file chosen in the attachments box must be stored against the service event."""
        path = os.path.join(self.media_root, 'gantry_photo.txt')
        with open(path, 'w') as f:
            f.write('photo of the worn bearing')

        self.open_new_form()
        self.fill_required_fields()
        # The real file input is hidden behind a styled "Browse" label; show it
        # so WebDriver can hand it a file, as the operating system dialog would.
        file_input = self.driver.find_element(By.ID, 'id_se_attachments')
        self.driver.execute_script("arguments[0].style.display = 'block';", file_input)
        file_input.send_keys(path)
        self.wait_for_text('#se-attachment-names', 'gantry_photo.txt')

        self.save_service_event()

        attachment = Attachment.objects.get()
        assert attachment.serviceevent == sl_models.ServiceEvent.objects.get()
        assert attachment.label == 'gantry_photo.txt'
        assert attachment.created_by == self.user
        with attachment.attachment.open('r') as f:
            assert f.read() == 'photo of the worn bearing'

    def test_ticking_delete_on_edit_removes_the_attachment(self):
        """Ticking an attachment's delete box on edit must remove that attachment, and only that one."""
        se = self.create_service_event()
        doomed = Attachment.objects.create(
            attachment=SimpleUploadedFile('old.txt', b'old'), label='old.txt', serviceevent=se,
            created_by=self.user,
        )
        kept = Attachment.objects.create(
            attachment=SimpleUploadedFile('keep.txt', b'keep'), label='keep.txt', serviceevent=se,
            created_by=self.user,
        )

        self.open_edit_form(se)
        self.click_css('#attach-%d-DELETE' % doomed.pk)
        assert self.value_of('id_se_attachments_delete_ids') == str(doomed.pk)
        self.save_service_event()

        assert list(Attachment.objects.all()) == [kept]


class TestEditAndDeleteServiceEvent(ServiceLogSeleniumTestCase):

    def test_status_needing_reviewed_rts_qc_is_refused_while_rts_qc_is_unreviewed(self):
        """A status that needs reviewed return to service QC must be refused while that QC is unreviewed.

        Otherwise a machine could be marked ready for clinical use before its
        return to service QC had been checked by anyone.
        """
        approved = sl_utils.create_service_event_status(
            name='Approved', is_review_required=False, rts_qa_must_be_reviewed=True
        )
        se = self.create_service_event()
        tli = qa_utils.create_test_list_instance(unit_test_collection=self.utc, created_by=self.user)
        sl_utils.create_return_to_service_qa(
            service_event=se, unit_test_collection=self.utc, user_assigned_by=self.user, add_test_list_instance=tli
        )
        assert not tli.all_reviewed

        self.open_edit_form(se)
        # The existing row shows the performed QC's review button once its status has loaded.
        self.wait_for_visible('#review-tli-rtsqa-0')
        self.select2_choose('id_service_status', 'Approved')

        alert = self.save_service_event_expecting_errors()

        assert 'Service Event Details' in alert.text
        self.wait_for_text(
            '.has-error', 'Cannot select status: Return to service QC must be performed and reviewed.'
        )
        se.refresh_from_db()
        assert se.service_status == self.default_status
        assert approved.serviceevent_set.count() == 0

    def test_details_page_shows_the_event_and_its_return_to_service_qc(self):
        """The details page must show the event's fields, its RTS QC and working links to review and edit."""
        se = self.create_service_event(
            problem_description='Couch drifts', service_time=timezone.timedelta(hours=1, minutes=15)
        )
        tli = qa_utils.create_test_list_instance(unit_test_collection=self.utc, created_by=self.user)
        sl_utils.create_return_to_service_qa(
            service_event=se, unit_test_collection=self.utc, user_assigned_by=self.user, add_test_list_instance=tli
        )

        self.login()
        self.open(reverse('sl_details', kwargs={'pk': se.pk}))
        body = self.wait_for_visible('.box-body')

        page = self.driver.find_element(By.TAG_NAME, 'body').text
        assert 'Service Event %d Details' % se.pk in page
        assert 'Linac One' in body.text
        assert 'Gantry' in body.text
        assert 'Preventive' in body.text
        assert 'Couch drifts' in page
        assert '1:15' in page
        assert 'Output Check' in page

        review_href = reverse('review_test_list_instance', kwargs={'pk': tli.pk})
        review = self.driver.find_element(By.CSS_SELECTOR, 'a[href^="%s?next="]' % review_href)
        assert review.get_attribute('href').endswith(reverse('sl_details', kwargs={'pk': se.pk}))
        edit = self.driver.find_element(By.LINK_TEXT, 'Edit')
        assert edit.get_attribute('href').endswith(reverse('sl_edit', kwargs={'pk': se.pk}))

    def test_deleting_a_service_event_with_a_reason_makes_it_inactive(self):
        """Deleting an event must keep it in the database as inactive, with the reason logged."""
        se = self.create_service_event()

        self.open_edit_form(se)
        self.click_css('a.service-delete')
        self.wait_for_visible('#id_reason + .select2')
        self.select2_choose('id_reason', 'Invalid')
        self.type_into('id_comment', 'Logged against the wrong unit')
        self.click_css('#submit-delete')
        self.wait_for_element('#se_toggle')

        se.refresh_from_db()
        assert not se.is_active
        log = sl_models.ServiceLog.objects.get(service_event=se, log_type=sl_models.DELETED_SERVICE_EVENT)
        assert log.extra_info == {'reason': 'Invalid', 'comment': 'Logged against the wrong unit'}
        assert 'Service event %d deleted' % se.pk in self.driver.find_element(By.TAG_NAME, 'body').text

    @pytest.mark.xfail(
        strict=True,
        reason='service_log/views.py:858-862 DeleteServiceEvent.form_invalid returns a URL string, not a response',
    )
    def test_invalid_delete_form_warns_and_keeps_the_service_event(self):
        """A delete form that fails validation must show a warning and leave the event active.

        The reason list is fixed, so an invalid reason only arrives from a
        stale or altered page; here the page is altered to send one.
        """
        se = self.create_service_event()

        self.login()
        self.open(reverse('se_delete', kwargs={'pk': se.pk}))
        self.wait_for_visible('#id_reason + .select2')
        self.driver.execute_script(
            "$('#id_reason').append(new Option('Not a reason', 'not-a-reason')).val('not-a-reason').change();"
        )
        with self.wait_for_page_load():
            self.click_css('#submit-delete')
        self.wait.until(lambda d: d.execute_script("return document.readyState === 'complete';"))

        page = self.driver.find_element(By.TAG_NAME, 'body').text
        assert 'Server Error' not in page
        assert 'Could not delete service event' in page
        se.refresh_from_db()
        assert se.is_active


class TestDownTimeAndSchedules(ServiceLogSeleniumTestCase):

    def test_down_time_list_filters_by_date_and_download_link_carries_the_filter(self):
        """Filtering the down time list by date must narrow the list and the up time summary download.

        The summary is what physicists hand to management; if the download
        ignored the filter it would quietly report on the wrong period.
        """
        if not hasattr(self.driver, 'execute_cdp_cmd'):
            pytest.skip('Reading the downloaded summary needs Chromium')
        now = timezone.localtime()
        self.create_service_event(
            datetime_service=now - timezone.timedelta(days=3), problem_description='In range',
            lost_time=timezone.timedelta(hours=2),
        )
        self.create_service_event(
            unit_service_area=self.other_usa, datetime_service=now - timezone.timedelta(days=60),
            problem_description='Too early',
        )
        download_dir = tempfile.mkdtemp(prefix='qatrack-sl-download-')
        self.addCleanup(shutil.rmtree, download_dir, ignore_errors=True)
        self.driver.execute_cdp_cmd('Browser.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
        table = '#listable-table-se_down_time tbody'

        self.login()
        self.open(reverse('se_down_time'))
        self.wait_for_text(table, 'Too early')

        self.click_css('#daterange-div-2 button')
        self.click_element(self.wait.until(lambda d: d.find_element(
            By.XPATH, '//div[contains(@class, "daterangepicker")]//li[normalize-space()="Last 7 Days"]'
        )))
        self.wait.until(lambda d: 'Too early' not in d.find_element(By.CSS_SELECTOR, table).text)
        assert 'In range' in self.driver.find_element(By.CSS_SELECTOR, table).text
        date_from, date_to = self.driver.execute_script(
            "return $('input.text_filter[rel=1]').val();"
        ).split(' - ')

        self.click_css('#go_down_time')
        csv_path = os.path.join(download_dir, 'qatrack_unit_uptime.csv')
        self.wait_until(lambda: os.path.exists(csv_path) and os.path.getsize(csv_path) > 0)
        with open(csv_path, newline='') as f:
            rows = list(csv.reader(f))

        assert rows[0] == ['Up Time Report: %s to %s' % (date_from, date_to)]
        unit_rows = [r for r in rows if r and r[0] in ('Linac One', 'Linac Two')]
        assert [r[0] for r in unit_rows] == ['Linac One']

    def create_overdue_schedule(self, template_name, visible_to):
        template = sl_utils.create_service_event_template(
            name=template_name, service_type=self.plain_type, service_area=self.service_area, created_by=self.user,
        )
        schedule = sl_utils.create_service_event_schedule(
            service_event_template=template, unit_service_area=self.usa, assigned_to=visible_to,
        )
        schedule.visible_to.add(visible_to)
        sl_models.ServiceEventSchedule.objects.filter(pk=schedule.pk).update(
            due_date=timezone.now() - timezone.timedelta(days=1), auto_schedule=False,
        )
        return schedule

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'service_log/urls.py:44-48 se_schedule_overview_due_dates_user uses DueDateOverview, '
            'not DueDateOverviewUser, so it is not filtered to the user\'s groups'
        ),
    )
    def test_due_dates_for_your_groups_hides_schedules_of_other_groups(self):
        """The "For Your Groups" overview must list only schedules visible to the user's groups."""
        mine = Group.objects.create(name='Physics')
        theirs = Group.objects.create(name='Engineering')
        self.user.groups.add(mine)
        self.create_overdue_schedule('Our Monthly PM', mine)
        self.create_overdue_schedule('Their Monthly PM', theirs)

        self.login()
        self.open(reverse('se_schedule_overview_due_dates_user'))
        self.wait_for_text('#table-overdue', 'Our Monthly PM')

        page = self.driver.find_element(By.TAG_NAME, 'body').text
        assert 'For Your Groups' in page
        assert 'Their Monthly PM' not in page

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'service_log/templates/service_log/overview_by_due_date.html:155 links with '
            'se_schedule.pk, which is not in the context (the loop variable is sch), so the link has no schedule'
        ),
    )
    def test_due_date_overview_link_opens_the_scheduled_service_event(self):
        """Each schedule in the due date overview must link to a new event for that schedule."""
        group = Group.objects.create(name='Physics')
        self.user.groups.add(group)
        schedule = self.create_overdue_schedule('Our Monthly PM', group)

        self.login()
        self.open(reverse('se_schedule_overview_due_dates'))
        link = self.wait.until(lambda d: d.find_element(By.LINK_TEXT, 'Our Monthly PM'))

        assert 'se_schedule=%d&' % schedule.pk in link.get_attribute('href')


class TestServiceDatesAndTimes(ServiceLogSeleniumTestCase):
    """The service date is saved, shown and re-saved exactly, whatever zone the workstation is in.

    Late-evening times are used on purpose: in UTC they are already the next
    day, so a conversion done in the wrong zone shows up as a wrong date.
    """

    def test_late_evening_service_date_is_shown_again_and_unchanged_by_saving_again(self):
        """22:30 on 5 Oct is saved as such, shown as such on the edit and details pages, and survives a re-save.

        If this fails, a service event moves to the wrong day, and each edit can move it again.
        """
        self.open_new_form()
        self.fill_required_fields()
        self.enter_service_date('2026-10-05 22:30')
        self.save_service_event()
        se = sl_models.ServiceEvent.objects.get()
        assert local_minute(se.datetime_service) == (2026, 10, 5, 22, 30)

        self.open_edit_form(se)
        assert self.value_of('id_datetime_service') == '2026-10-05 22:30'
        self.save_service_event()
        se.refresh_from_db()
        assert local_minute(se.datetime_service) == (2026, 10, 5, 22, 30)

        self.open(reverse('sl_details', kwargs={'pk': se.pk}))
        self.wait_for_visible('.box-body')
        assert '2026-10-05 22:30' in self.driver.find_element(By.TAG_NAME, 'body').text

    def assert_opening_the_empty_date_fills_in_now(self):
        before = timezone.localtime().replace(second=0, microsecond=0)
        self.open_new_form()
        self.click_css('#id_datetime_service')
        self.wait_until(lambda: self.value_of('id_datetime_service'), message='opening the picker filled in nothing')
        after = timezone.localtime()
        shown = timezone.make_aware(timezone.datetime.strptime(self.value_of('id_datetime_service'), '%Y-%m-%d %H:%M'))
        assert before <= shown <= after, 'the picker filled in %s, opened between %s and %s' % (shown, before, after)

    def test_opening_the_empty_service_date_fills_in_now(self):
        """Opening the picker on an empty service date fills in the time now.

        If this fails, a service event recorded without changing the date is filed
        at the wrong time.
        """
        self.assert_opening_the_empty_date_fills_in_now()

    def test_opening_the_empty_service_date_fills_in_now_on_a_workstation_in_another_zone(self):
        """The same on a workstation whose clock is set to another zone: it is the server's "now" that counts.

        If this fails, service events entered from a computer set to another zone
        are filed hours out.
        """
        self.use_browser_timezone('Asia/Tokyo')
        self.assert_opening_the_empty_date_fills_in_now()

    def test_return_to_service_qc_time_is_shown_in_the_sites_time_on_a_workstation_in_another_zone(self):
        """The completion time of linked return to service QC reads the same as everywhere else on the site.

        The row is filled in by JavaScript from the server's answer. If this fails,
        a workstation set to another zone shows the QC as done at another time, or
        on another day, than the server-rendered pages say.
        """
        se = self.create_service_event()
        tli = qa_utils.create_test_list_instance(
            unit_test_collection=self.utc, created_by=self.user, work_completed=aware(2026, 10, 5, 22, 30)
        )
        sl_utils.create_return_to_service_qa(
            service_event=se, unit_test_collection=self.utc, user_assigned_by=self.user, add_test_list_instance=tli
        )

        self.use_browser_timezone('Asia/Tokyo')
        self.open_edit_form(se)
        self.wait_until(lambda: self.driver.find_element(By.ID, 'work-completed-rtsqa-0').text.strip(),
                        message='the return to service QC row never showed a completion time')
        assert self.driver.find_element(By.ID, 'work-completed-rtsqa-0').text.strip() == '05 Oct 2026 22:30'
