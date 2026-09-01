from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from qatrack.faults.models import Fault
from qatrack.parts.models import Part, PartUsed
from qatrack.qa.models import TestList, TestListInstance, UnitTestCollection
from qatrack.reports.models import ReportSchedule, SavedReport
from qatrack.service_log.models import (
    ReturnToServiceQA,
    ServiceEvent,
    ServiceEventSchedule,
    ServiceEventTemplate,
)
from qatrack.units.models import Unit


class TestSampleDataGenerator(TestCase):

    def test_generate_small_center(self):
        out = StringIO()
        call_command("generate_sample_data", size="small", days=14, clear=True, no_input=True, stdout=out)

        self.assertIn("Successfully generated sample data for 'small' center!", out.getvalue())

        # Units
        self.assertEqual(Unit.objects.count(), 3)
        self.assertTrue(Unit.objects.filter(name__contains="TrueBeam").exists())
        self.assertTrue(Unit.objects.filter(name__contains="Versa").exists())
        self.assertTrue(Unit.objects.filter(name__contains="SOMATOM").exists())

        # QA
        self.assertGreaterEqual(TestList.objects.count(), 5)
        self.assertGreaterEqual(UnitTestCollection.objects.filter(active=True).count(), 8)
        self.assertGreaterEqual(TestListInstance.objects.count(), 10)
        self.assertEqual(TestListInstance.objects.filter(in_progress=True).count(), 1)

        # Service log & Faults
        self.assertGreaterEqual(ServiceEvent.objects.count(), 3)
        self.assertGreaterEqual(ReturnToServiceQA.objects.count(), 1)
        self.assertGreaterEqual(Fault.objects.count(), 2)
        self.assertGreaterEqual(ServiceEventTemplate.objects.count(), 4)
        self.assertGreaterEqual(ServiceEventSchedule.objects.count(), 2)

        # Parts
        self.assertGreaterEqual(Part.objects.count(), 5)
        self.assertGreaterEqual(PartUsed.objects.count(), 1)

        # Reports
        self.assertGreaterEqual(SavedReport.objects.count(), 4)
        self.assertGreaterEqual(ReportSchedule.objects.count(), 2)
