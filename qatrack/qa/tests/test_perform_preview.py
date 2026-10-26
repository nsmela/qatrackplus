"""Tests for the read-only Perform QC preview shown in the Test List admin."""

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse

from qatrack.qa import models

from . import utils


class TestPerformQAPreview(TestCase):

    def setUp(self):
        utils.create_status()
        self.test_list = utils.create_test_list("Preview list")
        self.t_simple = utils.create_test(name="simple")
        self.t_bool = utils.create_test(name="yes no", test_type=models.BOOLEAN)
        self.t_upload = utils.create_test(name="upload", test_type=models.UPLOAD)
        for idx, test in enumerate([self.t_simple, self.t_bool, self.t_upload]):
            utils.create_test_list_membership(self.test_list, test, idx)
        self.utc = utils.create_unit_test_collection(test_collection=self.test_list)
        self.url = reverse("perform_qa_preview", kwargs={"pk": self.utc.pk})

        self.editor = User.objects.create_user("tl_editor", password="pw")
        self.editor.user_permissions.add(Permission.objects.get(codename="change_testlist"))
        self.performer = User.objects.create_user("performer", password="pw")
        self.performer.user_permissions.add(Permission.objects.get(codename="add_testlistinstance"))

    def test_get_renders_real_page_in_preview_mode(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["preview"])
        self.assertEqual(resp.context["unit_test_collection"], self.utc)
        self.assertEqual(len(resp.context["formset"].forms), 3)
        self.assertTemplateUsed(resp, "qa/testlistinstance_form.html")
        content = resp.content.decode()
        self.assertIn("This is only a preview. Nothing you enter here is saved.", content)
        self.assertIn('class="qa-preview-banner" role="status"', content)
        self.assertIn("qa-preview", content)
        self.assertIn("var qa_preview = true;", content)
        self.assertIn('onsubmit="return false;"', content)
        self.assertNotIn('id="submit-qa"', content)
        self.assertNotIn('name="in_progress"', content)

    def test_preview_ignores_group_visibility(self):
        """Visibility only decides whose lists an assignment shows up in."""
        self.utc.visible_to.clear()
        self.client.login(username="tl_editor", password="pw")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_real_perform_page_has_no_preview_markers(self):
        self.performer.groups.add(*Group.objects.all())
        self.client.login(username="performer", password="pw")
        resp = self.client.get(reverse("perform_qa", kwargs={"pk": self.utc.pk}))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("This is only a preview", content)
        self.assertIn("var qa_preview = false;", content)
        self.assertIn('id="submit-qa"', content)

    def test_forbidden_without_change_testlist(self):
        self.client.login(username="performer", password="pw")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_post_saves_nothing(self):
        data = {
            "form-TOTAL_FORMS": "3",
            "form-INITIAL_FORMS": "0",
            "form-0-value": "1",
            "work_started": "2020-01-01 10:00",
        }
        for username, status in (("tl_editor", 405), ("performer", 403)):
            self.client.login(username=username, password="pw")
            resp = self.client.post(self.url, data)
            self.assertEqual(resp.status_code, status)
        self.assertEqual(models.TestListInstance.objects.count(), 0)
        self.assertEqual(models.TestInstance.objects.count(), 0)

    def test_allows_same_origin_framing(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(self.url)
        self.assertEqual(resp["X-Frame-Options"], "SAMEORIGIN")

    def test_missing_utc_is_404(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(reverse("perform_qa_preview", kwargs={"pk": self.utc.pk + 100}))
        self.assertEqual(resp.status_code, 404)
