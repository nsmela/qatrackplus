import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone, translation

from qatrack.attachments.models import Attachment
from qatrack.qa import models
from qatrack.qa.views import forms

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


class TestDateFieldsUseTheDatePickersFormats(TestCase):
    """The perform page's date boxes are filled and read by Flatpickr in fixed formats
    (FLATPICKR_DATE_FMT 'd M Y' and FLATPICKR_DATETIME_FMT 'Y-m-d H:i', in every
    language). A value rendered in any other format is silently misread by the
    picker and then submitted, so the forms must render, and accept, exactly those.
    """

    PICKER_DATE = '%d %b %Y'
    PICKER_DATETIME = '%Y-%m-%d %H:%M'

    def make_instance(self, test_type, **values):
        uti = utils.create_unit_test_info(test=utils.create_test(test_type=test_type))
        ti = utils.create_test_instance(unit_test_info=uti, value=None)
        for field, value in values.items():
            setattr(ti, field, value)
        ti.save()
        return ti

    def rendered_value(self, bound_field):
        return bound_field.field.widget.format_value(bound_field.value())

    def test_work_started_default_is_now_in_the_pickers_format(self):
        before = timezone.localtime().replace(second=0, microsecond=0)
        for language in ('en', 'fr'):
            with translation.override(language):
                form = forms.CreateTestListInstanceForm()
                shown = timezone.datetime.strptime(self.rendered_value(form['work_started']), self.PICKER_DATETIME)
            assert before <= timezone.make_aware(shown) <= timezone.localtime(), language

    def test_saved_date_and_time_results_are_shown_in_the_pickers_format(self):
        when = timezone.make_aware(timezone.datetime(2026, 9, 30, 22, 35))
        date_ti = self.make_instance(models.DATE, date_value=when.date())
        datetime_ti = self.make_instance(models.DATETIME, datetime_value=when)
        for language in ('en', 'fr'):
            with translation.override(language):
                date_form = forms.UpdateTestInstanceForm(instance=date_ti)
                datetime_form = forms.UpdateTestInstanceForm(instance=datetime_ti)
                assert self.rendered_value(date_form['date_value']) == '30 Sep 2026', language
                assert self.rendered_value(datetime_form['datetime_value']) == '2026-09-30 22:35', language

    def test_pickers_formats_are_accepted_in_every_language(self):
        ti = self.make_instance(models.DATETIME, datetime_value=timezone.now())
        for language in ('en', 'fr', 'fr-ca', 'es'):
            with translation.override(language):
                form = forms.UpdateTestInstanceForm(instance=ti)
                assert form.fields['date_value'].clean('30 Sep 2026') == timezone.datetime(2026, 9, 30).date()
                assert form.fields['datetime_value'].clean('2026-09-30 22:35') == timezone.make_aware(
                    timezone.datetime(2026, 9, 30, 22, 35)
                ), language
