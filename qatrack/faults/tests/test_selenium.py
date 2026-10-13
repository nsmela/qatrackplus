"""Browser tests for logging and reviewing faults (qatrack/faults).

Much of the fault form runs in the browser (faults/js/faults.js): choosing a
unit decides which modalities may be picked and which service events can be
linked, fault types are looked up (and new ones offered) by ajax, and the
"Log Fault" window on the Perform QC page saves without leaving the page. The
unreviewed list's bulk acknowledge (faults/js/faultsbulkreview.js) and the
comment box are JavaScript too. A Django test client cannot see any of that,
so these tests use a real browser and then check what was saved.

Every test waits for the page the server answers with (or for jQuery to go
quiet) before it reads the database, because the live server and the test
share one in-memory SQLite connection.
"""

import os
import shutil
import tempfile

from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_comments.models import Comment
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from qatrack.accounts.tests.utils import create_user
from qatrack.attachments.models import Attachment
from qatrack.faults import models
from qatrack.faults.tests import utils as f_utils
from qatrack.qa.tests import utils as qa_utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log.tests import utils as sl_utils
from qatrack.units.models import Modality


def local_minute(dt):
    """(year, month, day, hour, minute) of an aware datetime in the site's time zone."""
    dt = timezone.localtime(dt)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute)


def aware(year, month, day, hour=12, minute=0):
    return timezone.make_aware(timezone.datetime(year, month, day, hour, minute))


class FaultsSeleniumTestCase(SeleniumTestCase):
    """Common data and helpers for the fault browser tests.

    Two serviceable units with different modalities: Linac One has 6 MV
    photons and 9 MeV electrons, Linac Two has only protons. Both have QC
    visible to the user's group, because the fault form only offers units
    whose QC the user can see. Two fault types exist already.
    """

    def setUp(self):
        super().setUp()
        self.user.first_name, self.user.last_name = 'Pat', 'Physicist'
        self.user.save()
        self.group = qa_utils.create_group(name='Therapists')
        self.user.groups.add(self.group)

        self.unit = qa_utils.create_unit(name='Linac One')
        self.photon = Modality.objects.get(name='6MV Photon')
        self.electron = qa_utils.create_modality(energy=9, particle='electron')
        self.unit.modalities.add(self.electron)

        self.other_unit = qa_utils.create_unit(name='Linac Two')
        self.proton = qa_utils.create_modality(name='Proton')
        self.other_unit.modalities.set([self.proton])

        self.test_list = qa_utils.create_test_list(name='Daily QC')
        self.utc = qa_utils.create_unit_test_collection(unit=self.unit, test_collection=self.test_list)
        qa_utils.create_unit_test_collection(unit=self.other_unit, test_collection=self.test_list)

        self.mlc = f_utils.create_fault_type(code='MLC-12', description='Leaf will not move')
        self.gantry = f_utils.create_fault_type(code='GANTRY-3', description='Gantry stalls')

    def tearDown(self):
        super().tearDown()
        try:
            self.driver.switch_to.default_content()
        except WebDriverException:
            pass

    def create_fault(self, unit=None, fault_type=None, **kwargs):
        return f_utils.create_fault(
            unit=unit or self.unit, fault_type=fault_type or self.mlc, user=self.user, **kwargs
        )

    # -- clicking and typing ---------------------------------------------------------------------

    def click_element(self, element):
        """Scroll `element` to the middle of the window and click it like a mouse would."""
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
        return self.driver.execute_script('return $(document.getElementById(arguments[0])).val();', el_id)

    def page_text(self):
        return self.driver.find_element(By.TAG_NAME, 'body').text

    def enabled_options(self, el_id):
        """The text of every <option> in <select id=el_id> that is not disabled."""
        return self.driver.execute_script(
            'return Array.from(document.getElementById(arguments[0]).options)'
            '  .filter(function(o) { return !o.disabled; })'
            '  .map(function(o) { return o.text.trim(); });', el_id
        )

    # -- select2 -----------------------------------------------------------------------------------

    def open_select2(self, el_id):
        self.click_css('#%s ~ .select2 .select2-selection' % el_id)
        return self.wait_for_visible('.select2-container--open .select2-results')

    def close_select2(self):
        self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def select2_results(self):
        """The text of each option a person can see in the open select2 dropdown.

        WebDriver gives hidden elements no text, so options hidden by CSS are left out.
        """
        texts = self.driver.execute_script(
            "return $('.select2-container--open li.select2-results__option:visible')"
            "  .map(function() { return $(this).text().trim(); }).get();"
        )
        return [t for t in texts if t]

    def _open_select2_option(self, text, exact=True):
        """The visible option showing `text` in the open select2 dropdown, or False.

        The ajax lookups replace the options while they are being read, so a
        stale option just means "look again".
        """
        options = self.driver.find_elements(By.CSS_SELECTOR, '.select2-container--open li.select2-results__option')
        for option in options:
            try:
                option_text = option.text.strip()
            except StaleElementReferenceException:
                return False
            if (exact and option_text == text) or (not exact and text in option_text):
                return option
        return False

    def select2_choose(self, el_id, text, exact=True):
        """Open the select2 widget for <select id=el_id> and click the option showing `text`.

        Going through select2's own dropdown runs the page's change handlers
        exactly as they run for a person.
        """
        self.open_select2(el_id)
        option = self.wait.until(lambda d: self._open_select2_option(text, exact))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def select2_search(self, el_id, term, text, exact=False):
        """Type `term` into an ajax select2 for <select id=el_id> and click the result showing `text`."""
        self.open_select2(el_id)
        search = self.wait_for_visible('.select2-container--open .select2-search__field')
        search.send_keys(term)
        option = self.wait.until(lambda d: self._open_select2_option(text, exact))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def choose_fault_type(self, term, text, exact=False):
        """Search for a fault type and pick it.

        The fault type box is a multiple select2 whose search field lives
        inside the box itself, not in the dropdown.
        """
        self.click_css('#id_fault-fault_types_field ~ .select2 .select2-search__field')
        search = self.driver.switch_to.active_element
        search.send_keys(term)
        option = self.wait.until(lambda d: self._open_select2_option(text, exact))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')
        self.wait_for_ajax()

    # -- the fault form ----------------------------------------------------------------------------

    def open_create_form(self, user=None):
        self.login(user=user)
        self.open(reverse('fault_create'))
        self.wait_for_visible('#id_fault-unit ~ .select2')
        self.wait_for_ajax()

    def open_edit_form(self, fault):
        self.login()
        self.open(reverse('fault_edit', kwargs={'pk': fault.pk}))
        self.wait_for_visible('#id_fault-unit ~ .select2')
        self.wait_for_ajax()

    def choose_unit(self, unit_name='Linac One'):
        self.select2_choose('id_fault-unit', 'Other :: %s' % unit_name)
        self.wait_for_ajax()

    def enter_occurred(self, text):
        """Type a date into the flatpickr "occurred" box, clearing what opening the picker fills in."""
        self.type_into('id_fault-occurred', text, clear=True)
        self.driver.find_element(By.ID, 'id_fault-occurred').send_keys(Keys.TAB)
        self.wait.until(lambda d: self.value_of('id_fault-occurred') == text)

    def save_fault_form(self):
        """Submit the full page fault form and wait for the fault list it redirects to."""
        self.click_css('form button[type=submit].btn-primary')
        self.wait_for_element('#listable-table-fault_list')
        self.wait_for_ajax()


class TestCreateFault(FaultsSeleniumTestCase):

    def test_choosing_a_unit_enables_only_that_units_modalities(self):
        """Choosing a unit must leave only that unit's modalities choosable.

        Otherwise a fault could be recorded against a beam the machine does
        not have, and fault trends by modality would be wrong.
        """
        self.open_create_form()

        # The blank option is always there: modality is optional.
        self.choose_unit('Linac Two')
        assert self.enabled_options('id_fault-modality') == ['---------', 'Proton']

        self.choose_unit('Linac One')
        assert sorted(self.enabled_options('id_fault-modality')) == ['---------', '6MV Photon', '9MeV Electron']

        # The select2 dropdown, which is what a person actually clicks, agrees:
        # faults.css hides the disabled options altogether.
        self.open_select2('id_fault-modality')
        self.wait.until(lambda d: self._open_select2_option('6MV Photon'))
        assert sorted(self.select2_results()) == ['---------', '6MV Photon', '9MeV Electron']
        self.close_select2()
        assert self.javascript_errors() == []

    def test_new_fault_is_saved_with_its_unit_modality_types_and_related_service_event(self):
        """A fault filled in on the form must be saved with exactly what was chosen.

        Also checks that the related service event search only finds events on
        the chosen unit, and that changing the unit drops an event picked for
        the old one.
        """
        sl_utils.create_service_event_status(is_default=True)
        se_one = sl_utils.create_service_event(
            unit_service_area=sl_utils.create_unit_service_area(unit=self.unit),
            user_created_by=self.user, problem_description='Linac One leaf problem',
        )
        se_two = sl_utils.create_service_event(
            unit_service_area=sl_utils.create_unit_service_area(unit=self.other_unit),
            user_created_by=self.user, problem_description='Linac Two couch problem',
        )

        self.open_create_form()

        self.choose_unit('Linac Two')
        self.open_select2('id_fault-related_service_events')
        self.wait.until(lambda d: self._open_select2_option('Linac Two couch problem', exact=False))
        assert not any('Linac One' in r for r in self.select2_results())
        self.click_element(self._open_select2_option('Linac Two couch problem', exact=False))
        self.wait.until(lambda d: self.value_of('id_fault-related_service_events') == [str(se_two.pk)])

        self.choose_unit('Linac One')
        assert not self.value_of('id_fault-related_service_events')

        self.open_select2('id_fault-related_service_events')
        option = self.wait.until(lambda d: self._open_select2_option('Linac One leaf problem', exact=False))
        assert not any('Linac Two' in r for r in self.select2_results())
        self.click_element(option)
        self.wait.until(lambda d: self.value_of('id_fault-related_service_events') == [str(se_one.pk)])

        self.select2_choose('id_fault-modality', '9MeV Electron')
        self.choose_fault_type('ML', 'MLC-12')
        self.choose_fault_type('GAN', 'GANTRY-3')
        descriptions = self.wait_for_visible('#fault-type-descriptions')
        assert 'Leaf will not move' in descriptions.text
        assert 'Gantry stalls' in descriptions.text
        self.enter_occurred('2026-10-05 09:15')
        self.type_into('id_fault-comment', 'Leaf 12 stuck during morning QC')

        self.save_fault_form()

        fault = models.Fault.objects.get()
        assert fault.unit == self.unit
        assert fault.modality == self.electron
        assert set(fault.fault_types.all()) == {self.mlc, self.gantry}
        assert list(fault.related_service_events.all()) == [se_one]
        assert local_minute(fault.occurred) == (2026, 10, 5, 9, 15)
        assert fault.created_by == self.user
        assert [c.comment for c in Comment.objects.for_model(fault)] == ['Leaf 12 stuck during morning QC']
        assert not fault.faultreviewinstance_set.exists()

    def test_modality_can_be_cleared_after_one_was_chosen(self):
        """Modality is optional, so a modality picked by mistake must be removable again."""
        self.open_create_form()
        self.choose_unit('Linac One')
        self.select2_choose('id_fault-modality', '6MV Photon')
        assert self.value_of('id_fault-modality') == str(self.photon.pk)

        self.open_select2('id_fault-modality')
        self.wait.until(lambda d: self._open_select2_option('6MV Photon'))
        # faults.css hides disabled options, so a disabled blank option is simply not there.
        assert '---------' in self.select2_results()
        self.click_element(self._open_select2_option('---------'))
        self.wait.until(lambda d: self.value_of('id_fault-modality') in ('', None))

    def test_changing_unit_keeps_a_modality_the_new_unit_has_and_clears_one_it_lacks(self):
        """Switching unit clears a modality only when the new unit does not have it.

        If this fails, a fault can be saved against a beam the new unit does not
        have, or a valid choice is thrown away for no reason.
        """
        self.other_unit.modalities.add(self.photon)
        self.open_create_form()
        self.choose_unit('Linac One')
        self.select2_choose('id_fault-modality', '9MeV Electron')

        self.choose_unit('Linac Two')
        assert self.value_of('id_fault-modality') in ('', None)

        self.select2_choose('id_fault-modality', '6MV Photon')
        self.choose_unit('Linac One')
        assert self.value_of('id_fault-modality') == str(self.photon.pk)

    def test_new_fault_type_typed_into_the_box_is_created_with_the_fault(self):
        """A code that does not exist yet must be offered as *code* and created when the fault is saved.

        Uses a lower case code because the lookup lower-cases what is typed.
        """
        self.open_create_form()
        self.choose_unit('Linac One')

        self.choose_fault_type('cbct drift', '*cbct drift*', exact=True)
        self.wait_for_text('#fault-type-descriptions', 'cbct drift')
        assert self.value_of('id_fault-fault_types_field') == ['newft:cbct drift']
        assert not models.FaultType.objects.filter(code='cbct drift').exists()

        self.enter_occurred('2026-10-05 09:15')
        self.save_fault_form()

        new_type = models.FaultType.objects.get(code='cbct drift')
        fault = models.Fault.objects.get()
        assert list(fault.fault_types.all()) == [new_type]
        assert models.FaultType.objects.count() == 3

    def test_new_fault_type_is_not_offered_without_permission_to_add_fault_types(self):
        """A user who may log faults but not add fault types must only be offered existing types."""
        logger = create_user(is_superuser=False, uname='therapist', pwd=self.password)
        logger.groups.add(self.group)
        logger.user_permissions.add(
            Permission.objects.get(codename='add_fault'),
            Permission.objects.get(codename='view_fault'),
        )

        self.open_create_form(user=logger)
        self.choose_unit('Linac One')

        self.click_css('#id_fault-fault_types_field ~ .select2 .select2-search__field')
        self.driver.switch_to.active_element.send_keys('cbct')
        self.wait_for_visible('.select2-container--open .select2-results__message')
        self.wait_for_ajax()
        assert not any('cbct' in r for r in self.select2_results())
        self.close_select2()

        # An existing type is still found by the same box.
        self.choose_fault_type('ML', 'MLC-12')
        assert self.value_of('id_fault-fault_types_field') == ['MLC-12']


class TestLogFaultFromPerformQC(FaultsSeleniumTestCase):
    """The "Log Fault" window on the Perform QC page, which saves by ajax."""

    def setUp(self):
        super().setUp()
        qa_utils.create_status(name='Unreviewed', slug='unreviewed', is_default=True)
        test = qa_utils.create_test(name='Output')
        qa_utils.create_test_list_membership(self.test_list, test)

    def open_fault_modal(self):
        self.login()
        self.open(reverse('perform_qa', kwargs={'pk': self.utc.pk}))
        self.wait_for_element('#perform-qa-table')
        self.wait_for_ajax()
        self.click_css('a.fault-modal-toggle')
        self.wait_for_visible('#fault-modal #save_fault')
        self.wait_for_visible('#fault-modal #id_fault-unit ~ .select2')

    def test_fault_logged_in_the_window_is_saved_and_the_window_closes(self):
        """Logging a fault from Perform QC must save it for the unit being tested and close the window."""
        self.open_fault_modal()
        # The unit being tested is chosen already.
        assert self.value_of('id_fault-unit') == str(self.unit.pk)
        assert sorted(self.enabled_options('id_fault-modality')) == ['---------', '6MV Photon', '9MeV Electron']

        self.select2_choose('id_fault-modality', '6MV Photon')
        self.choose_fault_type('ML', 'MLC-12')
        self.type_into('id_fault-comment', 'Interlock during output check')
        self.click_css('#save_fault')

        message = self.wait_for_visible('#modal-fault-message .success-message')
        fault = models.Fault.objects.get()
        assert 'Fault ID %d was created' % fault.pk in message.text
        # faults.js closes the window two seconds after a successful save.
        self.wait_for_invisible('#fault-modal')

        assert fault.unit == self.unit
        assert fault.modality == self.photon
        assert list(fault.fault_types.all()) == [self.mlc]
        assert fault.created_by == self.user
        assert [c.comment for c in Comment.objects.for_model(fault)] == ['Interlock during output check']
        # Still on the Perform QC page, with nothing lost.
        assert self.driver.current_url.endswith(reverse('perform_qa', kwargs={'pk': self.utc.pk}))

    def test_fault_window_shows_errors_and_saves_once_they_are_fixed(self):
        """Saving without a fault type must show the error in the window, save nothing, and keep it open."""
        self.open_fault_modal()

        self.click_css('#save_fault')
        error = self.wait_for_visible('#fault-modal .has-error .error-message')
        assert 'This field is required' in error.text
        form_group = error.find_element(By.XPATH, './ancestor::div[contains(@class, "form-group")][1]')
        assert form_group.find_elements(By.ID, 'id_fault-fault_types_field')
        assert not models.Fault.objects.exists()
        assert self.driver.find_element(By.ID, 'fault-modal').is_displayed()

        self.choose_fault_type('GAN', 'GANTRY-3')
        self.click_css('#save_fault')
        self.wait_for_visible('#modal-fault-message .success-message')
        # The old error is cleared before the second save.
        assert not self.driver.find_elements(By.CSS_SELECTOR, '#fault-modal .error-message')
        self.wait_for_invisible('#fault-modal')
        assert list(models.Fault.objects.get().fault_types.all()) == [self.gantry]


class TestReviewing(FaultsSeleniumTestCase):

    def make_review_group(self, required=True):
        physics = Group.objects.create(name='Physics')
        self.user.groups.add(physics)
        return f_utils.create_fault_review_group(group=physics, required=required)

    def test_bulk_acknowledge_reviews_all_selected_faults(self):
        """Select all on the unreviewed list must summarise, then review, every unreviewed fault.

        The summary groups faults by type and unit so the reviewer can see
        what they are signing off before they confirm.
        """
        first = self.create_fault()
        second = self.create_fault()
        other = self.create_fault(unit=self.other_unit, fault_type=self.gantry)
        already = self.create_fault()
        f_utils.create_fault_review(fault=already, review_group=False, reviewed_by=self.user)

        self.login()
        self.open(reverse('fault_list_unreviewed'))
        table = '#listable-table-fault_list_unreviewed tbody'
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, table + ' input.test-selected')) == 3)

        toggle = [el for el in self.driver.find_elements(By.CSS_SELECTOR, 'input.test-selected-toggle')
                  if el.is_displayed()][0]
        self.click_element(toggle)
        boxes = self.driver.find_elements(By.CSS_SELECTOR, table + ' input.test-selected')
        assert all(box.is_selected() for box in boxes)

        self.click_css('#submit-review')
        self.wait_for_visible('#bulk-review-modal #confirm-update')
        rows = [
            [td.text.strip() for td in tr.find_elements(By.TAG_NAME, 'td')]
            for tr in self.driver.find_elements(By.CSS_SELECTOR, '#instance-summary tbody tr')
        ]
        assert rows == [['MLC-12', 'Linac One', '2'], ['GANTRY-3', 'Linac Two', '1']]

        with self.wait_for_page_load():
            self.click_css('#confirm-update')
        self.wait_for_text('.content-header', 'Successfully reviewed 3 faults')
        self.wait_for_ajax()

        for fault in (first, second, other):
            review = fault.faultreviewinstance_set.get()
            assert review.reviewed_by == self.user
        assert not models.Fault.objects.unreviewed().exists()

    def test_bulk_acknowledge_reviews_only_the_ticked_faults(self):
        """Ticking two of three faults summarises and reviews those two, and leaves the third unreviewed.

        If this fails, a reviewer signs off faults they never looked at.
        """
        first = self.create_fault()
        second = self.create_fault(unit=self.other_unit, fault_type=self.gantry)
        skipped = self.create_fault()

        self.login()
        self.open(reverse('fault_list_unreviewed'))
        table = '#listable-table-fault_list_unreviewed tbody'
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, table + ' input.test-selected')) == 3)
        for fault in (first, second):
            self.click_css('%s input.test-selected[data-fault="%d"]' % (table, fault.pk))

        self.click_css('#submit-review')
        self.wait_for_visible('#bulk-review-modal #confirm-update')
        rows = [
            [td.text.strip() for td in tr.find_elements(By.TAG_NAME, 'td')]
            for tr in self.driver.find_elements(By.CSS_SELECTOR, '#instance-summary tbody tr')
        ]
        assert sorted(rows) == [['GANTRY-3', 'Linac Two', '1'], ['MLC-12', 'Linac One', '1']]

        with self.wait_for_page_load():
            self.click_css('#confirm-update')
        self.wait_for_text('.content-header', 'Successfully reviewed 2 faults')

        assert first.faultreviewinstance_set.get().reviewed_by == self.user
        assert second.faultreviewinstance_set.get().reviewed_by == self.user
        assert not skipped.faultreviewinstance_set.exists()

    def test_reviewer_chosen_on_the_edit_form_is_saved(self):
        """Choosing a reviewer for a required review group on the edit form must record that review."""
        frg = self.make_review_group(required=True)
        fault = self.create_fault(modality=self.photon)

        self.open_edit_form(fault)
        assert self.value_of('id_fault-modality') == str(self.photon.pk)
        self.select2_choose('id_review-form-0-reviewed_by', 'Pat Physicist')
        self.save_fault_form()

        # Saving the edit form must not lose what it did not change.
        fault.refresh_from_db()
        assert fault.modality == self.photon

        review = models.FaultReviewInstance.objects.get()
        assert review.fault == fault
        assert review.reviewed_by == self.user
        assert review.fault_review_group == frg
        assert fault.review_complete()

    def test_edit_form_refuses_to_save_without_a_required_reviewer(self):
        """A required review group left without a reviewer must stop the save and say why.

        Otherwise a site that demands sign-off from a group could end up with
        faults changed but never reviewed by that group.
        """
        self.make_review_group(required=True)
        fault = self.create_fault()

        self.open_edit_form(fault)
        self.select2_choose('id_fault-modality', '9MeV Electron')
        self.click_css('form button[type=submit].btn-primary')

        error = self.wait_for_visible('.has-error .error-message')
        assert 'This field is required' in error.text
        form_group = error.find_element(By.XPATH, './ancestor::div[contains(@class, "form-group")][1]')
        assert form_group.find_element(By.ID, 'id_review-form-0-group').get_attribute('value') == 'Physics'
        fault.refresh_from_db()
        assert fault.modality is None
        assert not models.FaultReviewInstance.objects.exists()

    def test_acknowledging_from_the_details_page_records_the_review(self):
        """"Acknowledge This Fault" must review the fault as the current user and say so on the page."""
        fault = self.create_fault()

        self.login()
        self.open(reverse('fault_details', kwargs={'pk': fault.pk}))
        button = self.wait_for_visible('#review-fault')
        assert 'Acknowledge This Fault' in button.text

        with self.wait_for_page_load():
            self.click_element(button)
        self.wait_for_text('.content-header', 'Successfully acknowledged')

        review = models.FaultReviewInstance.objects.get()
        assert review.fault == fault
        assert review.reviewed_by == self.user
        assert 'Unacknowledge This Fault' in self.wait_for_visible('#review-fault').text
        assert 'Pat Physicist @' in self.page_text()

    def test_unacknowledging_from_the_details_page_removes_the_review(self):
        """"Unacknowledge This Fault" must remove the review, putting the fault back on the unreviewed list."""
        fault = self.create_fault()
        f_utils.create_fault_review(fault=fault, review_group=False, reviewed_by=self.user)

        self.login()
        self.open(reverse('fault_details', kwargs={'pk': fault.pk}))
        button = self.wait_for_visible('#review-fault')
        assert 'Unacknowledge This Fault' in button.text

        with self.wait_for_page_load():
            self.click_element(button)
        self.wait_for_text('.content-header', 'Successfully unacknowledged')

        assert not models.FaultReviewInstance.objects.exists()
        assert list(models.Fault.objects.unreviewed()) == [fault]
        assert 'Acknowledge This Fault' in self.wait_for_visible('#review-fault').text


class TestFaultDetails(FaultsSeleniumTestCase):

    def test_comment_posted_on_the_details_page_is_saved_and_shown(self):
        """A comment typed on the details page must be posted by ajax, saved, and shown without a reload."""
        fault = self.create_fault()

        self.login()
        self.open(reverse('fault_details', kwargs={'pk': fault.pk}))
        post = self.wait_for_visible('#post-comment')
        assert not post.is_enabled()

        self.type_into('id_comment', 'Vendor called, part on order')
        self.wait.until(lambda d: d.find_element(By.ID, 'post-comment').is_enabled())
        self.click_css('#post-comment')
        self.wait_for_text('#comments', 'Vendor called, part on order')
        self.wait_for_ajax()

        comment = Comment.objects.for_model(fault).get()
        assert comment.comment == 'Vendor called, part on order'
        assert comment.user == self.user
        # The box is emptied and the button disabled again, ready for the next comment.
        assert self.value_of('id_comment') == ''
        assert not self.driver.find_element(By.ID, 'post-comment').is_enabled()

    def test_other_occurrences_heading_names_the_fault_type(self):
        """The "Other Occurrences" box must say which fault type it is listing other occurrences of."""
        fault = self.create_fault()
        self.create_fault(unit=self.other_unit)

        self.login()
        self.open(reverse('fault_details', kwargs={'pk': fault.pk}))
        self.wait_for_element('#listable-table-fault_details tbody')
        heading = [
            h for h in self.driver.find_elements(By.CSS_SELECTOR, 'h3.box-title')
            if 'Other Occurrences' in h.text
        ][0]

        assert 'MLC-12' in heading.text

    def test_deleting_a_fault_from_its_confirmation_page_removes_it(self):
        """Delete on the details page, then confirm, must remove the fault and its comments."""
        fault = self.create_fault()
        kept = self.create_fault(unit=self.other_unit)
        Comment.objects.create(
            content_object=fault, user=self.user, comment='Doomed', site_id=1, submit_date=timezone.now(),
        )

        self.login()
        self.open(reverse('fault_details', kwargs={'pk': fault.pk}))
        with self.wait_for_page_load():
            self.click_element(self.wait_for_visible('a.btn-danger[href="%s"]' % reverse(
                'fault_delete', kwargs={'pk': fault.pk})))
        self.wait_for_text('.box-body form', 'permanently delete')
        with self.wait_for_page_load():
            self.click_css('form button[type=submit].btn-danger')
        self.wait_for_element('#listable-table-fault_list')
        self.wait_for_ajax()

        assert list(models.Fault.objects.all()) == [kept]
        assert not Comment.objects.filter(comment='Doomed').exists()
        assert self.driver.current_url.endswith(reverse('fault_list'))

    def test_deleting_a_fault_confirms_it_with_a_message(self):
        """After deleting a fault the user must be told which fault was deleted."""
        fault = self.create_fault()
        fault_id = fault.pk

        self.login()
        self.open(reverse('fault_delete', kwargs={'pk': fault_id}))
        with self.wait_for_page_load():
            self.click_css('form button[type=submit].btn-danger')
        self.wait_for_element('#listable-table-fault_list')
        assert not models.Fault.objects.exists()

        assert 'Successfully deleted Fault %d' % fault_id in self.page_text()


class TestAttachments(FaultsSeleniumTestCase):

    def setUp(self):
        super().setUp()
        # Keep uploaded files out of the repository's media directory.
        self.media_root = tempfile.mkdtemp(prefix='qatrack-faults-selenium-')
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media_settings = self.settings(
            MEDIA_ROOT=self.media_root, UPLOAD_ROOT=os.path.join(self.media_root, 'uploads')
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def test_file_chosen_on_the_create_form_is_attached_to_the_fault(self):
        """A file chosen in the attachments box must be listed on the form and stored with the new fault."""
        path = os.path.join(self.media_root, 'interlock_log.txt')
        with open(path, 'w') as f:
            f.write('MLC interlock 12:03')

        self.open_create_form()
        self.choose_unit('Linac One')
        self.choose_fault_type('ML', 'MLC-12')
        # The real file input is hidden behind a styled "Browse" label; show it
        # so WebDriver can hand it a file, as the operating system dialog would.
        file_input = self.driver.find_element(By.ID, 'id_fault-attachments')
        self.driver.execute_script("arguments[0].style.display = 'block';", file_input)
        file_input.send_keys(path)
        self.wait_for_text('#attachment-names', 'interlock_log.txt')

        self.save_fault_form()

        attachment = Attachment.objects.get()
        assert attachment.fault == models.Fault.objects.get()
        assert attachment.label == 'interlock_log.txt'
        assert attachment.created_by == self.user
        with attachment.attachment.open('r') as f:
            assert f.read() == 'MLC interlock 12:03'

    def test_ticking_delete_on_the_edit_form_removes_only_that_attachment(self):
        """Ticking one attachment's delete box on edit must remove that attachment and keep the others."""
        fault = self.create_fault()
        doomed = Attachment.objects.create(
            attachment=SimpleUploadedFile('old.txt', b'old'), label='old.txt', fault=fault, created_by=self.user,
        )
        kept = Attachment.objects.create(
            attachment=SimpleUploadedFile('keep.txt', b'keep'), label='keep.txt', fault=fault, created_by=self.user,
        )

        self.open_edit_form(fault)
        self.click_css('#attach-%d-DELETE' % doomed.pk)
        assert self.value_of('id_fault-attachments_delete_ids') == str(doomed.pk)
        self.save_fault_form()

        assert list(Attachment.objects.all()) == [kept]
        assert list(fault.fault_types.all()) == [self.mlc]

    def test_ticking_two_delete_boxes_removes_both_attachments(self):
        """Two attachments ticked for deletion are both removed (the form sends them as "5,6")."""
        fault = self.create_fault()
        doomed = [
            Attachment.objects.create(
                attachment=SimpleUploadedFile(name, b'old'), label=name, fault=fault, created_by=self.user,
            ) for name in ('one.txt', 'two.txt')
        ]

        self.open_edit_form(fault)
        for attachment in doomed:
            self.click_css('#attach-%d-DELETE' % attachment.pk)
        self.save_fault_form()

        assert not Attachment.objects.exists()

    def test_attachments_of_other_records_are_never_deleted(self):
        """Only this record's own attachments can be deleted, whatever ids the browser sends.

        The delete ids travel in a hidden field. If this fails, an edited request can
        delete anyone's attachments, from any record.
        """
        fault = self.create_fault()
        other = Attachment.objects.create(
            attachment=SimpleUploadedFile('other.txt', b'other'), label='other.txt',
            fault=self.create_fault(unit=self.other_unit), created_by=self.user,
        )

        self.open_edit_form(fault)
        self.driver.execute_script(
            "document.getElementById('id_fault-attachments_delete_ids').value = arguments[0];", str(other.pk)
        )
        self.save_fault_form()

        assert list(Attachment.objects.all()) == [other]


class TestFaultListFilters(FaultsSeleniumTestCase):

    table = '#listable-table-fault_list tbody'

    def setUp(self):
        super().setUp()
        self.mlc_fault = self.create_fault(unit=self.unit, fault_type=self.mlc)
        self.gantry_fault = self.create_fault(unit=self.other_unit, fault_type=self.gantry)

    def open_list(self):
        self.login()
        self.open(reverse('fault_list'))
        self.wait_for_text(self.table, 'GANTRY-3')
        self.wait_for_text(self.table, 'MLC-12')

    def header_cell(self, title):
        """The filter cell under the column titled `title`."""
        headers = self.driver.find_elements(By.CSS_SELECTOR, '#listable-table-fault_list thead tr:first-child th')
        titles = [h.text.strip() for h in headers]
        idx = titles.index(title) + 1
        return '#listable-table-fault_list thead tr:nth-child(2) th:nth-child(%d)' % idx

    def table_text(self):
        return self.driver.find_element(By.CSS_SELECTOR, self.table).text

    def test_filtering_by_unit_narrows_the_list(self):
        """Choosing a unit in the Unit column filter must list only that unit's faults."""
        self.open_list()

        cell = self.header_cell('Unit')
        self.click_css(cell + ' button.multiselect')
        self.click_element(self.wait.until(lambda d: d.find_element(
            By.XPATH, '//ul[contains(@class, "multiselect-container")]//label[normalize-space()="Linac Two"]'
        )))
        self.wait.until(lambda d: 'MLC-12' not in self.table_text())
        self.wait_for_ajax()

        text = self.table_text()
        assert 'GANTRY-3' in text
        assert 'Linac One' not in text

    def test_filtering_by_fault_type_narrows_the_list(self):
        """Typing a code in the Fault Types column filter must list only faults of that type."""
        self.open_list()

        cell = self.header_cell('Fault Types')
        self.click_css(cell + ' input')
        self.driver.switch_to.active_element.send_keys('MLC')
        self.wait.until(lambda d: 'GANTRY-3' not in self.table_text())
        self.wait_for_ajax()

        text = self.table_text()
        assert 'MLC-12' in text
        assert 'Linac One' in text


class TestFaultDatesAndTimes(FaultsSeleniumTestCase):
    """When a fault occurred is shown and saved again exactly, whatever zone the workstation is in."""

    def test_late_evening_occurred_time_is_shown_again_and_unchanged_by_saving_again(self):
        """22:30 on 5 Oct is shown as such on the edit page, and saving the edit form keeps it.

        If this fails, editing a fault (to add a reviewer, say) moves it to another
        day, out of the reports and trends it belongs to.
        """
        fault = self.create_fault(occurred=aware(2026, 10, 5, 22, 30))

        self.open_edit_form(fault)
        assert self.value_of('id_fault-occurred') == '2026-10-05 22:30'
        self.save_fault_form()

        fault.refresh_from_db()
        assert local_minute(fault.occurred) == (2026, 10, 5, 22, 30)

    def test_opening_the_empty_occurred_box_fills_in_now_on_a_workstation_in_another_zone(self):
        """Opening the picker on an empty "occurred" box fills in the server's "now", not the workstation's.

        If this fails, faults logged from a computer set to another zone are filed hours out.
        """
        self.use_browser_timezone('Asia/Tokyo')
        before = timezone.localtime().replace(second=0, microsecond=0)
        self.open_create_form()
        self.click_css('#id_fault-occurred')
        self.wait_until(lambda: self.value_of('id_fault-occurred'), message='opening the picker filled in nothing')
        after = timezone.localtime()
        shown = timezone.make_aware(timezone.datetime.strptime(self.value_of('id_fault-occurred'), '%Y-%m-%d %H:%M'))
        assert before <= shown <= after, 'the picker filled in %s, opened between %s and %s' % (shown, before, after)
