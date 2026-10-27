"""Round 2, N27: no Django 4.2 "default.html" form template deprecation warnings.

Django 4.1+ warns (RemovedInDjango50Warning) whenever a form or formset is
rendered through its default template, e.g. a bare ``{{ form }}``. The only
place QATrack+ did that was the review page (``qa/testlistinstance_review.html``),
which now renders ``{{ form.as_table }}``: identical markup, no warning.
"""

import warnings

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils.deprecation import RemovedInDjango50Warning

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qa.views.forms import ReviewTestListInstanceForm


class TestReviewPageFormRendering(TestCase):

    def setUp(self):
        self.status = utils.create_status()
        self.test_list = utils.create_test_list()
        self.test = utils.create_test(name="test_simple")
        utils.create_test_list_membership(self.test_list, self.test)
        self.utc = utils.create_unit_test_collection(test_collection=self.test_list)
        self.tli = utils.create_test_list_instance(unit_test_collection=self.utc)
        uti = models.UnitTestInfo.objects.get(unit=self.utc.unit, test=self.test)
        self.ti = utils.create_test_instance(self.tli, unit_test_info=uti, value=1, status=self.status)
        self.url = reverse("review_test_list_instance", kwargs={"pk": self.tli.pk})

    def _get_with_warnings_as_errors(self, method, *args, **kwargs):
        with warnings.catch_warnings():
            warnings.simplefilter("error", RemovedInDjango50Warning)
            return getattr(self.client, method)(*args, **kwargs)

    def test_review_page_renders_without_deprecation_warning(self):
        user = User.objects.create_superuser("n27admin", "n27@example.com", "password")
        self.client.force_login(user)
        response = self._get_with_warnings_as_errors("get", self.url)
        self.assertEqual(response.status_code, 200)

    def test_review_page_with_form_errors_renders_without_deprecation_warning(self):
        """The review form's only output is its non-field error; render that path too."""
        user = User.objects.create_user("n27reviewer", "n27r@example.com", "password")
        user.user_permissions.add(Permission.objects.get(codename="can_review", content_type__app_label="qa"))
        self.tli.created_by = user
        self.tli.save()
        self.client.force_login(user)
        data = {
            "testinstance_set-TOTAL_FORMS": "1",
            "testinstance_set-INITIAL_FORMS": "1",
            "testinstance_set-MAX_NUM_FORMS": "",
            "testinstance_set-0-id": self.ti.pk,
            "testinstance_set-0-value": 1,
            "testinstance_set-0-status": self.status.pk,
        }
        response = self._get_with_warnings_as_errors("post", self.url, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You do not have the required permission to review your own tests.")

    def test_as_table_markup_matches_previous_bare_render(self):
        """``as_table`` produces exactly what the old ``{{ form }}`` produced."""
        user = User.objects.create_user("n27other", "n27o@example.com", "password")
        self.tli.created_by = user
        self.tli.save()
        form = ReviewTestListInstanceForm(data={}, instance=self.tli, user=user)
        form.is_valid()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RemovedInDjango50Warning)
            old = str(form)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RemovedInDjango50Warning)
            new = form.as_table()
        self.assertEqual(old, new)
        self.assertIn("errorlist nonfield", new)
