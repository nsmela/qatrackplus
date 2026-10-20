"""Tests for the fault details page: its htmx sections, pickers and review box."""

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from qatrack.faults import forms
from qatrack.faults.models import FaultType
from qatrack.faults.tests import utils
from qatrack.qa.tests import utils as qa_utils
from qatrack.service_log.tests import utils as sl_utils

HTMX = {"HTTP_HX_REQUEST": "true"}


def section_url(fault, section, edit=False):
    name = "fault_section_edit" if edit else "fault_section_detail"
    return reverse(name, kwargs={"pk": fault.pk, "section": section})


class FaultDetailsTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser("faultuser", "a@b.com", "password")
        self.client.force_login(self.user)
        self.unit = qa_utils.create_unit()
        self.fault_type = utils.create_fault_type(code="MLC", slug="mlc", description="MLC interlock")
        self.fault = utils.create_fault(unit=self.unit, fault_type=self.fault_type, user=self.user)

    def login_with_perms(self, *codenames):
        user = User.objects.create_user("limited", "limited@example.com", "password")
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(user)
        return user


class TestDetailsPage(FaultDetailsTestCase):

    def test_sections_load_read_only(self):
        """Edit forms and their widgets are only fetched when a pencil is clicked."""
        resp = self.client.get(reverse("fault_details", kwargs={"pk": self.fault.pk}))
        content = resp.content.decode()
        assert resp.status_code == 200
        for section in ["occurrence", "fault-types", "related-ses", "attachments"]:
            assert 'id="fault-section-%s"' % section in content
            assert section_url(self.fault, section, edit=True) in content
        assert "select2(" not in content
        assert "flatpickr(" not in content
        assert 'name="fault-fault_types_field"' not in content
        assert "MLC interlock" in content

    def test_delete_page_is_read_only(self):
        resp = self.client.get(reverse("fault_delete", kwargs={"pk": self.fault.pk}))
        content = resp.content.decode()
        assert resp.status_code == 200
        assert 'id="fault-section-fault-types"' in content
        assert section_url(self.fault, "fault-types", edit=True) not in content


class TestSections(FaultDetailsTestCase):

    def test_unknown_section_is_404(self):
        assert self.client.get(section_url(self.fault, "bogus")).status_code == 404
        assert self.client.get(section_url(self.fault, "bogus", edit=True)).status_code == 404

    def test_sections_need_change_permission(self):
        self.login_with_perms()
        assert self.client.get(section_url(self.fault, "fault-types", edit=True)).status_code == 403

    def test_edit_form_lists_current_fault_types(self):
        resp = self.client.get(section_url(self.fault, "fault-types", edit=True), **HTMX)
        content = resp.content.decode()
        assert resp.status_code == 200
        assert 'data-editing="1"' in content
        assert 'name="fault-fault_types_field" value="MLC"' in content

    def test_invalid_save_is_422_with_errors(self):
        """Removing every fault type isn't allowed; the form comes back with its error."""
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), {}, **HTMX)
        assert resp.status_code == 422
        assert 'class="fl-errors"' in resp.content.decode()
        assert list(self.fault.fault_types.all()) == [self.fault_type]

    def test_invalid_occurrence_save_is_422(self):
        data = {"fault-occurred": "", "fault-unit": "", "fault-modality": ""}
        resp = self.client.post(section_url(self.fault, "occurrence", edit=True), data, **HTMX)
        assert resp.status_code == 422

    def test_save_returns_read_mode_with_last_modified(self):
        other = utils.create_fault_type(code="BEAM", slug="beam")
        data = {"fault-fault_types_field": ["MLC", "BEAM"]}
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        content = resp.content.decode()
        assert resp.status_code == 200
        assert 'data-editing="0"' in content
        assert "fl-saved" in content
        assert 'id="fault-last-modified" hx-swap-oob="true"' in content
        assert set(self.fault.fault_types.all()) == {self.fault_type, other}

    def test_new_fault_type_gets_its_description(self):
        data = {
            "fault-fault_types_field": ["MLC", forms.NEW_FAULT_TYPE_MARKER + "VACUUM"],
            "new_fault_type_desc-VACUUM": "  Waveguide vacuum fault  ",
        }
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        assert resp.status_code == 200
        vacuum = FaultType.objects.get(code="VACUUM")
        assert vacuum.description == "Waveguide vacuum fault"
        assert vacuum in self.fault.fault_types.all()

    def test_new_code_reuses_type_differing_only_by_case(self):
        data = {"fault-fault_types_field": [forms.NEW_FAULT_TYPE_MARKER + "mlc"]}
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        assert resp.status_code == 200
        assert FaultType.objects.filter(code__iexact="mlc").count() == 1
        assert list(self.fault.fault_types.all()) == [self.fault_type]

    def test_creating_a_type_needs_add_permission(self):
        """The picker hides "Create" without the permission; a direct post is refused too."""
        self.login_with_perms("change_fault")
        data = {"fault-fault_types_field": ["MLC", forms.NEW_FAULT_TYPE_MARKER + "VACUUM"]}
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        assert resp.status_code == 422
        assert "permission to create new fault types" in resp.content.decode()
        assert not FaultType.objects.filter(code="VACUUM").exists()

    def test_reusing_an_existing_type_needs_no_add_permission(self):
        self.login_with_perms("change_fault")
        data = {"fault-fault_types_field": [forms.NEW_FAULT_TYPE_MARKER + "mlc"]}
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        assert resp.status_code == 200

    def test_new_type_description_cannot_fill_in_an_existing_blank_one(self):
        """Describing an existing type needs change_faulttype, even when its description is blank."""
        blank = utils.create_fault_type(code="BLANK", slug="blank")
        self.login_with_perms("change_fault", "add_faulttype")
        data = {
            "fault-fault_types_field": [forms.NEW_FAULT_TYPE_MARKER + "blank"],
            "new_fault_type_desc-blank": "sneaky",
        }
        resp = self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        assert resp.status_code == 200
        blank.refresh_from_db()
        assert blank.description == ""

    def test_new_type_description_does_not_overwrite_existing_one(self):
        data = {
            "fault-fault_types_field": [forms.NEW_FAULT_TYPE_MARKER + "mlc"],
            "new_fault_type_desc-mlc": "something else",
        }
        self.client.post(section_url(self.fault, "fault-types", edit=True), data, **HTMX)
        self.fault_type.refresh_from_db()
        assert self.fault_type.description == "MLC interlock"


class TestFaultTypePicker(FaultDetailsTestCase):

    def picker(self, q, selected=()):
        url = reverse("fault_type_picker", kwargs={"pk": self.fault.pk})
        return self.client.get(url, {"q": q, "fault-fault_types_field": list(selected)}, **HTMX)

    def test_short_query_returns_nothing(self):
        resp = self.picker("M")
        assert resp.status_code == 200
        assert resp.content.strip() == b""

    def test_matches_code_and_description(self):
        utils.create_fault_type(code="VACUUM", slug="vacuum", description="Waveguide MLC-adjacent fault")
        content = self.picker("MLC").content.decode()
        assert ">MLC<" in content
        assert ">VACUUM<" in content

    def test_excludes_types_already_in_the_form(self):
        utils.create_fault_type(code="MLC-DRIFT", slug="mlc-drift")
        content = self.picker("MLC", selected=["MLC"]).content.decode()
        assert ">MLC-DRIFT<" in content
        assert ">MLC<" not in content

    def test_offers_create_when_nothing_matches_exactly(self):
        content = self.picker("MLC-NEW").content.decode()
        assert "Create “MLC-NEW”" in content

    def test_no_create_for_an_exact_match_in_any_case(self):
        content = self.picker("mlc").content.decode()
        assert "Create" not in content

    def test_no_create_without_add_permission(self):
        self.login_with_perms("change_fault")
        content = self.picker("MLC-NEW").content.decode()
        assert "Create" not in content

    def test_row_for_existing_type(self):
        url = reverse("fault_type_picker_row", kwargs={"pk": self.fault.pk})
        content = self.client.get(url, {"code": "mlc"}, **HTMX).content.decode()
        assert 'name="fault-fault_types_field" value="MLC"' in content

    def test_row_for_new_type(self):
        url = reverse("fault_type_picker_row", kwargs={"pk": self.fault.pk})
        content = self.client.get(url, {"code": "VACUUM"}, **HTMX).content.decode()
        assert 'value="%sVACUUM"' % forms.NEW_FAULT_TYPE_MARKER in content
        assert 'name="new_fault_type_desc-VACUUM"' in content

    def test_new_type_row_needs_add_permission(self):
        self.login_with_perms("change_fault")
        url = reverse("fault_type_picker_row", kwargs={"pk": self.fault.pk})
        assert self.client.get(url, {"code": "VACUUM"}, **HTMX).status_code == 403

    def test_picker_needs_change_permission(self):
        self.login_with_perms()
        assert self.picker("MLC").status_code == 403


class TestServiceEventPicker(FaultDetailsTestCase):

    def setUp(self):
        super().setUp()
        usa = sl_utils.create_unit_service_area(unit=self.unit)
        self.se = sl_utils.create_service_event(unit_service_area=usa, problem_description="Replaced MLC motor")
        other_usa = sl_utils.create_unit_service_area(unit=qa_utils.create_unit())
        self.other_se = sl_utils.create_service_event(unit_service_area=other_usa, problem_description="Other unit")

    def picker(self, q="", selected=()):
        url = reverse("fault_se_picker", kwargs={"pk": self.fault.pk})
        return self.client.get(url, {"q": q, "fault-related_service_events": list(selected)}, **HTMX)

    def test_only_service_events_on_the_faults_unit(self):
        content = self.picker().content.decode()
        assert "#%d" % self.se.pk in content
        assert "#%d" % self.other_se.pk not in content

    def test_searches_descriptions_and_ids(self):
        assert "#%d" % self.se.pk in self.picker("motor").content.decode()
        assert "#%d" % self.se.pk in self.picker("#%d" % self.se.pk).content.decode()
        assert "#%d" % self.se.pk not in self.picker("nothing like it").content.decode()

    def test_excludes_service_events_already_in_the_form(self):
        content = self.picker(selected=[str(self.se.pk)]).content.decode()
        assert "#%d" % self.se.pk not in content

    def test_row_for_service_event(self):
        url = reverse("fault_se_picker_row", kwargs={"pk": self.fault.pk})
        content = self.client.get(url, {"se": self.se.pk}, **HTMX).content.decode()
        assert 'name="fault-related_service_events" value="%d"' % self.se.pk in content

    def test_row_for_another_units_service_event_is_404(self):
        url = reverse("fault_se_picker_row", kwargs={"pk": self.fault.pk})
        assert self.client.get(url, {"se": self.other_se.pk}, **HTMX).status_code == 404

    def test_saving_related_service_events(self):
        data = {"fault-related_service_events": [str(self.se.pk)]}
        resp = self.client.post(section_url(self.fault, "related-ses", edit=True), data, **HTMX)
        assert resp.status_code == 200
        assert list(self.fault.related_service_events.all()) == [self.se]


class TestFaultTypeDescriptionEdit(FaultDetailsTestCase):

    def url(self):
        return reverse("fault_type_edit_description", kwargs={"slug": self.fault_type.slug})

    def test_htmx_save_returns_the_row(self):
        resp = self.client.post(self.url(), {"description-mlc": "Leaf interlock"}, **HTMX)
        assert resp.status_code == 200
        assert "Leaf interlock" in resp.content.decode()
        self.fault_type.refresh_from_db()
        assert self.fault_type.description == "Leaf interlock"

    def test_json_save_still_works(self):
        resp = self.client.post(self.url(), {"description": "Leaf interlock"})
        assert resp.json() == {"status": "success", "description": "Leaf interlock"}

    def test_editor_shown_with_change_faulttype(self):
        content = self.client.get(section_url(self.fault, "fault-types", edit=True), **HTMX).content.decode()
        assert 'name="description-mlc"' in content
        assert "data-fl-desc-edit" in content

    def test_description_read_only_without_change_faulttype(self):
        """Someone who can edit the fault but not fault types sees the description
        but gets no way to change it, and the server refuses it anyway."""
        self.login_with_perms("change_fault")
        content = self.client.get(section_url(self.fault, "fault-types", edit=True), **HTMX).content.decode()
        assert "MLC interlock" in content
        assert 'name="description-mlc"' not in content
        assert "data-fl-desc-edit" not in content

        resp = self.client.post(self.url(), {"description-mlc": "changed"}, **HTMX)
        assert resp.status_code == 403
        self.fault_type.refresh_from_db()
        assert self.fault_type.description == "MLC interlock"

    def test_missing_description_changes_nothing(self):
        resp = self.client.post(self.url(), {})
        assert resp.status_code == 400
        self.fault_type.refresh_from_db()
        assert self.fault_type.description == "MLC interlock"


class TestReviewFromDetailsPage(FaultDetailsTestCase):

    def test_htmx_acknowledge_returns_record_box_and_status(self):
        resp = self.client.post(reverse("fault_review", kwargs={"pk": self.fault.pk}), **HTMX)
        content = resp.content.decode()
        assert resp.status_code == 200
        assert 'id="fault-section-record"' in content
        assert 'id="fault-review-status" hx-swap-oob="true"' in content
        assert "Unacknowledge" in content
        assert self.fault.faultreviewinstance_set.exists()

    def test_htmx_unacknowledge(self):
        utils.create_fault_review(fault=self.fault)
        resp = self.client.post(reverse("fault_review", kwargs={"pk": self.fault.pk}), **HTMX)
        assert "Acknowledge fault" in resp.content.decode()
        assert not self.fault.faultreviewinstance_set.exists()


class TestExpiredSession(FaultDetailsTestCase):

    def test_htmx_request_sends_the_whole_page_to_login(self):
        """A logged-out htmx request must not swap the login page into a section."""
        self.client.logout()
        page = "http://testserver" + reverse("fault_details", kwargs={"pk": self.fault.pk}) + "?tab=1"
        resp = self.client.get(section_url(self.fault, "fault-types", edit=True), HTTP_HX_CURRENT_URL=page, **HTMX)
        assert resp.status_code == 204
        assert resp["HX-Redirect"] == "/accounts/login/?next=/faults/%d/%%3Ftab%%3D1" % self.fault.pk

    def test_next_never_points_off_site(self):
        self.client.logout()
        resp = self.client.get(
            section_url(self.fault, "fault-types"), HTTP_HX_CURRENT_URL="https://evil.example/steal", **HTMX
        )
        assert resp["HX-Redirect"] == "/accounts/login/?next=/steal"

    def test_normal_requests_still_redirect(self):
        self.client.logout()
        resp = self.client.get(reverse("fault_details", kwargs={"pk": self.fault.pk}))
        assert resp.status_code == 302
