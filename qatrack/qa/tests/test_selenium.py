import time
from datetime import date

import pytest
import recurrence
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as e_c
from selenium.webdriver.support.ui import Select

from qatrack.accounts.tests.utils import create_group
from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qa.tests.test_selenium_admin import AdminSeleniumMixin
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log.tests import utils as sl_utils
from qatrack.units import models as u_models

objects = {

    'Group': {
        'name': 'testGroup',
    },
    'Category': {
        'name': 'testCategory',
        'slug': 'testCategory',
        'description': 'test test test test'
    },
    'Tests': [
        {
            'test_type': models.SIMPLE,
            'name': 'simple',
            'choices': None,
            'constant_value': None,
            'procedure': None
        }, {
            'test_type': models.BOOLEAN,
            'name': 'boolean',
            'choices': None,
            'constant_value': None,
            'procedure': None
        }, {
            'test_type': models.MULTIPLE_CHOICE,
            'name': 'multchoice',
            'choices': '1,2,3,4,5',
            'constant_value': None,
            'procedure': None
        }, {
            'test_type': models.CONSTANT,
            'name': 'constant',
            'choices': None,
            'constant_value': '23.23',
            'procedure': None
        }, {
            'test_type': models.COMPOSITE,
            'name': 'composite',
            'choices': None,
            'constant_value': None,
            'procedure': 'result = constant * simpleNumeric'
        }, {
            'test_type': models.STRING,
            'name': 'string',
            'choices': None,
            'constant_value': None,
            'procedure': None
        }, {
            'test_type': models.STRING_COMPOSITE,
            'name': 'scomposite',
            'choices': None,
            'constant_value': None,
            'procedure': 'result = string + " composite"'
        }, {
            'test_type': models.UPLOAD,
            'name': 'upload',
            'choices': None,
            'constant_value': None,
            'procedure': 'result = FILE[0]'
        }
    ],
    'TestList': {
        'name': 'TestTestList'
    },
    'Modality': {
        'name': 'TestModality'
    },
    'UnitType': {
        'name': 'TestModality',
        'vendor': 'TestVendor'
    },
    'Unit': {
        'name': 'TestUnit',
        'number': '1',
        'date_acceptance': '2026-01-05',
    },
    'Frequency': {
        'name': 'TestFrequency',
        'nominal_interval': '2',
        'due_interval': '3',
        'window_end': '4'
    },
    'absoluteTolerance': {
        'act_low': '-2',
        'tol_low': '-1',
        'tol_high': '1',
        'act_high': '2'
    },
    'percentTolerance': {
        'act_low': '-5',
        'tol_low': '-1',
        'tol_high': '1',
        'act_high': '5'
    },
    'multiChoiceTolerance': {
        'mc_pass_choices': '3',
        'mc_tol_choices': '2,4'
    },
}  # yapf: disable


# The user, login() and load_admin() that used to live on this class are now on
# the shared harness, so that other apps' browser tests need not import from this
# module. The name is kept because existing tests (here and in reports) use it.
BaseQATests = SeleniumTestCase


@pytest.mark.selenium
class LiveQATests(AdminSeleniumMixin, BaseQATests):
    """Creating the basic QC configuration through the Django admin.

    Each test goes through the admin as a person would - from the index, to
    the add page, filling the form in and saving - and then reads back from
    the database what was saved. A success message alone would pass even if a
    field were silently dropped on the way.
    """

    def test_admin_category(self):
        """A category is saved with the name, slug and description typed in."""

        self.load_admin()
        self.driver.find_element(By.XPATH, '//a[@href="/admin/qa/category/"]').click()
        self.click_by_link_text("ADD CATEGORY")
        self.type_into('id_name', objects['Category']['name'])
        # The slug is filled in from the name as it is typed; replace it.
        self.type_into('id_slug', objects['Category']['slug'], clear=True)
        self.type_into('id_description', objects['Category']['description'])
        self.save()

        category = models.Category.objects.get(name=objects['Category']['name'])
        assert category.slug == objects['Category']['slug']
        assert category.description == objects['Category']['description']

    def test_admin_tests(self):
        """Tests of each type are saved with their type, category, choices, constant and procedure.

        The calculation procedure is typed into the code editor that replaces
        the plain text box; if the editor stopped copying its text back to the
        form, the procedure would be saved empty.
        """

        category = utils.create_category(
            name=objects['Category']['name'],
            slug=objects['Category']['slug'],
            description=objects['Category']['description'],
        )
        type_labels = dict(models.TEST_TYPE_CHOICES)

        self.load_admin()
        self.driver.find_element(By.LINK_TEXT, 'Tests').click()
        self.click_by_link_text("ADD TEST")

        for i, the_test in enumerate(objects['Tests']):
            # Wait for a fresh, empty add form: after "Save and add another"
            # the previous page's success message must not be mistaken for
            # this one's.
            self.wait.until(lambda d: self.value_of('id_name') == '')
            self.type_into('id_name', the_test['name'])
            self.type_into('id_slug', the_test['name'])
            self.select2_choose('id_category', category.name)
            self.select2_choose('id_type', type_labels[the_test['test_type']])

            if the_test['choices']:
                self.type_into('id_choices', the_test['choices'])
            if the_test['constant_value']:
                self.type_into('id_constant_value', the_test['constant_value'])
            if the_test['procedure']:
                self.click_css('#calc-procedure-editor')
                self.driver.switch_to.active_element.send_keys(the_test['procedure'])
                # The editor copies its text into the form when it loses focus.
                self.click_css('#id_name')
                self.wait.until(lambda d: self.value_of('id_calculation_procedure') == the_test['procedure'])

            last = i + 1 == len(objects['Tests'])
            self.save('_save' if last else '_addanother')
            assert models.Test.objects.filter(name=the_test['name']).exists(), the_test['name']

        assert models.Test.objects.count() == len(objects['Tests'])
        for the_test in objects['Tests']:
            saved = models.Test.objects.get(name=the_test['name'])
            assert saved.slug == the_test['name']
            assert saved.type == the_test['test_type'], the_test['name']
            assert saved.category == category
            assert (saved.choices or None) == the_test['choices'], the_test['name']
            expected_constant = float(the_test['constant_value']) if the_test['constant_value'] else None
            assert saved.constant_value == expected_constant, the_test['name']
            # Saving tidies the procedure with black, which adds a final newline.
            assert (saved.calculation_procedure or '').strip() == (the_test['procedure'] or ''), the_test['name']

    def test_admin_testlist(self):
        """A test list is saved with every test entered, each in its own position."""

        for the_test in objects['Tests']:
            utils.create_test(
                name=the_test['name'],
                test_type=the_test['test_type'],
                choices=the_test['choices'],
                procedure=the_test['procedure'],
                constant_value=the_test['constant_value'],
            )
        test_pks = list(models.Test.objects.order_by('pk').values_list('pk', flat=True))

        self.load_admin()
        self.click_by_link_text("Test Lists")
        self.click_by_link_text("ADD TEST LIST")
        self.type_into('id_name', objects['TestList']['name'])
        self.type_into('id_slug', objects['TestList']['name'].lower(), clear=True)
        # The add page offers five empty rows; three more are needed.
        for i in range(3):
            self.click_element(self.driver.find_element(By.LINK_TEXT, 'Add another Test List Membership'))
            self.wait_for_element('#id_testlistmembership_set-%d-test' % (5 + i))
        for i, pk in enumerate(test_pks):
            self.type_into('id_testlistmembership_set-%d-test' % i, str(pk))
        self.save()

        test_list = models.TestList.objects.get(name=objects['TestList']['name'])
        assert test_list.slug == objects['TestList']['name'].lower()
        memberships = models.TestListMembership.objects.filter(test_list=test_list)
        assert sorted(memberships.values_list('test_id', flat=True)) == test_pks
        assert sorted(memberships.values_list('order', flat=True)) == list(range(len(test_pks)))

    def test_admin_modality(self):
        """A treatment and imaging modality is saved with its name."""

        self.load_admin()
        self.click_by_link_text("Treatment and Imaging Modalities")
        self.click_by_link_text("ADD TREATMENT AND IMAGING MODALITY")
        self.type_into('id_name', objects['Modality']['name'])
        self.save()

        assert list(u_models.Modality.objects.values_list('name', flat=True)) == [objects['Modality']['name']]

    def test_admin_unittype(self):
        """A unit type is saved with its name and the vendor chosen."""

        vendor = utils.create_vendor(objects['UnitType']['vendor'])

        self.load_admin()
        self.click_by_link_text("Unit Types")
        self.click_by_link_text("ADD UNIT TYPE")
        self.type_into('id_name', objects['UnitType']['name'])
        self.choose_option('id_vendor', vendor.name)
        self.save()

        unit_type = u_models.UnitType.objects.get(name=objects['UnitType']['name'])
        assert unit_type.vendor == vendor

    def test_admin_unit(self):
        """A unit is saved with its type, modalities, service areas and the hours of its schedule."""

        unit_type = utils.create_unit_type(
            name=objects['UnitType']['name'], vendor=utils.create_vendor(objects['UnitType']['vendor'])
        )
        modality = utils.create_modality(name=objects['Modality']['name'])
        utils.create_modality(name='Unused Modality')
        service_area = sl_utils.create_service_area(name='Gantry')
        other_service_area = sl_utils.create_service_area(name='Couch')

        self.load_admin()
        self.click_by_link_text("Units")
        self.click_by_link_text("ADD UNIT")
        self.type_into('id_name', objects['Unit']['name'])
        self.type_into('id_number', objects['Unit']['number'])
        self.type_into('id_date_acceptance', objects['Unit']['date_acceptance'])
        self.choose_option('id_type', '%s :: %s' % (objects['UnitType']['vendor'], unit_type.name))
        self.move_to_chosen('modalities', modality.name)
        self.click_css('#id_service_areas_add_all_link')
        self.wait_for_element('#id_service_areas_to option[title="Couch"]')

        # The first schedule row: from acceptance, 10.5 hours on Mondays.
        self.type_into('id_unitavailabletime_set-0-date_changed', objects['Unit']['date_acceptance'])
        self.type_into('id_unitavailabletime_set-0-hours_monday', '10:30', clear=True)
        self.save()

        unit = u_models.Unit.objects.get(name=objects['Unit']['name'])
        assert unit.number == int(objects['Unit']['number'])
        assert unit.date_acceptance == date(2026, 1, 5)
        assert unit.type == unit_type
        assert list(unit.modalities.all()) == [modality]
        assert set(unit.service_areas.all()) == {service_area, other_service_area}

        schedule = u_models.UnitAvailableTime.objects.get(unit=unit)
        assert schedule.date_changed == date(2026, 1, 5)
        assert schedule.hours_monday == timezone.timedelta(hours=10, minutes=30)
        assert schedule.hours_tuesday == timezone.timedelta(hours=8)
        assert schedule.hours_sunday == timezone.timedelta(0)

    def test_admin_frequency(self):
        """A weekly frequency is saved with the weekdays clicked in the rule editor and its window."""

        self.load_admin()
        self.click_by_link_text("Frequencies")
        self.click_by_link_text("ADD FREQUENCY")
        self.type_into('id_name', objects['Frequency']['name'])
        self.click_css('.add-rule .recurrence-label')
        days = self.wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.weekly td'))
        for index in (0, 2, 4):  # Monday, Wednesday, Friday
            self.click_element(days[index])
        self.type_into('id_window_end', objects['Frequency']['window_end'])
        self.wait.until(lambda d: 'BYDAY=MO,WE,FR' in self.value_of('id_recurrences'))
        self.save()

        frequency = models.Frequency.objects.get(name=objects['Frequency']['name'])
        assert frequency.slug == objects['Frequency']['name'].lower()
        assert frequency.window_end == int(objects['Frequency']['window_end'])
        assert frequency.window_start is None
        [rule] = frequency.recurrences.rrules
        assert rule.freq == recurrence.WEEKLY
        assert [str(day) for day in rule.byday] == ['MO', 'WE', 'FR']
        assert frequency.nominal_interval < 3

    def test_admin_unittestcollection(self):
        """A test list assigned to a unit is saved with its unit, frequency, groups and the test list picked."""

        group = create_group(name=objects['Group']['name'])
        unit = utils.create_unit(name=objects['Unit']['name'], number=objects['Unit']['number'])
        frequency = utils.create_frequency(name=objects['Frequency']['name'], slug='testfrequency')
        utils.create_test_list(name='Another Test List')
        test_list = utils.create_test_list(name=objects['TestList']['name'])
        test_list_type = ContentType.objects.get_for_model(models.TestList)

        self.load_admin()
        self.click_by_link_text("Assign Test Lists to Units")
        self.click_by_link_text('ADD UNIT TEST COLLECTION')
        self.wait_for_element('#id_unit ~ .select2')

        self.select2_choose('id_unit', 'Other :: %s' % unit.name)
        self.select2_choose('id_frequency', frequency.name)
        self.select2_choose('id_assigned_to', group.name)
        Select(self.driver.find_element(By.ID, 'id_content_type')).select_by_value(str(test_list_type.pk))
        self.move_to_chosen('visible_to', group.name)
        # Choosing the content type loads the test lists into a second box.
        self.select2_choose('generic_object_id', '(%d) %s' % (test_list.pk, test_list.name))
        self.wait.until(lambda d: self.value_of('id_object_id') == str(test_list.pk))
        self.save()

        utc = models.UnitTestCollection.objects.get()
        assert utc.unit == unit
        assert utc.frequency == frequency
        assert utc.assigned_to == group
        assert utc.content_type == test_list_type
        assert utc.tests_object == test_list
        assert list(utc.visible_to.all()) == [group]

    def test_admin_tolerances(self):
        """Absolute, percentage and multiple choice tolerances are each saved with their own type and limits."""

        self.load_admin()
        self.click_by_link_text('Tolerances')
        self.click_by_link_text('ADD TOLERANCE')

        for tol_type, values in [(models.ABSOLUTE, 'absoluteTolerance'), (models.PERCENT, 'percentTolerance')]:
            self.wait.until(lambda d: self.value_of('id_act_low') == '')
            Select(self.wait_for_visible('#id_type')).select_by_value(tol_type)
            for field in ('act_low', 'tol_low', 'tol_high', 'act_high'):
                self.type_into('id_%s' % field, objects[values][field])
            self.save('_addanother')

        self.wait.until(lambda d: self.value_of('id_mc_pass_choices') == '')
        Select(self.wait_for_visible('#id_type')).select_by_value(models.MULTIPLE_CHOICE)
        self.type_into('id_mc_pass_choices', objects['multiChoiceTolerance']['mc_pass_choices'])
        self.type_into('id_mc_tol_choices', objects['multiChoiceTolerance']['mc_tol_choices'])
        self.save()

        assert models.Tolerance.objects.exclude(type=models.BOOLEAN).count() == 3
        for tol_type, values in [(models.ABSOLUTE, 'absoluteTolerance'), (models.PERCENT, 'percentTolerance')]:
            tol = models.Tolerance.objects.get(type=tol_type)
            for field in ('act_low', 'tol_low', 'tol_high', 'act_high'):
                assert getattr(tol, field) == float(objects[values][field]), (tol_type, field)
        mc_tol = models.Tolerance.objects.get(type=models.MULTIPLE_CHOICE)
        assert mc_tol.mc_pass_choices == objects['multiChoiceTolerance']['mc_pass_choices']
        assert mc_tol.mc_tol_choices == objects['multiChoiceTolerance']['mc_tol_choices']

    def test_admin_set_ref_tols(self):
        """References and tolerances chosen on Set References & Tolerances are saved on the unit's tests."""

        mc_tol = utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='3', mc_tol_choices='2,4')
        abs_tol = utils.create_tolerance()

        mult_test = utils.create_test(name='multchoice', test_type=models.MULTIPLE_CHOICE, choices='1,2,3,4,5')
        simp_test = utils.create_test(name='simple', test_type=models.SIMPLE)
        comp_test = utils.create_test(name='composite', test_type=models.COMPOSITE)
        test_list = utils.create_test_list(objects['TestList']['name'])
        for order, test in enumerate([mult_test, simp_test, comp_test]):
            utils.create_test_list_membership(test_list=test_list, test=test, order=order)
        utc = utils.create_unit_test_collection(test_collection=test_list)

        self.load_admin()
        self.click_by_link_text('Set References & Tolerances')

        for test, tol, reference in [(mult_test, mc_tol, None), (simp_test, abs_tol, '0'), (comp_test, abs_tol, '23.23')]:
            self.click_by_link_text(test.name)
            self.choose_option('id_tolerance', str(tol))
            if reference is not None:
                self.type_into('id_reference_value', reference)
            self.save()

        def uti(test):
            return models.UnitTestInfo.objects.select_related('reference').get(unit=utc.unit, test=test)

        assert uti(mult_test).tolerance == mc_tol
        assert uti(mult_test).reference is None
        assert uti(simp_test).tolerance == abs_tol
        assert uti(simp_test).reference.value == 0
        assert uti(comp_test).tolerance == abs_tol
        assert uti(comp_test).reference.value == 23.23

    def test_admin_statuses(self):
        """Test instance statuses are saved with the default and review flags ticked."""

        self.load_admin()
        self.wait.until(e_c.presence_of_element_located((By.XPATH, "//a[contains(@href,'testinstancestatus')]")))
        self.driver.find_element(By.XPATH, "//a[contains(@href,'testinstancestatus')]").click()
        self.click_by_link_text('ADD TEST INSTANCE STATUS')
        self.type_into('id_name', 'testStatus')
        self.click_css('#id_is_default')
        self.save('_addanother')

        self.wait.until(lambda d: self.value_of('id_name') == '')
        self.type_into('id_name', 'testApprovalStatus')
        self.click_css('#id_requires_review')
        self.save()

        default = models.TestInstanceStatus.objects.get(name='testStatus')
        assert default.slug == 'teststatus'
        assert default.is_default
        assert default.requires_review

        approval = models.TestInstanceStatus.objects.get(name='testApprovalStatus')
        assert not approval.is_default
        assert not approval.requires_review

    def rest(self):

        self.load_main()

        # Perform test
        self.click_by_link_text('TestUnit')
        self.click_by_link_text('Perform')

        self.wait.until(e_c.presence_of_element_located((By.ID, 'id_form-0-value')))
        basic = self.driver.find_element(By.ID, 'id_form-0-value')
        boolean = self.driver.find_element(By.NAME, 'form-1-value')
        basic.send_keys('3')
        boolean.click()
        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[1]/td[5][contains(text(), "ACT(3.00)")]')
            )
        )

        basic.send_keys(Keys.BACKSPACE, '2')
        boolean.click()
        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[1]/td[5][contains(text(), "TOL(2.00)")]')
            )
        )

        basic.send_keys(Keys.BACKSPACE, '1')
        boolean.click()
        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[1]/td[5][contains(text(), "OK(1.00)")]')
            )
        )

        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[13]/td[5][contains(text(), "OK(0.0%)")]')
            )
        )

        basic.send_keys(Keys.BACKSPACE, '1.06')
        boolean.click()
        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[13]/td[5][contains(text(), "ACT(6.0%)")]')
            )
        )

        basic.send_keys(Keys.BACKSPACE, '5')
        boolean.click()
        self.wait.until(
            e_c.presence_of_element_located(
                (By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[13]/td[5][contains(text(), "TOL(5.0%)")]')
            )
        )

        basic.send_keys(Keys.BACKSPACE, Keys.BACKSPACE, Keys.BACKSPACE)
        boolean.click()
        # time.sleep(1)

        multi = self.driver.find_element(By.ID, 'id_form-2-string_value')
        multi.click()
        multi.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
        self.assertTrue(
            self.driver.find_element(By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[7]/td[5]').text == 'ACT'
        )
        multi.click()
        multi.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
        self.assertTrue(
            self.driver.find_element(By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[7]/td[5]').text == 'TOL'
        )
        multi.click()
        multi.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
        self.assertTrue(
            self.driver.find_element(By.XPATH, '//*[@id="perform-qa-table"]/tbody/tr[7]/td[5]').text == 'OK'
        )

        self.driver.find_element(By.ID, 'id_form-5-string_value').send_keys('a string')
        boolean.click()
        self.wait.until(
            e_c.text_to_be_present_in_element_value((By.ID, 'id_form-6-string_value'), 'a string composite')
        )

        self.driver.find_element(By.ID, 'id_form-7-skipped').click()

        self.driver.find_element(By.ID, 'submit-qa').click()

        self.wait.until(e_c.presence_of_element_located((By.XPATH, '//div[contains(text(), "Showing 1 to 1")]')))
        self.driver.find_element(By.PARTIAL_LINK_TEXT, 'Review Data').click()
        self.driver.find_element(By.PARTIAL_LINK_TEXT, 'Unreviewed Visible To Your Groups').click()
        self.click_by_link_text('Review')

        self.wait.until(e_c.presence_of_element_located((By.ID, 'id_testinstance_set-0-status')))
        self.driver.find_element(By.ID, 'bulk-status').click()
        self.driver.find_element(By.ID, 'bulk-status').send_keys(Keys.ARROW_DOWN, Keys.ARROW_DOWN, Keys.ENTER)

        self.driver.find_element(By.XPATH, '//button[@type = "submit"]').click()

        self.wait.until(
            e_c.presence_of_element_located((By.XPATH, '//td[contains(text(), "No data available in table")]'))
        )


@pytest.mark.selenium
class TestPerformQC(BaseQATests):

    def setUp(self):
        with transaction.atomic():
            super().setUp()

            self.unit = utils.create_unit()
            self.group = utils.create_group()
            for p in Permission.objects.all():
                self.group.permissions.add(p)
            self.user.groups.add(self.group)
            self.test_list = utils.create_test_list()

            self.tnum_1 = utils.create_test(name="test1")
            self.tnum_2 = utils.create_test(name="test2")
            self.tcomp = utils.create_test(name="testc", test_type=models.COMPOSITE)
            self.tcomp.calculation_procedure = "result = test1 + test2 + 2"
            self.tcomp.save()

            self.tdate = utils.create_test(name="testdate", test_type=models.DATE)
            self.tdatetime = utils.create_test(name="testdatetime", test_type=models.DATETIME)

            self.tmult = utils.create_test(name="testmult", choices="choicea,choiceb", test_type=models.MULTIPLE_CHOICE)
            self.tstring = utils.create_test(name="teststring", test_type=models.STRING)
            self.tstringcomp = utils.create_test(name="teststringcomp", test_type=models.STRING_COMPOSITE)
            self.tstringcomp.calculation_procedure = "teststringcomp = teststring + testmult"
            self.tstringcomp.save()

            all_tests = [
                self.tnum_1,
                self.tnum_2,
                self.tcomp,
                self.tdate,
                self.tdatetime,
                self.tmult,
                self.tstring,
                self.tstringcomp,
            ]

            for o, t in enumerate(all_tests):
                utils.create_test_list_membership(self.test_list, t, order=o)

            self.utc = utils.create_unit_test_collection(unit=self.unit, test_collection=self.test_list)

            self.utc.visible_to.add(self.group)
            self.url = reverse("perform_qa", kwargs={'pk': self.utc.pk})
            self.status = models.TestInstanceStatus.objects.create(
                name="foo",
                slug="foo",
                is_default=True,
            )

            sl_utils.create_service_event_status(is_default=True)
            sl_utils.create_unit_service_area(self.utc.unit)
            sl_utils.create_service_type()

    def test_ok_on_load(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""
        with transaction.atomic():
            self.login()
            self.open(self.url)
            assert len(self.driver.find_elements(By.CSS_SELECTOR, ".qa-status.btn-danger")) == 0

    def fill_testlist(self):

        self.login()
        self.open(self.url)
        inputs = self.driver.find_elements(By.CLASS_NAME, "qa-input")[:3]
        inputs[0].send_keys(1)
        inputs[1].send_keys(2)
        inputs[1].send_keys(Keys.TAB)
        self.wait.until(lambda d: d.execute_script("return typeof jQuery !== 'undefined' ? jQuery.active == 0 : true"))
        self.click_by_css_selector(".choose-date")
        self.wait.until(e_c.element_to_be_clickable((By.CSS_SELECTOR, ".open .today")))
        self.click_by_css_selector(".open .today")

        self.click_by_css_selector(".choose-datetime")
        self.wait.until(e_c.element_to_be_clickable((By.CSS_SELECTOR, ".open .today")))
        self.click_by_css_selector(".open .today")

        self.click_by_css_selector("body")

        option = self.driver.find_elements(By.CSS_SELECTOR, "select.qa-input option")[-1]
        option.click()

        self.driver.find_element(By.CSS_SELECTOR, ".qa-string .qa-input").send_keys("test")
        self.click_by_css_selector("body")
        self.wait.until(lambda d: d.execute_script("return typeof jQuery !== 'undefined' ? jQuery.active == 0 : true"))
    def test_perform_ok(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""

        self.fill_testlist()
        inputs = self.driver.find_elements(By.CLASS_NAME, "qa-input")[:3]

        assert int(float(inputs[2].get_attribute("value"))) == 5
        assert models.TestListInstance.objects.count() == 0
        self.click("submit-qa")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
        self.wait.until(lambda d: d.execute_script("return typeof jQuery !== 'undefined' ? jQuery.active == 0 : true"))

        assert models.TestListInstance.objects.count() == 1
        assert models.TestListInstance.objects.latest("pk").include_for_scheduling

        assert models.TestInstance.objects.filter(unit_test_info__test__type="simple")[0].value == 1
        assert models.TestInstance.objects.filter(unit_test_info__test__type="simple")[1].value == 2
        assert models.TestInstance.objects.get(unit_test_info__test__type="composite").value == 5
        now = timezone.now()
        date = timezone.localtime(now).date()
        assert models.TestInstance.objects.get(unit_test_info__test__type="date").date_value == date
        dt = timezone.localtime(now).replace(hour=12, minute=0, second=0, microsecond=0)
        assert models.TestInstance.objects.get(unit_test_info__test__type="datetime").datetime_value == dt
        assert models.TestInstance.objects.get(unit_test_info__test__type="string").string_value == "test"
        assert models.TestInstance.objects.get(unit_test_info__test__type="scomposite").string_value == "testchoiceb"
        assert models.TestInstance.objects.get(unit_test_info__test__type="multchoice").string_value == "choiceb"

    def test_perform_ok_therapist(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""

        self.group.permissions.clear()
        self.user.is_superuser = False
        self.user.save()
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(models.TestListInstance)
        perm, _ = Permission.objects.get_or_create(
            codename="add_testlistinstance", content_type=ct, defaults={"name": "Can add test list instance"}
        )
        self.group.permissions.add(perm)
        self.fill_testlist()
        inputs = self.driver.find_elements(By.CLASS_NAME, "qa-input")[:3]

        assert int(float(inputs[2].get_attribute("value"))) == 5
        assert models.TestListInstance.objects.count() == 0
        self.click("submit-qa")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
        self.wait.until(lambda d: d.execute_script("return typeof jQuery !== 'undefined' ? jQuery.active == 0 : true"))

        assert models.TestListInstance.objects.count() == 1
        assert models.TestListInstance.objects.latest("pk").include_for_scheduling

        assert models.TestInstance.objects.filter(unit_test_info__test__type="simple")[0].value == 1
        assert models.TestInstance.objects.filter(unit_test_info__test__type="simple")[1].value == 2
        assert models.TestInstance.objects.get(unit_test_info__test__type="composite").value == 5
        now = timezone.now()
        date = timezone.localtime(now).date()
        assert models.TestInstance.objects.get(unit_test_info__test__type="date").date_value == date
        dt = timezone.localtime(now).replace(hour=12, minute=0, second=0, microsecond=0)
        assert models.TestInstance.objects.get(unit_test_info__test__type="datetime").datetime_value == dt
        assert models.TestInstance.objects.get(unit_test_info__test__type="string").string_value == "test"
        assert models.TestInstance.objects.get(unit_test_info__test__type="scomposite").string_value == "testchoiceb"
        assert models.TestInstance.objects.get(unit_test_info__test__type="multchoice").string_value == "choiceb"

    def test_comment(self):
        """ tests present"""
        self.fill_testlist()
        self.driver.find_elements(By.CSS_SELECTOR, ".revealcomment")[0].click()
        self.send_keys("id_form-0-comment", "testticomment")
        self.driver.find_elements(By.CSS_SELECTOR, ".revealcomment")[0].click()

        self.click("submit-qa")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
        assert models.TestInstance.objects.filter(comment="testticomment").count() == 1

    def test_set_in_progress(self):
        """ tests present"""
        self.fill_testlist()

        self.click("in-progress-container")
        self.click("submit-qa")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
        assert models.TestListInstance.objects.in_progress().count() == 1

    def test_perform_and_review(self):
        """Ensure that we can go through a full perform->review cycle"""

        utils.create_status(name="reviewed", slug="reviewed", is_default=False, requires_review=False)
        self.fill_testlist()
        self.click("submit-qa")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))

        self.open("/qc/session/unreviewed/")
        time.sleep(0.2)

        self.click_by_link_text("Review")
        self.select_by_text("bot-status-select", "reviewed")

        self.send_keys("id_comment", "testlistcomment")
        self.click("post-comment")
        time.sleep(0.2)
        assert models.Comment.objects.count() == 1

        assert models.TestListInstance.objects.unreviewed().count() == 1
        self.click("submit-review")
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
        assert models.TestListInstance.objects.unreviewed().count() == 0

    def test_perform_and_initiate_se(self):
        """Ensure that we can go through a full perform->review cycle"""

        self.fill_testlist()
        self.click("init-se-container")
        self.click("submit-qa")

        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))

        time.sleep(0.2)
        self.driver.execute_script("$('#id_datetime_service').focus()")
        time.sleep(0.3)
        self.click_by_css_selector(".today")
        time.sleep(0.2)
        self.select_by_index("id_service_area_field_fake", 1)
        time.sleep(0.2)
        self.select_by_index("id_service_type", 1)
        self.send_keys("id_problem_description", "Problem!")
        self.click("save-se")
        time.sleep(0.2)
        assert models.TestListInstance.objects.first().serviceevents_initiated.count() == 1

    def test_autosave(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""

        self.login()
        self.open(self.url)
        time.sleep(0.2)
        inputs = self.driver.find_elements(By.CLASS_NAME, "qa-input")[:3]
        inputs[0].send_keys(1)
        assert models.AutoSave.objects.count() == 0
        time.sleep(1)
        inputs[0].send_keys(Keys.ENTER)
        time.sleep(4.2)  # auto save is debounced with a 4s interval
        assert models.AutoSave.objects.count() == 1

    def test_load_autosave(self):
        """Ensure an autosave is restored with its test values, comments and
        work started/completed times displayed in the sites datetime format"""

        tl2 = utils.create_test_list(name="day 2")
        utils.create_test_list_membership(tl2, test=self.tnum_1)
        cycle = utils.create_cycle([self.test_list, tl2])
        utc = utils.create_unit_test_collection(
            unit=self.utc.unit, test_collection=cycle, assigned_to=self.utc.assigned_to
        )

        tz = timezone.get_current_timezone()
        auto = models.AutoSave.objects.create(
            unit_test_collection=utc,
            test_list=tl2,
            day=1,
            work_started=timezone.datetime(1980, 5, 12, 12).replace(tzinfo=tz),
            work_completed=timezone.datetime(1980, 5, 12, 12, 1).replace(tzinfo=tz),
            created_by=self.user,
            modified_by=self.user,
            data={
                'tests': {
                    'test1': 1,
                },
                'comments': {
                    'test1': 'test comment',
                },
                'skips': {
                    'test1': False,
                },
                'tli_comment': 'test list instance comment'
            }
        )

        self.login()

        url = reverse("perform_qa", kwargs={'pk': utc.pk})
        self.open(url + "?autosave_id=%d&day=%d" % (auto.pk, auto.day + 1))
        time.sleep(0.2)

        inputs = self.driver.find_elements(By.CLASS_NAME, "qa-input")[:3]
        title = "Perform %s : day 2" % utc.unit.name
        assert title in [el.text for el in self.driver.find_elements(By.CLASS_NAME, "box-title")]
        assert float(inputs[0].get_attribute("value")) == 1
        assert self.driver.find_element(By.ID, "id_work_started").get_attribute("value") == "1980-05-12 12:00"
        assert self.driver.find_element(By.ID, "id_work_completed").get_attribute("value") == "1980-05-12 12:01"
        assert self.driver.find_element(By.ID, "id_work_duration").get_attribute("value") == "0hr:01min"
        assert self.driver.find_element(By.ID, "id_form-0-comment").get_attribute("value") == "test comment"
        assert self.driver.find_element(By.ID, "id_comment").get_attribute("value") == "test list instance comment"

    def test_submit_autosave(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""

        tl2 = utils.create_test_list(name="day 2")
        utils.create_test_list_membership(tl2, test=self.tnum_1)
        cycle = utils.create_cycle([self.test_list, tl2])
        utc = utils.create_unit_test_collection(
            unit=self.utc.unit, test_collection=cycle, assigned_to=self.utc.assigned_to
        )

        tz = timezone.get_current_timezone()
        auto = models.AutoSave.objects.create(
            unit_test_collection=utc,
            test_list=tl2,
            day=1,
            work_started=timezone.datetime(1980, 5, 12, 12).replace(tzinfo=tz),
            work_completed=timezone.datetime(1980, 5, 12, 12, 1).replace(tzinfo=tz),
            created_by=self.user,
            modified_by=self.user,
            data={
                'tests': {
                    'test1': 1,
                },
                'comments': {
                    'test1': 'test comment',
                },
                'skips': {
                    'test1': False,
                },
                'tli_comment': 'test list instance comment'
            }
        )

        self.login()

        url = reverse("perform_qa", kwargs={'pk': utc.pk})
        self.open(url + "?autosave_id=%d&day=%d" % (auto.pk, auto.day + 1))
        time.sleep(0.2)

        self.click("submit-qa")
        # click() returns as soon as the click is dispatched, not when the
        # POST it triggers has been handled - so without this the assertion
        # below raced the submission. It failed roughly two runs in three on
        # Chromium, and the failure screenshot showed the submit button still
        # reading "Submitting...". Every other submit-qa test in this file
        # already waits for the success alert; this one was the exception.
        self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))

        assert models.AutoSave.objects.filter(pk=auto.pk).count() == 0


@pytest.mark.selenium
class TestReviewQC(BaseQATests):

    def setUp(self):
        with transaction.atomic():
            super().setUp()

            self.unreviewed = utils.create_status(name="Unreviewed", slug="unreviewed")
            self.reviewed = utils.create_status(name="Approved", slug="approved", is_default=False, requires_review=False)
            utils.create_test_instance()

            self.url = "/qc/session/unreviewed/"

    @override_settings(REVIEW_BULK=True)
    def test_review_ok(self):
        """Ensure that no failed tests on load and 3 "NO TOL" tests present"""
        with transaction.atomic():
            self.login()
            self.open(self.url)
            # The table is drawn by JavaScript after the page loads; a fixed
            # 0.1 s pause was not always enough on a busy machine.
            self.wait.until(e_c.element_to_be_clickable((By.CLASS_NAME, "test-selected-toggle")))
            self.driver.find_elements(By.CLASS_NAME, "test-selected-toggle")[0].click()
            self.select_by_text("bulk-status", "Approved")
            self.click("submit-review")
            assert models.TestListInstance.objects.unreviewed().count() == 1

            self.click("confirm-update")
            self.wait.until(e_c.presence_of_element_located((By.CLASS_NAME, 'alert-success')))
            assert models.TestListInstance.objects.unreviewed().count() == 0


@pytest.mark.selenium
class TestStringToleranceChoices(BaseQATests):
    """Which tolerances Set References & Tolerances offers, per test type.

    `test_admin_set_ref_tols` above already visits this page, but it covers only
    multiple choice, simple and composite tests, and it picks
    `select_by_index("id_tolerance", 1)` without asserting what is in the list. So
    it could not have caught the regression this class exists for: a string
    composite was offered absolute and percentage tolerances and nothing that
    could judge it, because only a multiple choice tolerance can (see
    `TestInstance.string_pass_fail`). Selecting index 1 would have chosen the
    wrong one and passed.

    These assert on the *contents* of the dropdown, which is where the defect was.
    """

    def setUp(self):
        super().setUp()

        with transaction.atomic():
            self.mc_tol = utils.create_tolerance(
                tol_type=models.MULTIPLE_CHOICE,
                mc_pass_choices="PASS",
                mc_tol_choices="Incorrect Linac,Incorrect Field",
            )
            self.abs_tol = utils.create_tolerance(tol_type=models.ABSOLUTE)

            self.scomposite = utils.create_test(
                name="string composite tol", test_type=models.STRING_COMPOSITE,
                procedure="result = 'PASS'",
            )
            self.simple = utils.create_test(name="numeric tol", test_type=models.SIMPLE)

            test_list = utils.create_test_list("tolerance choice list")
            utils.create_test_list_membership(test_list=test_list, test=self.scomposite)
            utils.create_test_list_membership(test_list=test_list, test=self.simple)
            utils.create_unit_test_collection(test_collection=test_list)

    def tolerance_options(self, test_name):
        """The visible text of every option the tolerance dropdown offers."""
        self.click_by_link_text(test_name)
        self.wait.until(e_c.presence_of_element_located((By.ID, 'id_tolerance')))
        select = Select(self.driver.find_element(By.ID, 'id_tolerance'))
        return [o.text.strip() for o in select.options if o.text.strip()]

    def test_string_composite_is_offered_a_multiple_choice_tolerance(self):
        self.load_admin()
        self.click_by_link_text('Set References & Tolerances')

        options = self.tolerance_options(self.scomposite.name)

        assert str(self.mc_tol) in options, (
            "a string composite must be offered the multiple choice tolerance; got %r" % options
        )
        assert str(self.abs_tol) not in options, (
            "a string composite has no numerical reference, so an absolute "
            "tolerance should not be offered; got %r" % options
        )

    def test_numerical_test_is_not_offered_a_multiple_choice_tolerance(self):
        """The narrowing must still narrow, or the fix is just a widening."""
        self.load_admin()
        self.click_by_link_text('Set References & Tolerances')

        options = self.tolerance_options(self.simple.name)

        assert str(self.abs_tol) in options, options
        assert str(self.mc_tol) not in options, options
