"""Tests for the read-only Perform QC preview shown in the Test List admin."""

import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse

from qatrack.qa import models
from qatrack.units.models import Unit

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


class TestPerformTestListPreview(TestCase):
    """The Perform QC preview for a test list on no machine (Test List admin, no machine picked)."""

    def setUp(self):
        utils.create_status()
        self.test_list = utils.create_test_list("No machine list")
        self.t_simple = utils.create_test(name="simple")
        self.t_bool = utils.create_test(name="yesno", test_type=models.BOOLEAN)
        self.t_mc = utils.create_test(name="choice", test_type=models.MULTIPLE_CHOICE, choices="a,b,c")
        self.t_const = utils.create_test(name="const", test_type=models.CONSTANT, constant_value=1.5)
        self.t_upload = utils.create_test(name="upload", test_type=models.UPLOAD)
        self.t_comp = utils.create_test(name="comp", test_type=models.COMPOSITE)
        self.t_comp.calculation_procedure = "result = simple + const"
        self.t_comp.save()
        tests = [self.t_simple, self.t_bool, self.t_mc, self.t_const, self.t_upload, self.t_comp]
        for idx, test in enumerate(tests):
            utils.create_test_list_membership(self.test_list, test, idx)
        self.child = utils.create_test_list("Child list")
        self.t_child = utils.create_test(name="childtest")
        utils.create_test_list_membership(self.child, self.t_child, 0)
        utils.create_sublist(parent_test_list=self.test_list, child_test_list=self.child, order=len(tests))
        self.url = reverse("perform_testlist_preview", kwargs={"pk": self.test_list.pk})

        self.editor = User.objects.create_user("tl_editor", password="pw")
        self.editor.user_permissions.add(*Permission.objects.filter(
            codename__in=["change_testlist", "can_view_ref_tol", "can_view_history", "change_unittestinfo"],
        ))
        self.editor.is_staff = True
        self.editor.save()
        self.performer = User.objects.create_user("performer", password="pw")
        self.performer.user_permissions.add(Permission.objects.get(codename="add_testlistinstance"))

    def test_renders_every_test_with_no_ref_or_tolerance(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["preview"])
        self.assertTemplateUsed(resp, "qa/testlistinstance_form.html")
        forms = resp.context["formset"].forms
        self.assertEqual([f.unit_test_info.test for f in forms], list(self.test_list.ordered_tests()))
        for form in forms:
            uti = form.unit_test_info
            self.assertIsNone(uti.pk)
            self.assertIsNone(uti.reference)
            self.assertIsNone(uti.tolerance)
        content = resp.content.decode()
        self.assertIn("This is only a preview. Nothing you enter here is saved.", content)
        self.assertIn("var qa_preview = true;", content)
        self.assertIn("var unit_id = null;", content)
        self.assertIn('<input type="hidden" id="unit-id" value=""/>', content)
        self.assertIn('<input type="hidden" id="unit-test-collection-id" value=""/>', content)
        self.assertIn("No Ref", content)
        # no saved unit settings, so no reference & tolerance edit links
        self.assertNotIn("ref-tol-link", content)
        self.assertNotIn('id="submit-qa"', content)
        self.assertIn("No machine", content)

    def test_writes_nothing(self):
        counts = lambda: (  # noqa: E731
            models.UnitTestCollection.objects.count(), models.UnitTestInfo.objects.count(),
            Unit.objects.count(),
            models.TestListInstance.objects.count(), models.AutoSave.objects.count(),
        )
        before = counts()
        self.client.login(username="tl_editor", password="pw")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(counts(), before)

    def test_ignores_existing_assignments(self):
        """Even when the list is assigned somewhere, this preview uses no machine's values."""
        utc = utils.create_unit_test_collection(test_collection=self.test_list)
        uti = models.UnitTestInfo.objects.get(unit=utc.unit, test=self.t_simple)
        uti.reference = utils.create_reference(value=42)
        uti.save()
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(all(f.unit_test_info.pk is None for f in resp.context["formset"].forms))
        self.assertIn("Perform No machine : No machine list", resp.content.decode())

    def test_forbidden_without_change_testlist(self):
        self.client.login(username="performer", password="pw")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_post_not_allowed(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.post(self.url, {"form-TOTAL_FORMS": "0", "form-INITIAL_FORMS": "0"})
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(models.TestListInstance.objects.count(), 0)

    def test_allows_same_origin_framing(self):
        self.client.login(username="tl_editor", password="pw")
        self.assertEqual(self.client.get(self.url)["X-Frame-Options"], "SAMEORIGIN")

    def test_missing_test_list_is_404(self):
        self.client.login(username="tl_editor", password="pw")
        resp = self.client.get(reverse("perform_testlist_preview", kwargs={"pk": self.test_list.pk + 100}))
        self.assertEqual(resp.status_code, 404)


class TestUnitlessCompositeCalculation(TestCase):
    """Composite tests on the no-machine preview are calculated without a unit."""

    def setUp(self):
        self.test_list = utils.create_test_list("Composite list")
        self.t1 = utils.create_test(name="test1")
        self.tc = utils.create_test(name="testc", test_type=models.COMPOSITE)
        self.tc.calculation_procedure = "result = test1 * 2"
        self.tc.save()
        for idx, test in enumerate([self.t1, self.tc]):
            utils.create_test_list_membership(self.test_list, test, idx)
        self.editor = User.objects.create_user("tl_editor", password="pw")
        self.editor.user_permissions.add(Permission.objects.get(codename="change_testlist"))
        self.performer = User.objects.create_user("performer", password="pw")
        self.performer.user_permissions.add(Permission.objects.get(codename="add_testlistinstance"))

    def calculate(self, username, **extra):
        self.client.login(username=username, password="pw")
        data = {
            "tests": {"test1": 3, "testc": ""},
            "meta": {},
            "test_list_id": self.test_list.pk,
            "unit_id": "",
            "skips": {"test1": False, "testc": False},
            "comments": {},
        }
        data.update(extra)
        resp = self.client.post(reverse("composite"), data=json.dumps(data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_preview_calculates_without_unit(self):
        result = self.calculate("tl_editor", preview=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["results"]["testc"]["value"], 6)

    def test_missing_unit_still_rejected_outside_preview(self):
        result = self.calculate("tl_editor", preview=False)
        self.assertFalse(result["success"])
        self.assertIn("Invalid or missing unit_id", result["errors"])

    def test_missing_unit_rejected_without_change_testlist(self):
        result = self.calculate("performer", preview=True)
        self.assertFalse(result["success"])
        self.assertIn("Invalid or missing unit_id", result["errors"])

    def test_preview_flag_does_not_drop_a_real_unit(self):
        unit = utils.create_unit()
        for test in (self.t1, self.tc):
            utils.create_unit_test_info(test=test, unit=unit)
        result = self.calculate("tl_editor", preview=True, unit_id=unit.pk)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["results"]["testc"]["value"], 6)
