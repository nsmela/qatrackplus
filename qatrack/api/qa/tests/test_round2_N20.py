from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from qatrack.qa import models
from qatrack.qa.tests import utils


class TestReferenceDisplay(APITestCase):
    """Older Yes/No references were saved with the numerical type (value 1/0).

    The API keeps returning the stored `type`/`value` as-is, and adds a
    read-only `reference_display` that reads the test so these show Yes/No.
    """

    def setUp(self):
        self.user = utils.create_user()
        self.client.force_authenticate(user=self.user)
        utils.create_status()

        self.unit = utils.create_unit()
        self.bool_test = utils.create_test(name="booltest", test_type=models.BOOLEAN)
        self.num_test = utils.create_test(name="numtest")
        self.test_list = utils.create_test_list("test list")
        utils.create_test_list_membership(self.test_list, self.bool_test, order=0)
        utils.create_test_list_membership(self.test_list, self.num_test, order=1)
        self.utc = utils.create_unit_test_collection(test_collection=self.test_list, unit=self.unit)

        # legacy reference: numerical type, value 1.0, on a Boolean test
        self.legacy_ref = utils.create_reference(name="legacy", ref_type=models.NUMERICAL, value=1.0)
        self.bool_uti = models.UnitTestInfo.objects.get(unit=self.unit, test=self.bool_test)
        self.bool_uti.reference = self.legacy_ref
        self.bool_uti.save()

        self.num_ref = utils.create_reference(name="num", ref_type=models.NUMERICAL, value=1.0)
        self.num_uti = models.UnitTestInfo.objects.get(unit=self.unit, test=self.num_test)
        self.num_uti.reference = self.num_ref
        self.num_uti.save()

    def test_unit_test_info_reference_display_legacy_boolean(self):
        resp = self.client.get(reverse("unittestinfo-detail", kwargs={"pk": self.bool_uti.pk}))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["reference_display"] == "Yes"
        # existing field unchanged: still a link to the reference
        assert resp.data["reference"].endswith(reverse("reference-detail", kwargs={"pk": self.legacy_ref.pk}))

    def test_unit_test_info_reference_display_numerical(self):
        resp = self.client.get(reverse("unittestinfo-detail", kwargs={"pk": self.num_uti.pk}))
        assert resp.data["reference_display"] == "1"

    def test_unit_test_info_no_reference(self):
        self.num_uti.reference = None
        self.num_uti.save()
        resp = self.client.get(reverse("unittestinfo-detail", kwargs={"pk": self.num_uti.pk}))
        assert resp.data["reference"] is None
        assert resp.data["reference_display"] == ""

    def test_reference_endpoint_unchanged(self):
        resp = self.client.get(reverse("reference-detail", kwargs={"pk": self.legacy_ref.pk}))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["type"] == models.NUMERICAL
        assert resp.data["value"] == 1.0
        assert "reference_display" not in resp.data

    def test_perform_response_includes_reference_display(self):
        data = {
            "unit_test_collection": reverse("unittestcollection-detail", kwargs={"pk": self.utc.pk}),
            "work_completed": "2019-07-25 10:49:47",
            "work_started": "2019-07-25 10:49:00",
            "tests": {
                "booltest": {"value": True},
                "numtest": {"value": 1},
            },
        }
        resp = self.client.post(reverse("testlistinstance-list"), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        tests = resp.data["tests"]
        assert tests["booltest"]["reference_display"] == "Yes"
        assert tests["booltest"]["reference"].endswith(
            reverse("reference-detail", kwargs={"pk": self.legacy_ref.pk})
        )
        assert tests["numtest"]["reference_display"] == "1"
