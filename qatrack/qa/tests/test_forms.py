import os

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone, translation

from qatrack.attachments.models import Attachment
from qatrack.qa import models
from qatrack.qa.views import forms
from qatrack.qatrack_core.tests.utils import picker_format

from . import utils


class TestUpdateTestInstanceForm(TestCase):

    def test_format_set(self):
        ti = utils.create_test_instance()
        ti.unit_test_info.test.formatting = "%.5f"
        ti.unit_test_info.test.type = "composite"
        ti.unit_test_info.test.save()

        f = forms.UpdateTestInstanceForm(instance=ti)
        assert f.fields['value'].widget.attrs['data-formatted'] == "1.00000"

    def test_attachments_to_process(self):
        ti = utils.create_test_instance()
        u = utils.create_user()
        filename = "TESTRUNNER.tmp"
        filepath = os.path.join(settings.TMP_UPLOAD_ROOT, filename)

        f = ContentFile("", filepath)

        a = Attachment.objects.create(testinstance=ti, created_by=u, attachment=f)
        f = forms.UpdateTestInstanceForm(instance=ti)
        f.cleaned_data = {'user_attached': "%d" % a.pk}
        assert f.attachments_to_process == [(ti.unit_test_info.pk, a)]


# Fixed by qatrackplus/qatrackplus#873, which derives every date format from one setting.
FIXED_BY_873 = pytest.mark.xfail(
    strict=True, raises=(AssertionError, ValueError, ValidationError),
    reason='forms render dates in another format than the pickers read until qatrackplus/qatrackplus#873',
)


class TestDateFieldsUseTheDatePickersFormats(TestCase):
    """The perform page's date boxes are filled by Django and read by Flatpickr. A value
    rendered in another format than the picker's is silently misread and then submitted:
    "13 Oct 2026 00:42" as Work Started became 11 Jan 2026. So the forms must render,
    and accept, exactly the pickers' formats, in every language.
    """

    def make_instance(self, test_type, **values):
        uti = utils.create_unit_test_info(test=utils.create_test(test_type=test_type))
        ti = utils.create_test_instance(unit_test_info=uti, value=None)
        for field, value in values.items():
            setattr(ti, field, value)
        ti.save()
        return ti

    def rendered_value(self, bound_field):
        return bound_field.field.widget.format_value(bound_field.value())

    @FIXED_BY_873
    def test_work_started_default_is_now_in_the_pickers_format(self):
        before = timezone.localtime().replace(second=0, microsecond=0)
        for language in ('en', 'fr'):
            with translation.override(language):
                form = forms.CreateTestListInstanceForm()
                shown = timezone.datetime.strptime(self.rendered_value(form['work_started']), picker_format())
            assert before <= timezone.make_aware(shown) <= timezone.localtime(), language

    @FIXED_BY_873
    def test_saved_date_and_time_results_are_shown_in_the_pickers_format(self):
        when = timezone.make_aware(timezone.datetime(2026, 9, 30, 22, 35))
        date_ti = self.make_instance(models.DATE, date_value=when.date())
        datetime_ti = self.make_instance(models.DATETIME, datetime_value=when)
        for language in ('en', 'fr'):
            with translation.override(language):
                date_form = forms.UpdateTestInstanceForm(instance=date_ti)
                datetime_form = forms.UpdateTestInstanceForm(instance=datetime_ti)
                assert self.rendered_value(date_form['date_value']) == when.strftime(
                    picker_format('FLATPICKR_DATE_FMT')), language
                assert self.rendered_value(datetime_form['datetime_value']) == when.strftime(picker_format()), language

    @FIXED_BY_873
    def test_pickers_formats_are_accepted_in_every_language(self):
        when = timezone.make_aware(timezone.datetime(2026, 9, 30, 22, 35))
        ti = self.make_instance(models.DATETIME, datetime_value=when)
        for language in ('en', 'fr', 'fr-ca', 'es'):
            with translation.override(language):
                form = forms.UpdateTestInstanceForm(instance=ti)
                date_text = when.strftime(picker_format('FLATPICKR_DATE_FMT'))
                assert form.fields['date_value'].clean(date_text) == when.date(), language
                assert form.fields['datetime_value'].clean(when.strftime(picker_format())) == when, language
