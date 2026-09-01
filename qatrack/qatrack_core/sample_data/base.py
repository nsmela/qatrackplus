from datetime import time, timedelta

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone


class BaseSampleDataGenerator:
    """Base class for QATrack+ sample data generators."""

    def __init__(self, days=90, stdout=None, stderr=None):
        self.days = days
        self.stdout = stdout
        self.stderr = stderr
        self.now = timezone.now()

    def log(self, message, style=None):
        if self.stdout:
            if style:
                self.stdout.write(style(message))
            else:
                self.stdout.write(message)

    def rel_dt(self, days_ago, hour=8, minute=0, second=0):
        """Returns a timezone-aware datetime `days_ago` in the past at given time of day."""
        base_date = (self.now - timedelta(days=days_ago)).date()
        dt = timezone.datetime.combine(base_date, time(hour=hour, minute=minute, second=second))
        if timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    def ensure_site(self):
        """Ensure django.contrib.sites default site exists."""
        site, _ = Site.objects.get_or_create(
            id=getattr(settings, 'SITE_ID', 1),
            defaults={'domain': 'localhost:8000', 'name': 'QATrack+ Center'}
        )
        return site

    def ensure_default_fixtures(self):
        """Load default fixtures if database is missing categories/frequencies/tolerances."""
        from qatrack.qa.models import Category, Frequency, Tolerance
        from qatrack.service_log.models import ServiceArea, ServiceEventStatus, ServiceType
        from qatrack.units.models import UnitClass, Vendor

        missing = (
            Category.objects.count() == 0 or
            Frequency.objects.count() == 0 or
            Tolerance.objects.count() == 0 or
            UnitClass.objects.count() == 0 or
            Vendor.objects.count() == 0 or
            ServiceArea.objects.count() == 0 or
            ServiceEventStatus.objects.count() == 0 or
            ServiceType.objects.count() == 0
        )
        if missing:
            self.log("Loading core default fixtures...", lambda s: s)
            call_command('installfixtures')

    def clear_database(self):
        """Cleans existing user data in a safe order."""
        self.log("Clearing existing data...", lambda s: s)
        with transaction.atomic():
            # Reports
            from qatrack.reports.models import ReportNote, ReportSchedule, SavedReport
            ReportSchedule.objects.all().delete()
            ReportNote.objects.all().delete()
            SavedReport.objects.all().delete()

            # Faults
            from qatrack.faults.models import Fault, FaultReviewInstance
            FaultReviewInstance.objects.all().delete()
            Fault.objects.all().delete()

            # Parts
            from qatrack.parts.models import (
                Contact,
                Part,
                PartCategory,
                PartStorageCollection,
                PartSupplierCollection,
                PartUsed,
                Room,
                Storage,
                Supplier,
            )
            PartUsed.objects.all().delete()
            PartStorageCollection.objects.all().delete()
            PartSupplierCollection.objects.all().delete()
            Part.objects.all().delete()
            PartCategory.objects.all().delete()
            Storage.objects.all().delete()
            Room.objects.all().delete()
            Contact.objects.all().delete()
            Supplier.objects.all().delete()

            # Service Log
            from qatrack.service_log.models import (
                Hours,
                ReturnToServiceQA,
                ServiceEvent,
                UnitServiceArea,
            )
            ReturnToServiceQA.objects.all().delete()
            Hours.objects.all().delete()
            ServiceEvent.objects.all().delete()
            UnitServiceArea.objects.all().delete()

            # QA
            from django_comments.models import Comment

            from qatrack.qa.models import (
                Reference,
                Sublist,
                Test,
                TestInstance,
                TestList,
                TestListCycle,
                TestListCycleMembership,
                TestListInstance,
                TestListMembership,
                UnitTestCollection,
                UnitTestInfo,
                UnitTestInfoChange,
            )
            Comment.objects.all().delete()
            TestInstance.objects.all().delete()
            TestListInstance.objects.all().delete()
            UnitTestInfoChange.objects.all().delete()
            UnitTestInfo.objects.all().delete()
            UnitTestCollection.objects.all().delete()
            Sublist.objects.all().delete()
            TestListMembership.objects.all().delete()
            TestListCycleMembership.objects.all().delete()
            TestListCycle.objects.all().delete()
            TestList.objects.all().delete()
            Test.objects.all().delete()
            Reference.objects.all().delete()

            # Units
            from qatrack.units.models import Site as ClinicalSite
            from qatrack.units.models import Unit, UnitAvailableTime, UnitAvailableTimeEdit, UnitType
            UnitAvailableTimeEdit.objects.all().delete()
            UnitAvailableTime.objects.all().delete()
            Unit.objects.all().delete()
            UnitType.objects.all().delete()
            ClinicalSite.objects.all().delete()

        self.log("Database cleared successfully.", lambda s: s)

    def generate(self):
        raise NotImplementedError("Subclasses must implement generate()")
