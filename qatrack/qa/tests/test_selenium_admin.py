"""Browser tests for the parts of the Django admin that depend on JavaScript.

The admin pages for QC configuration do a lot in the browser: the test form
shows and hides fields as the test type changes and swaps the calculation
procedure box for a code editor, test list members are dragged into order,
choosing a unit service area on a service event schedule narrows the
templates offered, and test packs are read from a file in the browser before
they are posted. A plain Django test client test can post a form but can not
prove any of that works, which is why these tests use a browser.

Every test waits for the page the server sends back after a save before it
reads the database, and then checks what was actually stored - a success
message on its own proves very little.
"""

import json
import os
import shutil
import tempfile

import pytest
from django.contrib.auth.models import Group
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.ui import Select

from qatrack.notifications import models as n_models
from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log import models as sl_models
from qatrack.service_log.tests import utils as sl_utils


class AdminSeleniumMixin:
    """Helpers for driving Django admin pages. Mix into a `SeleniumTestCase`."""

    def choose_option(self, el_id, text):
        """Pick the option showing `text` in a plain (not select2) <select>."""
        Select(self.wait_for_visible('#%s' % el_id)).select_by_visible_text(text)

    def move_to_chosen(self, field, *texts):
        """In a Django 'filter horizontal' widget, move the options showing `texts` to the chosen box."""
        for text in texts:
            option = self.wait_for_element('#id_%s_from option[title="%s"]' % (field, text))
            self.click_element(option)
            self.click_css('#id_%s_add_link' % field)
            self.wait_for_element('#id_%s_to option[title="%s"]' % (field, text))

    # -- saving ------------------------------------------------------------------------------------

    def submit_and_wait(self, button_css):
        """Click a submit button and wait until the browser has left the page it was on."""
        old_page = self.driver.find_element(By.TAG_NAME, 'html')
        self.click_element(self.driver.find_element(By.CSS_SELECTOR, button_css))
        self.wait.until(staleness_of(old_page))

    def admin_errors(self):
        """The error messages the admin is showing on the current page."""
        return [
            e.text for e in self.driver.find_elements(By.CSS_SELECTOR, '.errornote, .errorlist li') if e.text.strip()
        ]

    def save(self, button='_save'):
        """Press one of the admin's save buttons and wait for the success message on the next page.

        If the admin refuses the form instead, fail with the errors it showed,
        rather than with a bare timeout.
        """
        self.submit_and_wait('input[name="%s"]' % button)
        self.wait.until(
            lambda d: d.find_elements(By.CSS_SELECTOR, 'ul.messagelist li.success') or self.admin_errors()
        )
        errors = self.admin_errors()
        assert not errors, 'the admin refused the form: %r' % errors

    def success_message(self):
        return self.driver.find_element(By.CSS_SELECTOR, 'ul.messagelist li.success').text


class AdminTestCase(AdminSeleniumMixin, SeleniumTestCase):
    """The admin helpers above, plus a QC category most tests need. Tests log in with `load_admin()`."""

    def setUp(self):
        super().setUp()
        self.category = utils.create_category(name='Dosimetry', slug='dosimetry', description='Dose checks')


class TestTestAdmin(AdminTestCase):
    """The test form shows only the fields that matter for the chosen test type (test_admin.js)."""

    # Each field row the type toggles, and the types it should be shown for.
    TOGGLED_FIELDS = {
        'formatting': {models.CONSTANT, models.COMPOSITE, models.SIMPLE, models.WRAPAROUND},
        'choices': {models.MULTIPLE_CHOICE},
        'constant_value': {models.CONSTANT},
        'wrap_low': {models.WRAPAROUND},
        'flag_when': {models.BOOLEAN},
        'hidden': {models.CONSTANT, models.COMPOSITE, models.STRING_COMPOSITE},
        'display_image': {models.UPLOAD, models.COMPOSITE, models.STRING_COMPOSITE},
        'skip_without_comment': {t for t, _ in models.TEST_TYPE_CHOICES} - {
            models.CONSTANT, models.COMPOSITE, models.STRING_COMPOSITE,
        },
        'calculation_procedure': {t for t, _ in models.TEST_TYPE_CHOICES} - {models.CONSTANT},
        'chart_visibility': {t for t, _ in models.TEST_TYPE_CHOICES} - {
            models.STRING, models.STRING_COMPOSITE, models.DATE, models.DATETIME, models.UPLOAD,
        },
    }

    def open_add_test(self):
        self.load_admin()
        self.open('/admin/qa/test/add/')
        self.wait_for_element('#id_type ~ .select2')
        self.wait_for_element('#calc-procedure-editor')

    def shown_fields(self):
        return {f for f in self.TOGGLED_FIELDS if self.is_shown('.form-row.field-%s' % f)}

    def test_changing_type_shows_only_that_types_fields(self):
        """Each test type shows the fields it uses and hides the rest.

        If this broke, a person could not enter the choices for a multiple
        choice test or the value of a constant, or would be shown options that
        silently do nothing for the type they picked.
        """
        self.open_add_test()

        for test_type, label in models.TEST_TYPE_CHOICES:
            self.select2_choose('id_type', label)
            expected = {f for f, types in self.TOGGLED_FIELDS.items() if test_type in types}
            self.wait.until(lambda d: self.shown_fields() == expected, message=test_type)

    def test_calculation_procedure_is_edited_in_a_code_editor(self):
        """The calculation procedure box is replaced by a code editor whose text is saved with the test.

        The editor is only a view; the hidden text box is what the form posts,
        so the editor must copy its text back before the form is sent.
        """
        self.open_add_test()
        self.type_into('id_name', 'Output ratio')
        self.type_into('id_slug', 'output_ratio')
        self.select2_choose('id_category', self.category.name)
        self.select2_choose('id_type', 'Composite')

        assert self.is_shown('#calc-procedure-editor')
        assert not self.is_shown('#id_calculation_procedure')

        self.click_css('#calc-procedure-editor')
        self.driver.switch_to.active_element.send_keys('output_ratio = 1.5 * 2')
        self.click_css('#id_name')
        self.save()

        test = models.Test.objects.get(slug='output_ratio')
        assert test.type == models.COMPOSITE
        assert test.calculation_procedure.strip() == 'output_ratio = 1.5 * 2'

        # Constants have no procedure, so the editor goes away with the box.
        self.open('/admin/qa/test/add/')
        self.wait_for_element('#id_type ~ .select2')
        self.select2_choose('id_type', 'Constant')
        self.wait.until(lambda d: not self.is_shown('#calc-procedure-editor'))

    def save_new_test(self, name, type_label, procedure=None):
        self.open_add_test()
        assert self.is_checked('id_chart_visibility'), 'new tests start out shown in charts'
        self.type_into('id_name', name)
        self.type_into('id_slug', name)
        self.select2_choose('id_category', self.category.name)
        self.select2_choose('id_type', type_label)
        if procedure:
            self.click_css('#calc-procedure-editor')
            self.driver.switch_to.active_element.send_keys(procedure)
            self.click_css('#id_name')
        self.save()
        return models.Test.objects.get(slug=name)

    def test_string_composite_test_is_saved_hidden_from_charts(self):
        """A String Composite test can not be charted, so choosing that type unticks 'visible in charts'."""
        test = self.save_new_test('beam_notes', 'String Composite/JSON', procedure="beam_notes = 'ok'")

        assert test.type == models.STRING_COMPOSITE
        assert not test.chart_visibility

    def test_string_test_is_saved_hidden_from_charts(self):
        """A String test can not be charted either, so it too must be saved hidden from charts."""
        test = self.save_new_test('couch_comment', 'String')

        assert test.type == models.STRING
        assert not test.chart_visibility


class TestTestListAdmin(AdminTestCase):
    """Test list members and sublists, which share one drag-and-drop table (m2m_drag_admin_testlist.js)."""

    def setUp(self):
        super().setUp()
        self.alpha = utils.create_test(name='alpha', category=self.category)
        self.beta = utils.create_test(name='beta', category=self.category)
        self.gamma = utils.create_test(name='gamma', category=self.category)
        self.test_list = utils.create_test_list('Morning Output')
        self.test_list.slug = 'morning_output'
        self.test_list.save()
        for order, test in enumerate([self.alpha, self.beta, self.gamma]):
            utils.create_test_list_membership(self.test_list, test, order=order)

    def open_change_page(self):
        self.load_admin()
        self.open('/admin/qa/testlist/%d/change/' % self.test_list.pk)
        self.wait_for_element('#member-container tbody tr.has_original')

    def member_row(self, test):
        return self.driver.find_element(
            By.XPATH,
            '//div[@id="member-container"]//tr[.//input[starts-with(@id, "id_testlistmembership_set") '
            'and contains(@class, "vForeignKeyRawIdAdminField") and @value="%d"]]' % test.pk,
        )

    def shown_test_order(self):
        """Test ids in the order their rows appear in the members table."""
        return self.driver.execute_script(
            "return $('#member-container tbody tr input[id^=id_testlistmembership_set][id$=-test]')"
            "  .map(function() { return this.value; }).get().filter(function(v) { return v; });"
        )

    def orders(self):
        return dict(
            models.TestListMembership.objects.filter(test_list=self.test_list).values_list('test__name', 'order')
        )

    def test_dragging_a_member_to_the_top_saves_the_new_order(self):
        """Dragging the last test above the first saves it first, and the others move down one."""
        self.open_change_page()
        assert self.shown_test_order() == [str(t.pk) for t in (self.alpha, self.beta, self.gamma)]

        source = self.member_row(self.gamma).find_element(By.CSS_SELECTOR, 'td.field-macro_name')
        target = self.member_row(self.alpha)
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
        # jQuery UI sortable needs to see the mouse move in steps, not jump.
        actions = ActionChains(self.driver).click_and_hold(source)
        offset = target.location['y'] - source.location['y'] - 10
        for _ in range(10):
            actions.move_by_offset(0, offset / 10)
        actions.release().perform()

        expected = [str(t.pk) for t in (self.gamma, self.alpha, self.beta)]
        self.wait.until(lambda d: self.shown_test_order() == expected)
        self.save()

        assert self.orders() == {'gamma': 0, 'alpha': 1, 'beta': 2}

    def test_new_member_and_sublist_are_saved_after_the_existing_members(self):
        """A test and a sublist typed into the empty rows are saved, in order, after the existing tests."""
        child = utils.create_test_list('Couch Checks')
        utils.create_test_list_membership(child, utils.create_test(name='couch', category=self.category))
        delta = utils.create_test(name='delta', category=self.category)

        self.open_change_page()
        self.type_into('id_testlistmembership_set-3-test', str(delta.pk))
        self.type_into('id_children-0-child', str(child.pk))
        self.save()

        assert self.orders() == {'alpha': 0, 'beta': 1, 'gamma': 2, 'delta': 3}
        sublist = models.Sublist.objects.get(parent=self.test_list)
        assert sublist.child == child
        assert sublist.order == 4
        # The sublist's own tests are not copied into the parent.
        assert not models.TestListMembership.objects.filter(test_list=self.test_list, test__name='couch').exists()

    def test_typing_a_test_id_shows_the_tests_name(self):
        """After typing a test's id into a member row, the test's name is shown beside it.

        Without it a person adding tests to a list sees only bare numbers and
        can not tell whether they typed the right one.
        """
        delta = utils.create_test(name='delta', category=self.category)
        self.open_change_page()

        self.type_into('id_testlistmembership_set-3-test', str(delta.pk))
        self.click_css('#id_name')
        self.wait_for_ajax()
        self.wait_for_text('#testlistmembership_set-3-test_dynamic_raw_id_label', 'delta')

    def test_test_list_changelist_offers_only_working_actions(self):
        """The test list list page loads, lists the test list, and offers only actions that exist.

        `TestListAdmin.actions` names `export_test_lists`, which has no
        method. Django drops it quietly rather than erroring, so the page
        must still work and must not offer an action that would fail.
        """
        self.load_admin()
        self.browser_log()  # forget whatever earlier pages logged
        self.open('/admin/qa/testlist/')
        assert self.driver.find_element(By.LINK_TEXT, 'Morning Output')
        # "Delete selected" is switched off for the whole site, and the
        # missing export action is dropped, which leaves no actions at all.
        assert self.driver.find_elements(By.NAME, 'action') == []
        assert self.driver.find_element(By.LINK_TEXT, 'EXPORT TEST PACK')
        assert self.driver.find_element(By.LINK_TEXT, 'IMPORT TEST PACK')
        assert self.javascript_errors() == []


class TestTestListCycleAdmin(AdminTestCase):

    def test_cycle_saves_its_test_lists_in_the_order_entered(self):
        """Test lists typed into a new cycle are saved as day 1 and day 2 in the order they were entered.

        The order boxes are hidden (m2m_drag_admin.js fills them in when the
        form is sent), so a broken script would save every day with no order.
        """
        first = utils.create_test_list('Day One')
        second = utils.create_test_list('Day Two')

        self.load_admin()
        self.open('/admin/qa/testlistcycle/add/')
        self.type_into('id_name', 'Two Day Cycle')
        assert not self.is_shown('#id_testlistcyclemembership_set-0-order')
        # Entered with the higher id first, so the order can only come from the rows.
        self.type_into('id_testlistcyclemembership_set-0-test_list', str(second.pk))
        self.type_into('id_testlistcyclemembership_set-1-test_list', str(first.pk))
        self.save()

        cycle = models.TestListCycle.objects.get(name='Two Day Cycle')
        assert cycle.slug == 'two-day-cycle'
        memberships = models.TestListCycleMembership.objects.filter(cycle=cycle).order_by('order')
        assert [(m.test_list, m.order) for m in memberships] == [(second, 0), (first, 1)]


class TestReferencesAndTolerancesAdmin(AdminTestCase):
    """Copying references and tolerances between units, and the bulk action on Set References & Tolerances."""

    def setUp(self):
        super().setUp()
        self.source = utils.create_unit(name='Linac One')
        self.dest = utils.create_unit(name='Linac Two')
        self.output = utils.create_test(name='output', category=self.category)
        self.flatness = utils.create_test(name='flatness', category=self.category)
        self.test_list = utils.create_test_list('Monthly Output')
        utils.create_test_list_membership(self.test_list, self.output, order=0)
        utils.create_test_list_membership(self.test_list, self.flatness, order=1)
        utils.create_unit_test_collection(unit=self.source, test_collection=self.test_list)
        utils.create_unit_test_collection(unit=self.dest, test_collection=self.test_list)

        self.tolerance = utils.create_tolerance(tol_type=models.PERCENT, act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.references = {}
        for test, value in [(self.output, 100.0), (self.flatness, 2.5)]:
            uti = models.UnitTestInfo.objects.get(unit=self.source, test=test)
            uti.reference = utils.create_reference(name=test.name, value=value, created_by=self.user)
            uti.tolerance = self.tolerance
            uti.save()
            self.references[test.name] = uti.reference

    def dest_refs_tols(self):
        return {
            uti.test.name: (uti.reference_id, uti.tolerance_id)
            for uti in models.UnitTestInfo.objects.filter(unit=self.dest).select_related('test')
        }

    def preview_copy(self):
        """Fill in the copy form from the Set References & Tolerances page and press Preview."""
        self.load_admin()
        self.click_by_link_text('Set References & Tolerances')
        self.click_by_link_text('COPY REFERENCES & TOLERANCES')
        self.choose_option('id_source_unit', 'Other :: Linac One')
        self.choose_option('id_content_type', 'TestList')
        self.choose_option('id_source_testlist', 'Monthly Output')
        self.choose_option('id_dest_unit', 'Other :: Linac Two')
        self.submit_and_wait('input[type=submit][value=Preview]')
        self.wait_for_visible('button[name=confirm]')
        self.wait_for_visible('button[name=cancel]')
        assert self.dest_refs_tols() == {'output': (None, None), 'flatness': (None, None)}, 'copied before confirming'

        # The preview shows, test by test, what the destination has now and what it will get.
        rows = [
            [td.text.strip() for td in tr.find_elements(By.TAG_NAME, 'td')]
            for tr in self.driver.find_elements(By.CSS_SELECTOR, '#copy-preview tbody tr')
        ]
        assert [(r[0], r[1], r[2]) for r in rows] == [('flatness', '', ''), ('output', '', '')]
        assert all(r[3] and r[4] == str(self.tolerance) for r in rows), rows

    def test_confirmed_copy_gives_destination_unit_the_source_references_and_tolerances(self):
        """After Preview then Confirm, the destination unit has the source unit's references and tolerances."""
        self.preview_copy()
        self.submit_and_wait('button[name=confirm]')
        self.wait_for_text('ul.messagelist li.success', 'copied successfully')

        assert self.dest_refs_tols() == {
            'output': (self.references['output'].pk, self.tolerance.pk),
            'flatness': (self.references['flatness'].pk, self.tolerance.pk),
        }
        # and nothing on the source unit changed
        source = models.UnitTestInfo.objects.get(unit=self.source, test=self.output)
        assert (source.reference, source.tolerance) == (self.references['output'], self.tolerance)

    def test_cancelling_the_copy_changes_nothing(self):
        """Pressing Cancel on the preview leaves the destination unit's references and tolerances alone."""
        self.preview_copy()
        self.submit_and_wait('button[name=cancel]')
        assert not self.driver.find_elements(By.CSS_SELECTOR, 'ul.messagelist li.success')

        assert self.dest_refs_tols() == {'output': (None, None), 'flatness': (None, None)}

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason='qatrack/qa/admin.py:288 UnitTestInfoAdmin has no `actions`, so set_multiple_references_and_'
               'tolerances is never offered (and :502 would render set_multiple.html, which does not exist)',
    )
    def test_bulk_set_references_and_tolerances_is_offered(self):
        """Set References & Tolerances offers its 'set references and tolerances for selected tests' action."""
        self.load_admin()
        self.open('/admin/qa/unittestinfo/')
        self.wait_for_element('#result_list')
        actions = [o.get_attribute('value') for o in self.driver.find_elements(By.CSS_SELECTOR, '[name=action] option')]
        assert 'set_multiple_references_and_tolerances' in actions


class TestTestPackAdmin(AdminTestCase):
    """Exporting a test pack from one installation and importing it into another (testpack-*.js)."""

    def setUp(self):
        super().setUp()
        self.download_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.download_dir, ignore_errors=True)

        self.output = utils.create_test(name='pack_output', category=self.category)
        self.energy = utils.create_test(
            name='pack_energy', test_type=models.MULTIPLE_CHOICE, choices='6MV,10MV', category=self.category,
        )
        self.test_list = utils.create_test_list('Pack List')
        self.test_list.slug = 'pack_list'
        self.test_list.save()
        utils.create_test_list_membership(self.test_list, self.output, order=0)
        utils.create_test_list_membership(self.test_list, self.energy, order=1)
        utils.create_test_list('Not Exported')

    def wait_for_table(self, name):
        self.wait_for_visible('#%s-table' % name)
        self.wait.until(lambda d: not d.find_elements(By.CSS_SELECTOR, '.tp-container .loading'))

    def export_pack(self):
        """Export just 'Pack List' through the browser and return the downloaded test pack."""
        self.open('/admin/qa/testlist/export-testpack/')
        self.wait_for_table('testlists')
        try:
            self.driver.execute_cdp_cmd(
                'Browser.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': self.download_dir},
            )
        except Exception:  # noqa: BLE001 - older drivers only know the Page domain's version
            self.driver.execute_cdp_cmd(
                'Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': self.download_dir},
            )

        row = self.driver.find_element(By.XPATH, '//table[@id="testlists-table"]//td[text()="Pack List"]')
        self.click_element(row)
        self.wait_for_text('#testlists-summary', '1 Selected')
        self.wait.until(lambda d: self.value_of('id_testlists') == str(self.test_list.pk))
        self.type_into('id_name', 'roundtrip')
        self.type_into('id_description', 'Monthly output pack')
        self.click_css('input[type=submit][value=Download]')

        path = os.path.join(self.download_dir, 'roundtrip.tpk')
        self.wait_until(lambda: os.path.exists(path) and os.path.getsize(path) > 0, message='no test pack downloaded')
        with open(path, encoding='utf-8') as f:
            return path, json.load(f)

    def test_exported_test_pack_imports_back_the_same_test_list(self):
        """A test list exported to a test pack, deleted, and imported again comes back with the same tests.

        The export page builds the selection in the browser and the import page
        reads the file in the browser, so both halves need JavaScript.
        """
        self.load_admin()
        path, pack = self.export_pack()

        assert pack['meta']['name'] == 'roundtrip'
        assert pack['meta']['description'] == 'Monthly output pack'
        exported_lists = [json.loads(o)['object']['fields']['name'] for o in pack['objects']['testlists']]
        assert exported_lists == ['Pack List']

        # Pretend this is another installation: the test list and its tests are gone.
        models.TestListMembership.objects.all().delete()
        models.TestList.objects.filter(pk=self.test_list.pk).delete()
        models.Test.objects.all().delete()

        self.open('/admin/qa/testlist/import-testpack/')
        self.wait_for_table('testlists')
        self.driver.find_element(By.ID, 'id_testpack').send_keys(path)
        self.wait_for_text('#name', 'roundtrip')
        self.wait_for_text('#testlists-summary', 'All')
        rows = self.driver.find_elements(By.CSS_SELECTOR, '#testlists-table tbody tr')
        assert [r.text.strip() for r in rows] == ['Pack List desc']
        self.submit_and_wait('input[type=submit][value=Import]')
        self.wait_for_text('ul.messagelist li.success', 'Test Pack import successfully')

        imported = models.TestList.objects.get(slug='pack_list')
        assert imported.name == 'Pack List'
        memberships = models.TestListMembership.objects.filter(test_list=imported).order_by('order')
        assert [(m.test.slug, m.test.type, m.order) for m in memberships] == [
            ('pack_output', models.SIMPLE, 0),
            ('pack_energy', models.MULTIPLE_CHOICE, 1),
        ]
        assert models.Test.objects.get(slug='pack_energy').choices == '6MV,10MV'
        # Only the list that was exported came back; the other was never touched.
        assert sorted(models.TestList.objects.values_list('name', flat=True)) == ['Not Exported', 'Pack List']


class TestServiceEventScheduleAdmin(AdminTestCase):
    """Choosing a unit service area on a service event schedule (serviceeventschedule_admin.js)."""

    def setUp(self):
        super().setUp()
        self.unit = utils.create_unit(name='Linac One')
        gantry = sl_utils.create_service_area(name='Gantry')
        couch = sl_utils.create_service_area(name='Couch')
        self.gantry_usa = sl_utils.create_unit_service_area(unit=self.unit, service_area=gantry)
        self.couch_usa = sl_utils.create_unit_service_area(unit=self.unit, service_area=couch)

        service_type = sl_utils.create_service_type(name='Preventive')
        self.gantry_template = sl_utils.create_service_event_template(
            name='Gantry PM', service_area=gantry, service_type=service_type, created_by=self.user,
        )
        self.couch_template = sl_utils.create_service_event_template(
            name='Couch PM', service_area=couch, service_type=service_type, created_by=self.user,
        )
        self.any_template = sl_utils.create_service_event_template(
            name='Walkaround', service_type=service_type, created_by=self.user,
        )
        self.frequency = utils.create_frequency(name='Monthly', slug='monthly')
        self.group = Group.objects.create(name='Engineers')

    def test_choosing_a_service_area_fills_the_unit_and_narrows_the_templates(self):
        """Only templates for the chosen service area (or for none) can be picked, and a stale one is cleared.

        If the narrowing broke, a schedule could pair a unit's gantry with a
        couch template; the server does not check that on a new schedule.
        """
        self.load_admin()
        self.open('/admin/service_log/serviceeventschedule/add/')
        self.wait_for_element('#id_service_event_template ~ .select2')

        self.select2_choose('id_unit_service_area', 'Gantry')
        assert self.value_of('id_unit') == 'Other :: Linac One'
        assert self.enabled_options('id_service_event_template') == [
            '---------', 'Gantry PM (Service Area=Gantry)', 'Walkaround (Service Area=Not Specified)',
        ]
        self.select2_choose('id_service_event_template', 'Gantry PM (Service Area=Gantry)')

        # Switching to the couch clears the gantry template and offers the couch one instead.
        self.select2_choose('id_unit_service_area', 'Couch')
        assert self.value_of('id_service_event_template') == ''
        assert self.enabled_options('id_service_event_template') == [
            '---------', 'Couch PM (Service Area=Couch)', 'Walkaround (Service Area=Not Specified)',
        ]
        self.select2_choose('id_service_event_template', 'Couch PM (Service Area=Couch)')
        self.select2_choose('id_frequency', 'Monthly')
        self.select2_choose('id_assigned_to', 'Engineers')
        self.move_to_chosen('visible_to', 'Engineers')
        self.save()

        schedule = sl_models.ServiceEventSchedule.objects.get()
        assert schedule.unit_service_area == self.couch_usa
        assert schedule.service_event_template == self.couch_template
        assert schedule.frequency == self.frequency
        assert schedule.assigned_to == self.group
        assert list(schedule.visible_to.all()) == [self.group]


class TestNotificationAdmin(AdminTestCase):
    """QC completed notices, whose every choice is a select2 box (notification_admin.js)."""

    def setUp(self):
        super().setUp()
        physicists = Group.objects.create(name='Physicists')
        self.recipients = n_models.RecipientGroup.objects.create(name='Physics Team')
        self.recipients.groups.add(physicists)
        n_models.RecipientGroup.objects.create(name='Therapists', emails='rtt@example.com')
        self.linacs = n_models.UnitGroup.objects.create(name='Linacs')
        self.linacs.units.add(utils.create_unit(name='Linac One'))

    def fill_in_notice(self, notification_type, follow_up_days=None):
        self.load_admin()
        self.open('/admin/notifications/qccompletednotice/add/')
        self.wait_for_element('#id_recipients ~ .select2')
        self.select2_choose('id_notification_type', notification_type)
        if follow_up_days is not None:
            self.type_into('id_follow_up_days', str(follow_up_days))
        self.select2_choose('id_recipients', 'Physics Team')
        self.select2_choose('id_units', 'Linacs')
        self.save()
        return n_models.QCCompletedNotice.objects.get()

    def test_completed_notice_is_saved_with_the_groups_chosen(self):
        """A QC completed notice is saved with the type, recipients and unit filter picked in select2 boxes."""
        notice = self.fill_in_notice('Notify when Test List completed')

        assert notice.notification_type == n_models.QCCompletedNotice.COMPLETED
        assert notice.follow_up_days is None
        assert notice.recipients == self.recipients
        assert notice.units == self.linacs
        assert notice.test_lists is None

    def test_follow_up_notice_is_saved_with_its_days(self):
        """A follow up notice is saved with the number of days to wait before following up."""
        notice = self.fill_in_notice('Follow up notification', follow_up_days=3)

        assert notice.notification_type == n_models.QCCompletedNotice.FOLLOW_UP
        assert notice.follow_up_days == 3


class TestAutoReviewRuleSetAdmin(AdminTestCase):

    def setUp(self):
        super().setUp()
        self.approved = utils.create_status(name='Approved', slug='approved', is_default=False, requires_review=False)
        self.unreviewed = utils.create_status(name='Unreviewed', slug='unreviewed', is_default=True)
        self.ok_rule = models.AutoReviewRule.objects.create(pass_fail=models.OK, status=self.approved)
        self.tol_rule = models.AutoReviewRule.objects.create(pass_fail=models.TOLERANCE, status=self.unreviewed)
        self.default_set = models.AutoReviewRuleSet.objects.create(name='Default rules', is_default=True)
        self.default_set.rules.add(self.ok_rule)

    def open_add_page(self):
        self.load_admin()
        self.open('/admin/qa/autoreviewruleset/add/')
        self.wait_for_element('#id_rules_from')

    def test_rule_set_is_saved_with_the_rules_chosen(self):
        """A rule set is saved with exactly the rules moved into the 'chosen' box."""
        self.open_add_page()
        self.type_into('id_name', 'Strict rules')
        self.move_to_chosen('rules', str(self.tol_rule))
        self.save()

        rule_set = models.AutoReviewRuleSet.objects.get(name='Strict rules')
        assert list(rule_set.rules.all()) == [self.tol_rule]
        assert not rule_set.is_default
        assert models.AutoReviewRuleSet.objects.get(is_default=True) == self.default_set

    def test_a_second_default_rule_set_is_refused(self):
        """A new rule set can not also be the default while another one is; nothing is saved."""
        self.open_add_page()
        self.type_into('id_name', 'Another default')
        self.move_to_chosen('rules', str(self.ok_rule))
        self.click_css('#id_is_default')
        self.submit_and_wait('input[name="_save"]')

        self.wait_for_text('.field-is_default .errorlist', 'There must be one default auto review rule set')
        assert list(models.AutoReviewRuleSet.objects.values_list('name', flat=True)) == ['Default rules']
