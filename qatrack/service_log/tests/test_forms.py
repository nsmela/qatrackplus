from django.core.exceptions import ValidationError
from django.test import TestCase

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils
from qatrack.service_log import forms as sl_forms
from qatrack.service_log import models as sl_models
from qatrack.service_log.tests import utils as sl_utils


class TestHoursFormClean(TestCase):

    def setUp(self):
        self.user = create_user()
        self.tp = sl_utils.create_third_party()
        self.se = sl_utils.create_service_event()

    def test_clean_user_or_thirdparty_user(self):
        data = {
            'hours_set-0-user_or_thirdparty': f'user-{self.user.id}',
        }
        form = sl_forms.HoursForm(data=data, prefix='hours_set-0')
        form.instance.service_event = self.se
        form.cleaned_data = {'user_or_thirdparty': f'user-{self.user.id}'}
        user = form.clean_user_or_thirdparty()
        self.assertEqual(user, self.user)

    def test_clean_user_or_thirdparty_tp(self):
        data = {
            'hours_set-0-user_or_thirdparty': f'tp-{self.tp.id}',
        }
        form = sl_forms.HoursForm(data=data, prefix='hours_set-0')
        form.instance.service_event = self.se
        form.cleaned_data = {'user_or_thirdparty': f'tp-{self.tp.id}'}
        tp = form.clean_user_or_thirdparty()
        self.assertEqual(tp, self.tp)

    def test_clean_user_or_thirdparty_duplicate(self):
        data = {
            'hours_set-0-user_or_thirdparty': f'user-{self.user.id}',
            'hours_set-1-user_or_thirdparty': f'user-{self.user.id}',
        }
        form = sl_forms.HoursForm(data=data, prefix='hours_set-0')
        form.instance.service_event = self.se
        form.cleaned_data = {'user_or_thirdparty': f'user-{self.user.id}'}
        with self.assertRaises(ValidationError):
            form.clean_user_or_thirdparty()


class TestServiceEventFormClean(TestCase):

    def setUp(self):
        self.user = create_user()
        self.unit = qa_utils.create_unit()
        self.sa = sl_utils.create_service_area()
        self.usa = sl_utils.create_unit_service_area(unit=self.unit, service_area=self.sa)
        self.se = sl_utils.create_service_event()
        self.se.unit_service_area = self.usa
        self.se.save()
        self.status = sl_utils.create_service_event_status(rts_qa_must_be_reviewed=True)

    def test_clean_raises_when_no_test_list_instance(self):
        data = {
            'rtsqa-0-id': '1',
            'rtsqa-0-unit_test_collection': '1',
            'rtsqa-0-test_list_instance': '',
        }
        form = sl_forms.ServiceEventForm(data=data, instance=self.se, user=self.user)
        form.cleaned_data = {'service_status': self.status, 'unit_field': self.unit, 'service_area_field': self.sa}
        form._errors = {}
        form.clean()
        self.assertIn('service_status', form._errors)

    def test_clean_raises_when_not_all_reviewed(self):
        tli = qa_utils.create_test_list_instance()
        tli.all_reviewed = False
        tli.save()
        data = {
            'rtsqa-0-id': '1',
            'rtsqa-0-unit_test_collection': '1',
            'rtsqa-0-test_list_instance': tli.id,
        }
        form = sl_forms.ServiceEventForm(data=data, instance=self.se, user=self.user)
        form.cleaned_data = {'service_status': self.status, 'unit_field': self.unit, 'service_area_field': self.sa}
        form._errors = {}
        form.clean()
        self.assertIn('service_status', form._errors)

    def test_clean_passes_when_all_reviewed(self):
        tli = qa_utils.create_test_list_instance()
        tli.all_reviewed = True
        tli.save()
        data = {
            'rtsqa-0-id': '1',
            'rtsqa-0-unit_test_collection': '1',
            'rtsqa-0-test_list_instance': tli.id,
        }
        form = sl_forms.ServiceEventForm(data=data, instance=self.se, user=self.user)
        form.cleaned_data = {'service_status': self.status, 'unit_field': self.unit, 'service_area_field': self.sa}
        form._errors = {}
        form.clean()
        self.assertNotIn('service_status', form._errors)


class TestServiceEventTemplateFormCleanName(TestCase):

    def test_clean_name_duplicate(self):
        sl_utils.create_service_event_template(name="Duplicate")
        form = sl_forms.ServiceEventTemplateForm(data={'name': 'Duplicate'})
        form.cleaned_data = {'name': 'Duplicate'}
        form.clean_name()
        self.assertIn('name', form.errors)

    def test_clean_name_unique(self):
        form = sl_forms.ServiceEventTemplateForm(data={'name': 'Unique'})
        form.cleaned_data = {'name': 'Unique'}
        name = form.clean_name()
        self.assertEqual(name, 'Unique')
        self.assertNotIn('name', form.errors)


class TestServiceEventMultipleFieldClean(TestCase):

    def setUp(self):
        self.se1 = sl_utils.create_service_event()
        self.se2 = sl_utils.create_service_event()
        self.field = sl_forms.ServiceEventMultipleField(queryset=sl_models.ServiceEvent.objects.all())

    def test_clean_invalid_pk(self):
        with self.assertRaises(ValidationError):
            self.field.clean([self.se1.pk, 99999])

    def test_clean_valid_pk(self):
        qs = self.field.clean([self.se1.pk, self.se2.pk])
        self.assertEqual(set(qs), {self.se1, self.se2})
