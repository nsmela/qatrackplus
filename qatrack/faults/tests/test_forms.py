from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils.datastructures import MultiValueDict

from qatrack.faults import forms, models
from qatrack.qa.tests import utils as qa_utils


class TestFaultFormClean(TestCase):

    def setUp(self):
        self.unit = qa_utils.create_unit()

    def test_clean_unit_invalid(self):
        data = MultiValueDict({'unit': ['99999']})
        form = forms.FaultForm(data=data)
        form.cleaned_data = {'unit': '99999'}
        with self.assertRaises(ValidationError):
            form.clean_unit()

    def test_clean_unit_valid(self):
        data = MultiValueDict({'unit': [self.unit.id]})
        form = forms.FaultForm(data=data)
        form.cleaned_data = {'unit': self.unit.id}
        unit = form.clean_unit()
        self.assertEqual(unit, self.unit)

    def test_clean_fault_types_field_new(self):
        data = MultiValueDict({'fault-fault_types_field': [f'{forms.NEW_FAULT_TYPE_MARKER}NEW123']})
        form = forms.FaultForm(data=data)
        form.cleaned_data = {'fault_types_field': [f'{forms.NEW_FAULT_TYPE_MARKER}NEW123']}
        cleaned = form.clean_fault_types_field()
        self.assertEqual(cleaned, ['NEW123'])
        self.assertTrue(models.FaultType.objects.filter(code='NEW123').exists())

    def test_clean_fault_types_field_deduplicate(self):
        data = MultiValueDict({'fault-fault_types_field': ['A', 'B', 'A']})
        form = forms.FaultForm(data=data)
        form.cleaned_data = {'fault_types_field': ['A', 'B', 'A']}
        cleaned = form.clean_fault_types_field()
        self.assertEqual(cleaned, ['A', 'B'])
