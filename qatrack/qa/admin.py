import json
import math
import re

from django import VERSION, forms
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers, options, widgets
from django.contrib.admin.helpers import flatten_fieldsets
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.template import loader
from django.template.defaultfilters import date as date_formatter
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.text import Truncator, slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.utils.translation import ngettext
from django_mptt_admin.admin import DjangoMpttAdmin
from dynamic_raw_id.admin import DynamicRawIDMixin
from dynamic_raw_id.widgets import DynamicRawIDWidget

from qatrack.attachments.admin import (
    SaveInlineAttachmentUserMixin,
    get_attachment_inline,
)
from qatrack.qa import models
from qatrack.qa.utils import format_qc_value
from qatrack.qa.views import admin as admin_views
from qatrack.qatrack_core import scheduling
from qatrack.qatrack_core.admin import (
    BaseQATrackAdmin,
    BasicSaveUserAdmin,
    SaveUserMixin,
)
from qatrack.units.forms import unit_site_unit_type_choices
from qatrack.units.models import Site, Unit

admin.site.disable_action("delete_selected")


class QCAdminDesignMixin:
    """Shared look for the QC admin pages (admin/qa/change_form.html and change_list.html).

    The templates themselves are picked up by Django's admin/<app>/ lookup; this mixin
    makes every list filter start collapsed (admin/qa/shared/filter.html) and carries
    the optional card settings read by qatrack/qa/templatetags/qc_admin.py:
    qc_fieldset_icons, qc_wide_fields and qc_inline_icons.
    """

    qc_fieldset_icons = {}
    qc_wide_fields = ()
    qc_inline_icons = {}

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        for spec in cl.filter_specs:
            if spec.template == "admin/filter.html":
                spec.template = "admin/qa/shared/filter.html"
        return cl


# How many tests the Category page's Used In card lists before pointing to the Test list.
CATEGORY_USED_IN_LIMIT = 20


class CategoryAdmin(QCAdminDesignMixin, DjangoMpttAdmin):
    """QC categories admin"""
    prepopulated_fields = {
        'slug': ('name',)
    }
    list_display = (
        "name",
        "get_description",
    )
    # One Details card, parent first (admin/qa/category/change_form.html adds Used In).
    fields = ("parent", "name", "slug", "description")
    qc_wide_fields = ("parent",)
    # django-mptt-admin's tree and grid lists, with the QC title row on top.
    change_tree_template = "admin/qa/category/change_list.html"
    change_list_template = "admin/qa/category/grid_view.html"

    @admin.display(description=_l("Description"))
    def get_description(self, obj):
        """Just used to disable ordering by description"""
        return obj.description if obj else ""

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        """Context for the Used In card: the tests filed under this category."""
        context["qcc_tests"] = []
        context["qcc_test_count"] = 0
        if obj is not None and obj.pk:
            tests = obj.test_set.order_by("name")
            context["qcc_test_count"] = tests.count()
            context["qcc_tests"] = list(tests[:CATEGORY_USED_IN_LIMIT])
            context["qcc_tests_more"] = context["qcc_test_count"] - len(context["qcc_tests"])
            context["qcc_child_count"] = obj.get_children().count()
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)


def parse_reference_number(value):
    """The reference typed for a numerical test, as a finite float.

    Raises forms.ValidationError for anything else ("abc", "1,5", "nan", "inf"):
    Reference.value is a FloatField, so saving text there would fail with a
    server error, and an infinite or NaN reference would make every result fail.
    """
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        number = None
    if number is None or not math.isfinite(number):
        raise forms.ValidationError(
            _("Enter the reference as a number, using a point for decimals (for example 1.5)."),
            code="invalid_reference",
        )
    return number


class UnitTestInfoForm(forms.ModelForm):
    """Form for UnitTestInfo model"""

    reference_value = forms.CharField(label=_("New reference value"), required=False)
    reference_set_by = forms.CharField(label=_("Set by"), required=False)
    reference_set = forms.CharField(label=_("Date"), required=False)
    test_type = forms.CharField(required=False)
    comment = forms.CharField(
        label=_l("Comment"),
        widget=forms.Textarea,
        required=False,
        help_text=_("Include an optional comment about why this reference/tolerance is being updated")
    )

    class Meta:
        model = models.UnitTestInfo
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        readonly = (
            "test_type",
            "reference_set_by",
            "reference_set",
        )
        instance = kwargs.get('instance')

        if instance and instance.test:
            # Set test type
            self.fields['test_type'].initial = instance.test.get_type_display()

            # Set reference information if reference exists
            if instance.reference:
                self.fields['reference_set_by'].initial = getattr(instance.reference, 'created_by', 'Unknown')
                # Format the date to be more readable and in user's timezone
                created_date = getattr(instance.reference, 'created', None)
                if created_date:
                    # Use Django's timezone handling which respects site timezone settings
                    if timezone.is_aware(created_date):
                        local_date = timezone.localtime(created_date)
                    else:
                        local_date = created_date
                    self.fields['reference_set'].initial = local_date.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    self.fields['reference_set'].initial = 'Unknown'

            # Filter tolerances based on test type
            if instance.test.type == models.BOOLEAN:
                self.fields['tolerance'].queryset = models.Tolerance.objects.filter(type=models.BOOLEAN)
                self.fields['reference_value'] = forms.ChoiceField(
                    choices=[("", "---"), (0, "No"), (1, "Yes")], required=False, label=_("New reference value")
                )
            elif instance.test.is_string_type():
                # STRING and STRING_COMPOSITE as well as MULTIPLE_CHOICE: a string
                # test is judged by comparing its value against a multiple choice
                # tolerance's pass and tolerance lists, which is what
                # TestInstance.string_pass_fail() does for every string type. A
                # string test has no numerical reference, so the field is hidden.
                self.fields['tolerance'].queryset = models.Tolerance.objects.filter(type=models.MULTIPLE_CHOICE)
                self.fields['reference_value'].widget = forms.HiddenInput()
            elif instance.test.type == models.WRAPAROUND:
                # A percentage of a wraparound value is not meaningful.
                self.fields['tolerance'].queryset = models.Tolerance.objects.filter(type=models.ABSOLUTE)
                self.fields['reference_value'].widget = forms.TextInput()
            else:
                # For numerical tests, exclude boolean and multiple choice tolerances
                self.fields['tolerance'].queryset = models.Tolerance.objects.exclude(
                    type__in=[models.BOOLEAN, models.MULTIPLE_CHOICE]
                )
                self.fields['reference_value'].widget = forms.TextInput()

        if not isinstance(self.fields['reference_value'].widget, forms.HiddenInput):
            self.fields['reference_value'].help_text = _(
                "Leave this blank to keep the current reference. Enter a value only when you want to change it."
            )

        for field in readonly:
            self.fields[field].widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()

        if not self.instance or not self.instance.test:
            return cleaned_data

        reference_value = cleaned_data.get("reference_value", "")
        if not self._reference_value_changed():
            # left as it was: save() keeps the current reference, so check that one
            reference_value = self._kept_reference_value()
        tolerance = cleaned_data.get("tolerance")

        test = self.instance.test
        numerical = not (test.type == models.BOOLEAN or test.is_string_type())
        if numerical and self._reference_value_changed() and reference_value not in (None, ""):
            try:
                parse_reference_number(reference_value)
            except forms.ValidationError as e:
                # the checks below would only repeat this in other words
                self.add_error('reference_value', e)
                return cleaned_data

        # Validate percent tolerance requires numerical reference
        if tolerance and tolerance.type == models.PERCENT:
            if reference_value is None or reference_value == "":
                self.add_error('reference_value', _("A reference value is required when using a percent tolerance"))
            else:
                try:
                    val = float(reference_value)
                    if val == 0:
                        self.add_error(
                            'reference_value', _("Reference value cannot be zero when using a percent tolerance")
                        )
                except ValueError:
                    self.add_error(
                        'reference_value', _("A numerical reference value is required when using a percent tolerance")
                    )

        # Validate wraparound tests
        if self.instance.test.type == models.WRAPAROUND:
            try:
                if reference_value is not None and reference_value != "":
                    val = float(reference_value)
                    if val < self.instance.test.wrap_low or val > self.instance.test.wrap_high:
                        self.add_error(
                            'reference_value',
                            _("Reference value must be between %(low)s and %(high)s for wraparound tests") % {
                                'low': self.instance.test.wrap_low,
                                'high': self.instance.test.wrap_high
                            }
                        )
            except ValueError:
                self.add_error('reference_value', _("Reference value must be a number for wraparound tests"))

        return cleaned_data

    _KEEP_REFERENCE = object()

    def _reference_value_changed(self):
        """True when the user changed the reference field from what the form showed.

        The Unit Test Info admin page shows the field empty, so there leaving it
        blank means "keep the current reference". The builder's Reference and
        Tolerance dialog (MachineRefTolForm) shows the current value, so there an
        untouched value keeps it and emptying the field clears it on purpose.
        """
        return 'reference_value' in self.cleaned_data and 'reference_value' in self.changed_data

    def _kept_reference_value(self):
        """The value of the reference save() keeps when the field is left as it was."""
        if self.instance.reference_id and self.instance.reference is not None:
            return self.instance.reference.value
        return ""

    def _reference_for_validation(self):
        """The reference save() is about to attach, as an unsaved Reference (or None).

        Returns _KEEP_REFERENCE when save() leaves the stored reference alone.
        Only the value matters here: it's what UnitTestInfo.clean checks.
        """
        if not self._reference_value_changed():
            return self._KEEP_REFERENCE
        reference_value = self.cleaned_data['reference_value']
        if reference_value is None or reference_value == '':
            return None
        try:
            value = float(reference_value)
        except (TypeError, ValueError):
            # not a number: clean() has already reported it where it matters
            return None
        return models.Reference(value=value, name=str(reference_value), type=models.NUMERICAL)

    def _post_clean(self):
        # UnitTestInfo.clean checks the tolerance against instance.reference, but
        # the new Reference is only attached in save(). Show the model the pending
        # reference while it validates, then put the stored one back so nothing
        # changes on the instance if the form is invalid.
        stored = self.instance.reference if self.instance.reference_id else None
        pending = self._reference_for_validation() if self.instance.test_id else self._KEEP_REFERENCE
        if self.has_error('reference_value'):
            # clean() already said what's wrong with the reference; don't repeat it
            pending = None
        if pending is not self._KEEP_REFERENCE:
            self.instance.reference = pending
        try:
            super()._post_clean()
        finally:
            if pending is not self._KEEP_REFERENCE and self.instance.reference is pending:
                self.instance.reference = stored

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Handle reference value conversion
        reference_value = self.cleaned_data.get('reference_value')

        # Get the user from the form's initial data (set by FormWithRequest)
        user = self.initial.get('modified_by')

        if not self._reference_value_changed():
            # Left blank (or, in the builder's dialog, unchanged): keep the
            # current Reference rather than clearing it or saving a copy.
            pass
        elif reference_value is not None and reference_value != '':  # Non-empty reference value
            if instance.test.type == models.BOOLEAN:
                value = bool(int(reference_value))
            elif instance.test.type == models.MULTIPLE_CHOICE:
                value = reference_value
            else:
                # For numerical tests, try to preserve the original type from the form data
                # If the original form data contained a numeric type, keep it as a number
                # If it was a string, keep it as a string
                original_value = self.data.get('reference_value')
                if original_value and not isinstance(original_value, str):
                    # Original was numeric, convert to float
                    try:
                        value = float(reference_value)
                    except (ValueError, TypeError):
                        value = reference_value
                else:
                    # Original was string or None, keep as string
                    value = reference_value

            ref = models.Reference(
                value=value,
                name=str(value),
                type=models.BOOLEAN if instance.test.type == models.BOOLEAN else models.NUMERICAL,
                created_by=user,
                modified_by=user,
            )
            ref.save()
            instance.reference = ref
        else:
            # A value the form showed was emptied on purpose (only possible in the
            # builder's dialog, which starts with the current value filled in).
            instance.reference = None

        if commit:
            instance.save()
        return instance


def reference_value_changed(old_reference, new_reference, test=None):
    """True when ``new_reference`` holds a different value (or type) than ``old_reference``.

    Saving a reference creates a new Reference row even when the value is the
    same, so comparing the objects themselves would call every save a change.
    Going from no reference to one (or back) counts as a change. On Boolean
    tests the type is ignored: older Yes/No references were stored with the
    numerical type, and re-saving one as Boolean doesn't change its meaning.
    """
    if old_reference is None or new_reference is None:
        return (old_reference is None) != (new_reference is None)
    # a freshly saved Reference can still hold the submitted string ("100") or
    # bool in memory, so compare the values as the database stores them
    to_python = models.Reference._meta.get_field("value").to_python
    if to_python(old_reference.value) != to_python(new_reference.value):
        return True
    if test is not None and test.is_boolean():
        return False
    return old_reference.type != new_reference.type


def record_unit_test_info_change(uti, old_reference, old_tolerance, comment, user, changed_fields):
    """Add a history entry (UnitTestInfoChange) for a reference/tolerance change.

    Shared by the UnitTestInfo admin page and the test list builder's Reference
    and Tolerance dialog, so both keep the same history. ``changed_fields`` is the
    form's ``changed_data``; nothing is recorded unless the comment, reference or
    tolerance was touched. ``reference_changed`` is only set when the reference
    value actually differs (see ``reference_value_changed``); tolerances are
    picked from shared records, so comparing them directly is already accurate.
    Returns the new entry, or None.
    """
    if not uti or not uti.pk:
        return None
    if not any(k in changed_fields for k in ('comment', 'reference_value', 'tolerance')):
        return None
    return models.UnitTestInfoChange.objects.create(
        unit_test_info=uti,
        comment=comment,
        reference=old_reference,
        reference_changed=reference_value_changed(old_reference, uti.reference, uti.test),
        tolerance=old_tolerance,
        tolerance_changed=old_tolerance != uti.tolerance,
        changed_by=user,
    )


@admin.display(ordering="test__name")
def test_name(obj):
    return obj.test.name


@admin.display(ordering="test__type")
def test_type(obj):
    for tt, display in models.TEST_TYPE_CHOICES:
        if obj.test.type == tt:
            return display


# What the Set References & Tolerances action can give several tests at once. Every
# selected test must be of one kind, so one tolerance and one reference suit them all.
SET_MULTIPLE_BOOLEAN = "boolean"
SET_MULTIPLE_STRING = "string"
SET_MULTIPLE_NUMERICAL = "numerical"


def set_multiple_kind(test):
    """The set-multiple kind of a test, or None for one that never uses limits."""
    if test.type in NO_LIMIT_TEST_TYPES:
        return None
    if test.is_boolean():
        return SET_MULTIPLE_BOOLEAN
    if test.is_string_type():
        return SET_MULTIPLE_STRING
    return SET_MULTIPLE_NUMERICAL


def set_multiple_tolerance_types(test):
    """Tolerance types UnitTestInfoForm accepts for this test (see its __init__)."""
    if test.is_boolean():
        return {models.BOOLEAN}
    if test.is_string_type():
        return {models.MULTIPLE_CHOICE}
    if test.type == models.WRAPAROUND:
        return {models.ABSOLUTE}
    return {models.ABSOLUTE, models.PERCENT}


class SetMultipleReferencesAndTolerancesForm(forms.Form):
    """The Set References & Tolerances action's page: one reference, tolerance and
    comment for every selected test. Blank keeps each test's current value; "No
    tolerance" clears it. Each test is then validated and saved with
    UnitTestInfoForm, the form the single-test page uses (see
    UnitTestInfoAdmin.set_multiple_references_and_tolerances).
    """

    KEEP = ""
    CLEAR = "none"

    tolerance = forms.ChoiceField(label=_l("Tolerance"), required=False)
    reference = forms.CharField(
        label=_l("Reference"),
        required=False,
        help_text=_l("Leave this blank to keep each test's current reference."),
    )
    comment = forms.CharField(
        label=_l("Comment"),
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text=_l("Why are you changing these? Saved with each test's history."),
    )

    def __init__(self, *args, kind=None, tolerance_types=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        tolerances = models.Tolerance.objects.filter(type__in=tolerance_types).order_by("type", "pk")
        self.tolerances = {str(t.pk): t for t in tolerances}
        self.fields["tolerance"].choices = [
            (self.KEEP, _("Keep each test's current tolerance")),
            (self.CLEAR, _("No tolerance (clear it)")),
        ] + [(pk, tol.plain_display()) for pk, tol in self.tolerances.items()]
        if kind == SET_MULTIPLE_BOOLEAN:
            self.fields["reference"] = forms.ChoiceField(
                label=_("Reference"),
                required=False,
                choices=[(self.KEEP, _("Keep each test's current reference")), ("0", _("No")), ("1", _("Yes"))],
            )
        elif kind == SET_MULTIPLE_STRING:
            # string tests are judged by their tolerance's choices alone
            del self.fields["reference"]

    def clean_reference(self):
        value = self.cleaned_data.get("reference")
        value = "" if value is None else str(value).strip()
        # (Boolean tests: the select only allows "", "0" and "1", so nothing to do.)
        if self.kind == SET_MULTIPLE_NUMERICAL and value:
            # once here, rather than once per selected test
            parse_reference_number(value)
        return value

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            # a field already says what's wrong (e.g. a reference that isn't a
            # number, which leaves "reference" out of cleaned_data); don't add a
            # banner claiming both were left blank
            return cleaned
        if cleaned.get("tolerance", self.KEEP) == self.KEEP and not cleaned.get("reference"):
            if self.kind == SET_MULTIPLE_STRING:
                # these tests have no reference field
                raise forms.ValidationError(_("Choose a tolerance: leaving it as it is would change nothing."))
            raise forms.ValidationError(
                _("Choose a tolerance or enter a reference: leaving both as they are would change nothing.")
            )
        return cleaned

    def unit_test_info_data(self, uti):
        """The data UnitTestInfoForm gets for one selected test."""
        tolerance = self.cleaned_data["tolerance"]
        if tolerance == self.KEEP:
            tolerance = uti.tolerance_id or ""
        elif tolerance == self.CLEAR:
            tolerance = ""
        return {
            "tolerance": tolerance,
            "reference_value": self.cleaned_data.get("reference", ""),
            "comment": self.cleaned_data.get("comment", ""),
        }


class SetMultipleUnitTestInfoForm(UnitTestInfoForm):
    """UnitTestInfoForm for one test of the Set References & Tolerances action: the
    same tolerance filtering, validation and Reference creation, for just the
    tolerance and reference."""

    class Meta:
        model = models.UnitTestInfo
        fields = ["tolerance"]


# see http://stackoverflow.com/questions/851636/default-filter-in-django-admin
class ActiveUnitTestInfoFilter(admin.SimpleListFilter):

    NOTACTIVE = 'notactive'
    ACTIVE = 'active'

    title = _('Active Unit Assignments')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'activeassignment'

    def lookups(self, request, model_admin):
        return (
            (None, _('All')),
            (self.ACTIVE, _('At Least One Active Unit Assignment')),
            (self.NOTACTIVE, _('No Active Unit Assignments')),
        )

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': cl.get_query_string({
                    self.parameter_name: lookup,
                }, []),
                'display': title,
            }

    def queryset(self, request, qs):
        if self.value() == self.NOTACTIVE:
            return models.UnitTestInfo.objects.inactive(qs)
        elif self.value() == self.ACTIVE:
            return models.UnitTestInfo.objects.active(qs)
        return qs


def unit_test_info_missing_html(uti, part):
    """What the Unit Test Info pages show for a reference (``part="reference"``) or
    tolerance that isn't set.

    Uses the Test List builder's rule (machine_limit_usage, which mirrors
    TestInstance.calculate_pass_fail): "Not set" is highlighted only when this test
    type needs the value, because then its results on Perform QC show No Tol Set.
    A type that never uses it says "Not used"; an optional one (a Boolean test's
    tolerance) is a plain "Not set".
    """
    usage = machine_limit_usage(uti.test)
    use = usage[part]
    if use == "unused":
        if usage["uses_limits"]:
            why = _("This test type doesn't use a reference: its results are judged by the tolerance alone.")
        else:
            why = _("Limits don't apply to this test type: its results never pass or fail.")
        return format_html('<span class="qcr-unused" title="{}">{}</span>', why, _("Not used"))
    if use == "required":
        title = _("No limits set: results on %(unit)s will show No Tol Set") % {"unit": uti.unit.name}
        return format_html(
            '<span class="qcr-missing" title="{}"><i class="fa fa-exclamation-circle" aria-hidden="true"></i>{}'
            '<span class="tl-visually-hidden">: {}</span></span>',
            title, _("Not set"), title,
        )
    return format_html('<span class="qcr-none">{}</span>', _("Not set"))


def unit_test_info_reference_html(uti):
    """The reference as the Unit Test Info list and Details card show it (HTML):
    Yes/No for Boolean tests, "Not set" / "Not used" when there's none."""
    if uti.reference is None:
        return unit_test_info_missing_html(uti, "reference")
    return escape(uti.reference.value_display(uti.test))


def unit_test_info_tolerance_html(uti):
    """The tolerance as the Unit Test Info list and Details card show it: its stored
    name (as before), with the plain-language reading as a tooltip."""
    if uti.tolerance_id is None:
        return unit_test_info_missing_html(uti, "tolerance")
    return format_html('<span title="{}">{}</span>', uti.tolerance.plain_display_title(), uti.tolerance)


class UnitTestInfoAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    """Admin interface for UnitTestInfo model"""

    change_list_template = "admin/qa/unittestinfo/change_list.html"
    form = UnitTestInfoForm
    actions = ["set_multiple_references_and_tolerances"]

    # admin/qa/unittestinfo/change_form.html draws these as three cards: Details (a
    # read-only description list of what's set now), Reference & Tolerance (the
    # form) and History.
    fieldsets = (
        (None, {
            'fields': (
                'unit',
                'test',
                'reference_display',
                'tolerance_display',
            )
        }),
        (
            _('Reference & Tolerance'), {
                'fields': (
                    'test_type',
                    'reference_set_by',
                    'reference_set',
                    'reference_value',
                    'tolerance',
                    'comment',
                ),
            }
        ),
        (_('History'), {
            'fields': ('history',),
        }),
    )

    list_display = [test_name, "unit", test_type, "reference_display", "tolerance_display"]
    list_filter = [
        ActiveUnitTestInfoFilter, "unit__site", "unit", "test__category", "test__testlistmembership__test_list"
    ]
    # "reference" stays read-only (so the form never edits it) though the page
    # shows reference_display, which reads Yes/No for Boolean tests.
    readonly_fields = ("reference", "reference_display", "tolerance_display", "test", "unit", "history")
    search_fields = ("test__name", "test__display_name", "test__slug", "unit__name")

    def get_fields(self, request, obj=None):
        """Override to ensure form-only fields are included"""
        form = self.get_form(request, obj, fields=None)
        return list(form.base_fields) + list(self.get_readonly_fields(request, obj))

    def get_form(self, request, obj=None, **kwargs):
        """Override to ensure form-only fields are handled correctly"""
        if 'fields' in kwargs:
            fields = kwargs.pop('fields')
        else:
            fields = flatten_fieldsets(self.get_fieldsets(request, obj))
        if obj is not None and not self.has_change_permission(request, obj):
            # View-only: Django would leave every field out of the form, but
            # UnitTestInfoForm needs its tolerance field to set up (without it the
            # page fails to load). Build the whole form: Django still shows every
            # field read-only and refuses to save it.
            kwargs['change'] = False
        FormClass = super().get_form(request, obj, fields=fields, **kwargs)

        class FormWithRequest(FormClass):

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.initial['modified_by'] = request.user

        return FormWithRequest

    @admin.display(description=_l("Reference"), ordering="reference__value")
    def reference_display(self, obj):
        """The reference as the list column and the read-only field show it.

        Used in place of the plain str(reference) so Boolean tests read Yes/No
        even for older references stored with the numerical type. An empty one
        says "Not set" (highlighted when it causes No Tol Set) or "Not used".
        """
        if obj is None:
            return None
        return unit_test_info_reference_html(obj)

    @admin.display(description=_l("Tolerance"), ordering="tolerance")
    def tolerance_display(self, obj):
        """The tolerance's name, or "Not set" / "Not used" like reference_display."""
        if obj is None:
            return None
        return unit_test_info_tolerance_html(obj)

    @admin.display(description=_l("Set"))
    def set_ref_tol(self, obj):
        """A pencil that opens the Test List builder's Reference and Tolerance dialog
        (testlist_machine_ref_tol) for this row. Only listed for users who may change
        references and tolerances (get_list_display); nothing for test types that
        never use limits, as in the builder."""
        if not machine_limit_usage(obj.test)["uses_limits"]:
            return ""
        label = _("Set reference and tolerance for %(test)s on %(unit)s") % {
            "test": obj.test.name, "unit": obj.unit.name,
        }
        return format_html(
            '<button type="button" class="qcr-reftol-btn" aria-haspopup="dialog" data-uti-id="{}"'
            ' data-reftol-url="{}" title="{}" aria-label="{}"><i class="fa fa-pencil" aria-hidden="true"></i></button>',
            obj.pk, reverse("admin:qa_testlist_machine_ref_tol", args=[obj.pk]), label, label,
        )

    def get_list_display(self, request):
        list_display = list(super().get_list_display(request))
        if self.has_change_permission(request):
            list_display.append("set_ref_tol")
        return list_display

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['qcr_history_count'] = models.UnitTestInfoChange.objects.filter(
            unit_test_info_id=object_id,
        ).count() if str(object_id).isdigit() else 0
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description=_("Reference & Tolerance History"))
    def history(self, obj):
        """Display history of reference and tolerance changes"""
        if not obj:
            return _("No history available")

        changes = models.UnitTestInfoChange.objects.filter(unit_test_info=obj).order_by('-changed')

        if not changes:
            return _("No history available")

        # Each UnitTestInfoChange stores the values from *before* that change.
        # The values *after* a change are the ones stored on the next newer
        # change, or the current values on the UnitTestInfo for the newest
        # change.  Walk back from the present (newest first) pairing them up.
        def display(value):
            if value is None:
                return ""
            if isinstance(value, models.Reference):
                # pass the test so older Yes/No references stored as 1/0 read Yes/No
                return value.value_display(obj.test)
            return str(value)

        def part(before, after, flagged):
            before, after = display(before), display(after)
            # Only call it a change when the flag is set *and* the displayed value
            # differs. New entries only set reference_changed for a real change,
            # but older entries in existing databases were flagged on every save
            # (a new Reference object is created each time), so keep this check
            # for them.
            return {'before': before, 'after': after, 'changed': bool(flagged) and before != after}

        history = []
        after_ref, after_tol = obj.reference, obj.tolerance
        for change in changes:
            history.append({
                'change': change,
                'reference': part(change.reference, after_ref, change.reference_changed),
                'tolerance': part(change.tolerance, after_tol, change.tolerance_changed),
            })
            after_ref, after_tol = change.reference, change.tolerance

        t = loader.get_template("admin/qa/unittestinfo/history.html")
        return t.render({'history': history})

    def save_model(self, request, test_info, form, change):
        # Fetch the old instance from the DB before saving changes
        if test_info.pk:
            old = models.UnitTestInfo.objects.get(pk=test_info.pk)
            old_reference = old.reference
            old_tolerance = old.tolerance
        else:
            old_reference = None
            old_tolerance = None

        # Save the new values
        super().save_model(request, test_info, form, change)

        # Now create the history record using the old values
        record_unit_test_info_change(
            form.instance, old_reference, old_tolerance, form.cleaned_data.get("comment"), request.user,
            form.changed_data,
        )

    @admin.action(description=_l("Set references and tolerances for selected tests"), permissions=["change"])
    def set_multiple_references_and_tolerances(self, request, queryset):
        """Give the selected tests one reference and/or tolerance, with one comment.

        Every selected test is validated with UnitTestInfoForm (the single-test
        page's rules) before anything is saved; then all of them are saved in one
        transaction, each with a history entry. If any test fails, nothing is saved
        and the page shows why. The tests must all be of one kind (numerical,
        Boolean or string), so one tolerance can suit them all.
        """
        def selected():
            return list(
                queryset.select_related("unit", "test", "reference", "tolerance").order_by("unit__name", "test__name")
            )

        utis = selected()
        kinds = {set_multiple_kind(uti.test) for uti in utis}
        if None in kinds:
            self.message_user(
                request,
                _("Upload and date tests don't use references or tolerances. Leave them out of your selection."),
                level=messages.ERROR,
            )
            return None
        if len(kinds) > 1:
            self.message_user(
                request,
                _(
                    "Choose tests of one kind: all numerical, all Boolean (Yes/No) or all text and multiple "
                    "choice. They can't share a tolerance otherwise."
                ),
                level=messages.ERROR,
            )
            return None
        kind = kinds.pop() if kinds else None
        tolerance_types = set.intersection(*(set_multiple_tolerance_types(uti.test) for uti in utis)) if utis else set()

        form_kwargs = {"kind": kind, "tolerance_types": tolerance_types}
        test_errors = []
        if request.POST.get("post") == "yes":
            form = SetMultipleReferencesAndTolerancesForm(request.POST, **form_kwargs)
            if form.is_valid():
                # the values before validation: validating puts the new tolerance on each instance
                old = {uti.pk: (uti.reference, uti.tolerance) for uti in utis}
                uti_forms = [
                    (uti, SetMultipleUnitTestInfoForm(
                        form.unit_test_info_data(uti), instance=uti, initial={"modified_by": request.user},
                    ))
                    for uti in utis
                ]
                for uti, uti_form in uti_forms:
                    if not uti_form.is_valid():
                        errors = [str(e) for field_errors in uti_form.errors.values() for e in field_errors]
                        test_errors.append({"uti": uti, "errors": errors})
                if not test_errors:
                    with transaction.atomic():
                        for uti, uti_form in uti_forms:
                            saved = uti_form.save()
                            old_reference, old_tolerance = old[uti.pk]
                            record_unit_test_info_change(
                                saved, old_reference, old_tolerance, form.cleaned_data.get("comment"), request.user,
                                uti_form.changed_data,
                            )
                    self.message_user(request, ngettext(
                        "Set the reference and tolerance for %(count)d test.",
                        "Set the reference and tolerance for %(count)d tests.",
                        len(utis),
                    ) % {"count": len(utis)}, level=messages.SUCCESS)
                    return None
                # validating put the refused values on each instance: show what is really saved
                utis = selected()
        else:
            form = SetMultipleReferencesAndTolerancesForm(**form_kwargs)

        errors_by_pk = {entry["uti"].pk: entry["errors"] for entry in test_errors}
        context = {
            **self.admin_site.each_context(request),
            'title': _("Set references and tolerances"),
            'queryset': utis,
            'rows': [{"uti": uti, "errors": errors_by_pk.get(uti.pk, [])} for uti in utis],
            'opts': self.model._meta,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'form': form,
            'kind': kind,
            'test_errors': test_errors,
        }
        return TemplateResponse(request, 'admin/qa/unittestinfo/set_multiple_refs_and_tols.html', context)

    class Media:
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "select2/js/select2.js",
            "js/unittestinfo_admin.js",
        )
        css = {
            'all': (
                "qatrack_core/css/admin.css",
                "select2/css/select2.css",
            ),
        }

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'copy-refs-tols/',
                self.admin_site.admin_view(admin_views.CopyReferencesTolerancesView.as_view()),
                name='qa_copy_refs_and_tols'
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['copy_refs_tols_url'] = reverse('admin:qa_copy_refs_and_tols')
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, *args, **kwargs):
        """just display active ref/tols"""
        qs = models.UnitTestInfo.objects.select_related(
            "reference",
            "tolerance",
            "unit",
            "test",
        ).exclude(
            test__hidden=True,
        )
        return qs

    def has_add_permission(self, request):
        """unittestinfo's are created automatically"""
        return False


def _posted_delete(data, form_prefix):
    """True when the posted `<form_prefix>-DELETE` box is ticked.

    Reads the value the same way a formset's DELETE field does (a checkbox
    cleaned by a BooleanField), so "on", "true", "1" count as ticked and
    "false" / missing do not.
    """
    name = "%s-DELETE" % form_prefix
    value = forms.CheckboxInput().value_from_datadict(data, {}, name)
    return forms.BooleanField(required=False).to_python(value)


class TestListAdminForm(forms.ModelForm):
    """Form for handling validation of TestList creation/editing"""

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        dup = models.TestList.objects.exclude(pk=self.instance.pk).filter(slug=slug)
        if dup:
            raise forms.ValidationError(
                _("A test list with the slug '%(test_name)s' already exists in the database") % {'test_name': slug}
            )
        return slug

    # {formset prefix: whether saving deletes the saved rows marked for removal}.
    # TestListAdmin.get_form fills this in from the inlines' delete permission;
    # None means every removal is honoured.
    rows_can_delete = None

    def _removal_honoured(self, row_prefix, formset_prefix):
        """True when the row posted as `<row_prefix>-...` will really be left out on save.

        A row the user just added (no id yet) is always discarded. A saved row is
        only deleted when the user may delete rows of that inline; otherwise
        Django ignores its DELETE box and keeps the row.
        """
        if not _posted_delete(self.data, row_prefix):
            return False
        if self.rows_can_delete is None or not self.data.get("%s-id" % row_prefix):
            return True
        return self.rows_can_delete.get(formset_prefix, False)

    def _posted_ids(self, prefix, field):
        """Return the ids posted in `<prefix>-<n>-<field>`, leaving out rows marked for removal.

        A row the user removed in the builder is still posted (with its DELETE
        box ticked) so Django can delete it; it must not count towards the
        duplicate-name and maximum-size checks, unless the user isn't allowed
        to delete it (then it is saved again, so it still counts).
        """
        pattern = re.compile(r"^%s-(\d+)-%s$" % (re.escape(prefix), re.escape(field)))
        ids = []
        for key, value in self.data.items():
            match = pattern.match(key)
            if match and value and not self._removal_honoured("%s-%s" % (prefix, match.group(1)), prefix):
                ids.append(value)
        return ids

    def clean(self):
        test_ids = self._posted_ids("testlistmembership_set", "test")
        # (macro name, test name) for every test, direct or through a sublist.
        # One entry per posted row (not per distinct test), so the same test
        # added twice directly is reported below like any other duplicate.
        found = {
            str(pk): (slug, name)
            for pk, slug, name in models.Test.objects.filter(id__in=test_ids).values_list("pk", "slug", "name")
        }
        tests = [found[str(test_id)] for test_id in test_ids if str(test_id) in found]

        child_ids = self._posted_ids("children", "child")
        for tl in models.TestList.objects.filter(id__in=child_ids):
            tests.extend(tl.all_tests().values_list("slug", "name"))

        if len(tests) > settings.MAX_TESTS_PER_TESTLIST:
            msg = _(
                "This test list has %(test_count)d tests, counting the tests in its sublists. "
                "A test list can have at most %(max_tests)d. Remove some tests or sublists, then save again."
            ) % {"test_count": len(tests), "max_tests": settings.MAX_TESTS_PER_TESTLIST}
            raise forms.ValidationError(msg)

        slugs = [slug for slug, name in tests]
        duplicates = []
        for slug, name in tests:
            if slugs.count(slug) > 1 and (slug, name) not in duplicates:
                duplicates.append((slug, name))
        if duplicates:
            names = ", ".join(
                _("%(test_name)s (%(macro_name)s)") % {"test_name": name, "macro_name": slug}
                for slug, name in duplicates
            )
            msg = _(
                "These tests appear more than once in this test list, directly or through a sublist: "
                "%(tests)s. Remove the extra copies, then save again."
            ) % {"tests": names}
            raise forms.ValidationError(msg)

        return self.cleaned_data


TYPE_VALUE_MAX_CHARS = 60


def _truncate_type_value(text):
    """Return (display, title) for a type value, shortening long text with "…".

    `title` holds the full text whenever the display had to be shortened, so the
    builder can show it as a tooltip; otherwise it is empty.
    """
    if len(text) <= TYPE_VALUE_MAX_CHARS:
        return text, ""
    return text[:TYPE_VALUE_MAX_CHARS - 1].rstrip() + "…", text


def _format_type_value_number(value):
    """Show whole numbers without a trailing ".0" (e.g. 360.0 -> "360")."""
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _get_test_type_value(test):
    """Return (type_value, type_value_title, type_value_mono) for a test.

    The "type value" is the part of a test's definition that belongs to the test
    itself on every machine: a constant's value, a multiple choice test's
    choices, a wraparound test's range, or a calculated test's procedure.
    References and tolerances are per-machine, so they are not shown here.
    """
    t = test.type
    if t == models.CONSTANT:
        if test.constant_value is None:
            return "", "", False
        if test.formatting:
            value = format_qc_value(test.constant_value, test.formatting)
        else:
            value = str(test.constant_value)
        return value, "", False

    if t == models.MULTIPLE_CHOICE:
        choices = [c.strip() for c in (test.choices or "").split(",") if c.strip()]
        display, title = _truncate_type_value(", ".join(choices))
        return display, title, False

    if t == models.WRAPAROUND:
        if test.wrap_low is None or test.wrap_high is None:
            return "", "", False
        value = _("%(low)s to %(high)s") % {
            "low": _format_type_value_number(test.wrap_low),
            "high": _format_type_value_number(test.wrap_high),
        }
        return value, "", False

    if t in (models.COMPOSITE, models.STRING_COMPOSITE, models.UPLOAD):
        calc = (test.calculation_procedure or "").strip()
        if t == models.UPLOAD and calc.replace(" ", "") == "%s=None" % test.slug:
            # Test.clean_calculation_procedure fills this placeholder in for uploads
            # saved without a procedure, so treat it as "no procedure".
            calc = ""
        if not calc:
            return "", "", False
        first_line = next(line.strip() for line in calc.splitlines() if line.strip())
        display, title = _truncate_type_value(first_line)
        if display != calc:
            title = calc
        return display, title, True

    return "", "", False


def get_test_metadata(test):
    """Return dictionary of serialized test metadata for builder UI rendering."""
    cat_slug = test.category.slug if test.category else "general"
    cat_name = test.category.name if test.category else _("General")

    # Categories and types are each drawn as one neutral chip (.tl-cat-pill,
    # .tl-type-chip, showing the full type name): colour in QATrack+ means QC
    # status, so it isn't used to tell categories or test types apart.
    t = test.type
    if t == models.BOOLEAN:
        type_label = _("Boolean")
    elif t in (models.SIMPLE, models.NUMERICAL):
        type_label = _("Numerical")
    elif t == models.WRAPAROUND:
        type_label = _("Wraparound")
    elif t == models.MULTIPLE_CHOICE:
        type_label = _("Multiple Choice")
    elif t == models.COMPOSITE:
        type_label = _("Composite")
    elif t == models.CONSTANT:
        type_label = _("Constant")
    elif t == models.STRING:
        type_label = _("String")
    elif t == models.STRING_COMPOSITE:
        type_label = _("String Composite")
    elif t == models.UPLOAD:
        type_label = _("File Upload")
    elif t in (models.DATE, models.DATETIME):
        type_label = _("Date") if t == models.DATE else _("Date & Time")
    else:
        type_label = test.get_type_display()

    type_value, type_value_title, type_value_mono = _get_test_type_value(test)

    return {
        "id": test.id,
        "name": test.name,
        "display_name": test.display_name or test.name,
        "slug": test.slug,
        "description": test.description or "",
        "category_name": cat_name,
        "category_slug": cat_slug,
        "type": test.type,
        "type_label": type_label,
        "type_value": type_value,
        "type_value_title": type_value_title,
        "type_value_mono": type_value_mono,
        "edit_url": reverse("admin:qa_test_change", args=[test.id]),
    }


def get_sublist_metadata(child, sublist_pk=None, order=0, outline=False):
    """Return dictionary of serialized sublist metadata including child tests for builder UI rendering."""
    tests = child.ordered_tests()
    tests_meta = [get_test_metadata(t) for t in tests]
    return {
        "sublist_pk": sublist_pk,
        "child_id": child.id,
        "child_name": child.name,
        "child_slug": child.slug,
        "child_description": child.description,
        "test_count": len(tests),
        "tests": tests_meta,
        "order": order,
        "outline": outline,
        "edit_url": reverse("admin:qa_testlist_change", args=[child.id]),
    }


class TestListMembershipInlineFormSet(forms.models.BaseInlineFormSet):

    # The Test List admin turns this off: TestListAdminForm.clean already names
    # a test added twice (with the tests repeated through sublists), so Django's
    # generic "Please correct the duplicate data for test." would only repeat it.
    check_unique = True

    def validate_unique(self):
        if self.check_unique:
            super().validate_unique()

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if instance is None or instance.pk is None:
            # When creating a new TestList, there are no existing memberships
            # (and filtering by an unsaved instance is deprecated in Django)
            qs = kwargs["queryset"].none()
        else:
            qs = kwargs["queryset"].filter(test_list=instance).select_related("test", "test__category")
        kwargs["queryset"] = qs
        super().__init__(*args, **kwargs)

        for form in self.forms:
            # Rows that aren't saved yet (new rows, or every row of a Save As
            # copy) work out their test from the posted data instead (see
            # TestListMembershipForm.test_meta), so they survive a re-render
            # after a validation error.
            if getattr(form.instance, "test_id", None):
                form.test_meta = get_test_metadata(form.instance.test)


class SublistInlineFormSet(forms.models.BaseInlineFormSet):

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if instance is None or instance.pk is None:
            # When creating a new TestList, there are no existing sublists
            # (and filtering by an unsaved instance is deprecated in Django)
            qs = kwargs["queryset"].none()
        else:
            qs = kwargs["queryset"].filter(parent=instance).select_related("child")
        kwargs["queryset"] = qs
        super().__init__(*args, **kwargs)

        for form in self.forms:
            if getattr(form.instance, "child_id", None):
                child = form.instance.child
                # a saved row the user pointed at another list (Change): show
                # the posted child on a re-render, or the next save would undo it
                posted_child = form.data.get(form.add_prefix("child")) if form.is_bound else None
                if posted_child and str(posted_child) != str(form.instance.child_id):
                    child = models.TestList.objects.filter(pk=_int_param(posted_child, 0)).first() or child
                form.sublist_meta = get_sublist_metadata(
                    child,
                    sublist_pk=form.instance.pk,
                    order=form.instance.order,
                    # use the bound value so a re-rendered form (after a
                    # validation error) keeps what the user ticked
                    outline=bool(form["outline"].value()),
                )
            # otherwise SublistForm.sublist_meta works it out from the posted data

    def clean(self):
        """Make sure there are no duplicated slugs in a TestList"""
        super().clean()

        if not hasattr(self, "cleaned_data"):
            # something else went wrong already
            return {}

        children = [
            f.instance.child for f in self.forms if hasattr(f.instance, 'child') and not f.cleaned_data.get("DELETE")
        ]  # noqa: E501
        children_with_child = [child for child in children if child.children.exists()]
        if self.instance and self.instance in children:
            raise forms.ValidationError(
                _("A Test List can not be its own child. Please remove Sublist ID %(sublist_id)d and try again") %
                {'sublist_id': self.instance.pk}
            )
        elif children_with_child:
            names = ', '.join(c.name for c in children_with_child)
            raise forms.ValidationError(
                _(
                    "Test Lists can not be nested more than 1 level. Test List(s) "
                    "%(test_list_names)s already has(have) a sublist and therefore can't be used as a sublist."
                ) % {'test_list_names': names}
            )
        elif self.instance and self.instance.pk and self.instance.sublist_set.exists() and children:
            raise forms.ValidationError(
                _(
                    "This Test List is a Sublist of Test Lists: %(sublist_name)s"
                    " and therefore can't have sublists of its own."
                ) % {'sublist_name': ', '.join(self.instance.sublist_set.values_list("parent__name", flat=True))}
            )

        return self.cleaned_data


def macro_name(obj):
    return obj.test.slug


def _unsaved_and_deleted(form):
    """True for a posted builder row that isn't in the database and was marked for removal."""
    return form.is_bound and not form.instance.pk and _posted_delete(form.data, form.prefix)


class DiscardRemovedNewRowMixin:
    """Treat a new builder row the user removed before saving as an untouched blank row.

    Django only skips rows marked DELETE when the formset can delete, which needs
    the inline's delete permission. A row that was never saved isn't a deletion,
    though, so it's discarded (not validated, not saved) either way.
    """

    def has_changed(self):
        return not _unsaved_and_deleted(self) and super().has_changed()


class TestListMembershipForm(DiscardRemovedNewRowMixin, forms.ModelForm):

    model = models.TestListMembership

    def validate_unique(self):
        """skip unique validation.

        The uniqueness of ('test_list','test',) is already independently checked
        by the formset (looks for duplicate macro names).

        By making validate_unique here a null function, we eliminate a DB call
        per test list membership when saving test lists in the admin.
        """

    @property
    def test_meta(self):
        if not hasattr(self, "_test_meta_cache"):
            test = None
            if _unsaved_and_deleted(self):
                # a new row removed before saving: don't bring it back on a re-render
                pass
            elif getattr(self.instance, "test_id", None):
                test = self.instance.test
            elif self.is_bound and self.data.get(self.add_prefix("test")):
                try:
                    test = models.Test.objects.select_related("category").get(pk=self.data.get(self.add_prefix("test")))
                except models.Test.DoesNotExist:
                    pass
            self._test_meta_cache = get_test_metadata(test) if test else None
        return self._test_meta_cache

    @test_meta.setter
    def test_meta(self, value):
        self._test_meta_cache = value


class SublistForm(DiscardRemovedNewRowMixin, forms.ModelForm):

    model = models.Sublist

    def validate_unique(self):
        """skip unique validation.

        The uniqueness of ('test_list','test',) is already independently checked
        by the formset (looks for duplicate macro names).

        By making validate_unique here a null function, we eliminate a DB call
        per test list membership when saving test lists in the admin.
        """

    @property
    def sublist_meta(self):
        if not hasattr(self, "_sublist_meta_cache"):
            child = None
            if _unsaved_and_deleted(self):
                # a new sublist removed before saving: don't bring it back on a re-render
                pass
            elif getattr(self.instance, "child_id", None):
                child = self.instance.child
            elif self.is_bound and self.data.get(self.add_prefix("child")):
                try:
                    child = models.TestList.objects.get(pk=self.data.get(self.add_prefix("child")))
                except models.TestList.DoesNotExist:
                    pass
            self._sublist_meta_cache = get_sublist_metadata(
                child,
                sublist_pk=self.instance.pk if self.instance else None,
                order=self.instance.order if self.instance else 0,
                outline=bool(self["outline"].value()),
            ) if child else None
        return self._sublist_meta_cache

    @sublist_meta.setter
    def sublist_meta(self, value):
        self._sublist_meta_cache = value


class TestListMembershipInline(DynamicRawIDMixin, admin.TabularInline):

    model = models.TestListMembership
    formset = TestListMembershipInlineFormSet
    form = TestListMembershipForm
    # one spare blank row; admin's "Add another" adds more when it's used
    extra = 1
    template = "admin/qa/testlistmembership/edit_inline/tabular.html"
    readonly_fields = (macro_name,)
    dynamic_raw_id_fields = ("test",)

    def label_for_value(self, value):  # TODO: is this called ever?
        try:
            name = self.test_names[value]
            return '&nbsp;<strong>%s</strong>' % escape(Truncator(name).words(14, truncate='...'))
        except (ValueError, KeyError):
            return ''

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        # copied from django.contrib.admin.wigets (and dynamic_raw_id admin.py)
        # so we can override the label_for_value function for the test raw id widget
        db = kwargs.get('using')
        if db_field.name == "test":
            rel = db_field.remote_field if VERSION[0] >= 2 else db_field.rel
            widget = DynamicRawIDWidget(rel, self.admin_site)
            widget.label_for_value = self.label_for_value
            kwargs['widget'] = widget
            return db_field.formfield(**kwargs)
        elif db_field.name in self.dynamic_raw_id_fields:
            rel = db_field.remote_field if VERSION[0] >= 2 else db_field.rel
            kwargs['widget'] = DynamicRawIDWidget(rel, self.admin_site)
            return db_field.formfield(**kwargs)
        elif db_field.name in self.raw_id_fields:
            kwargs['widget'] = widgets.ForeignKeyRawIdWidget(
                db_field.remote_field if VERSION[0] >= 2 else db_field.rel, self.admin_site, using=db
            )
        elif db_field.name in self.radio_fields:
            kwargs['widget'] = widgets.AdminRadioSelect(
                attrs={
                    'class': options.get_ul_class(self.radio_fields[db_field.name]),
                }
            )
            kwargs['empty_label'] = db_field.blank and _('None') or None
        return db_field.formfield(**kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        # hacky method for getting test names so they don't need to be looked up again
        # in the label_for_value in contrib/admin/widgets.py
        if obj:
            self.test_names = dict(obj.tests.values_list("pk", "name"))
        else:
            self.test_names = {}
        formset = super().get_formset(request, obj, **kwargs)
        # duplicates are reported by TestListAdminForm.clean instead
        formset.check_unique = False
        return formset


class SublistInline(DynamicRawIDMixin, admin.TabularInline):

    model = models.Sublist
    fk_name = "parent"
    formset = SublistInlineFormSet
    form = SublistForm
    extra = 1
    template = "admin/qa/testlistmembership/edit_inline/tabular.html"
    dynamic_raw_id_fields = ("child",)

    def label_for_value(self, value):  # TODO: Is this called ever?
        try:
            name = self.test_list_names[value]
            return '&nbsp;<strong>%s</strong>' % escape(Truncator(name).words(14, truncate='...'))
        except (ValueError, KeyError):
            return ''

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        # copied from django.contrib.admin.wigets so we can override the label_for_value function
        # for the test raw id widget
        db = kwargs.get('using')
        if db_field.name == "child":
            rel = db_field.remote_field if VERSION[0] >= 2 else db_field.rel
            widget = DynamicRawIDWidget(rel, self.admin_site)
            widget.label_for_value = self.label_for_value
            kwargs['widget'] = widget
            return db_field.formfield(**kwargs)

        elif db_field.name in self.dynamic_raw_id_fields:
            rel = db_field.remote_field if VERSION[0] >= 2 else db_field.rel
            kwargs['widget'] = DynamicRawIDWidget(rel, self.admin_site)
            return db_field.formfield(**kwargs)

        elif db_field.name in self.raw_id_fields:
            kwargs['widget'] = widgets.ForeignKeyRawIdWidget(
                db_field.remote_field if VERSION[0] >= 2 else db_field.rel, self.admin_site, using=db
            )
        elif db_field.name in self.radio_fields:
            kwargs['widget'] = widgets.AdminRadioSelect(
                attrs={
                    'class': options.get_ul_class(self.radio_fields[db_field.name]),
                }
            )
            kwargs['empty_label'] = db_field.blank and _('None') or None
        return db_field.formfield(**kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        # hacky method for getting test names so they don't need to be looked up again
        # in the label_for_value in contrib/admin/widgets.py
        if obj:
            self.test_list_names = dict(obj.sublist_set.values_list("pk", "child__name"))
        else:
            self.test_list_names = {}
        return super().get_formset(request, obj, **kwargs)


class CollapsedTestListFilter(admin.SimpleListFilter):
    """Base for the Test Lists page filters: each one starts collapsed."""

    template = "admin/qa/shared/filter.html"


class ActiveTestListFilter(CollapsedTestListFilter):

    NOACTIVEUTCS = 'noactiveutcs'
    HASACTIVEUTCS = 'hasactiveutcs'

    title = _l('Active Unit Assignments')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'activeutcs'

    def lookups(self, request, model_admin):
        return (
            (self.NOACTIVEUTCS, _l('No Active Unit Assignments')),
            (self.HASACTIVEUTCS, _l('At Least One Active Unit Assignment')),
        )

    def queryset(self, request, qs):
        active_tl_ids = models.get_utc_tl_ids(active=True)
        active_sub_tl_ids = list(
            models.TestList.objects.filter(id__in=active_tl_ids,
                                           children__isnull=False).values_list('children__child__id',
                                                                               flat=True).distinct()
        )

        if self.value() == self.NOACTIVEUTCS:
            return qs.exclude(Q(id__in=active_tl_ids) | Q(id__in=active_sub_tl_ids))
        elif self.value() == self.HASACTIVEUTCS:
            return qs.filter(Q(id__in=active_tl_ids) | Q(id__in=active_sub_tl_ids))
        return qs


class UnitTestListFilter(CollapsedTestListFilter):

    title = _l('Assigned to Unit')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'assignedtounit'

    def lookups(self, request, model_admin):
        return Unit.objects.values_list("pk", "name")

    def queryset(self, request, qs):

        if self.value():
            unit = Unit.objects.get(pk=self.value())
            unit_tl_ids = models.get_utc_tl_ids(units=[unit])
            return qs.filter(id__in=unit_tl_ids)

        return qs


class SiteTestListFilter(CollapsedTestListFilter):

    title = _l('Assigned to Site')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'assignedtosite'

    def lookups(self, request, model_admin):
        return Site.objects.values_list("pk", "name")

    def queryset(self, request, qs):

        if self.value():
            site = Site.objects.get(pk=self.value())
            units = Unit.objects.filter(site=site)
            unit_tl_ids = models.get_utc_tl_ids(units=units)
            return qs.filter(id__in=unit_tl_ids)

        return qs


class FrequencyTestListFilter(CollapsedTestListFilter):

    title = _l('Assigned To Units by Frequency')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'assignedbyfreq'

    def lookups(self, request, model_admin):
        return [("adhoc", _("Ad Hoc"))] + list(models.Frequency.objects.values_list("pk", "name"))

    def queryset(self, request, qs):

        v = self.value()
        if v:
            if v == "adhoc":
                freq = None
            else:
                freq = models.Frequency.objects.get(pk=v)
            freq_tl_ids = models.get_utc_tl_ids(frequencies=[freq])
            return qs.filter(id__in=freq_tl_ids)

        return qs


class CategoryTestListFilter(CollapsedTestListFilter):
    """Filter test lists by the categories of the tests they contain."""

    title = _l('Category')
    parameter_name = 'category'

    def lookups(self, request, model_admin):
        cats = models.Category.objects.filter(
            test__testlistmembership__isnull=False
        ).distinct().order_by("name").values_list("pk", "name")
        return list(cats)

    def queryset(self, request, qs):
        v = self.value()
        if v:
            return qs.filter(testlistmembership__test__category__pk=v).distinct()
        return qs


def testlist_description_preview(request):
    """Render a Test List description as HTML for the change-form live preview.

    Wired up via htmx (hx-post from the description textarea). Staff-only (the URL
    is wrapped in admin_view). The description is trusted staff content that is
    already rendered as HTML on the perform page, so it is echoed back as-is.
    """
    text = (request.POST.get("description") or request.GET.get("description") or "").strip()
    if not text:
        html = format_html(
            '<span class="tl-htmlpreview-empty">{}</span>',
            _("Nothing to preview yet. Write a description to see how it will look."),
        )
    else:
        html = text
    return HttpResponse(html)


def testlist_search_tests(request):
    """HTMX endpoint to search tests for the test list builder."""
    q = (request.GET.get("q") or "").strip()
    qs = models.Test.objects.select_related("category").all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(category__name__icontains=q))[:25]
    else:
        qs = qs.order_by("name")[:25]
    results = [get_test_metadata(t) for t in qs]
    return render(request, "admin/qa/testlist/partials/_search_results.html", {
        "results": results,
        "query": q,
        "mode": "test",
    })


def testlist_search_sublists(request):
    """HTMX endpoint to search sublists for the test list builder."""
    q = (request.GET.get("q") or "").strip()
    current_id = request.GET.get("current_id")
    qs = models.TestList.objects.all()
    if current_id:
        try:
            qs = qs.exclude(pk=int(current_id))
        except (ValueError, TypeError):
            pass
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))[:25]
    else:
        qs = qs.order_by("name")[:25]
    results = []
    for tl in qs:
        # Every test the list would bring in, counted the way TestListAdminForm.clean
        # counts them (all_tests: its own tests plus its sublists'), so the builder
        # can mark lists that would repeat a test without another request.
        child_tests = list(tl.all_tests().order_by("name").values_list("id", "name"))
        results.append({
            "id": tl.id,
            "name": tl.name,
            "slug": tl.slug,
            "test_count": tl.tests.count(),
            "child_test_ids": ",".join(str(test_id) for test_id, name in child_tests),
            "child_test_names": json.dumps([name for test_id, name in child_tests]),
        })
    return render(request, "admin/qa/testlist/partials/_search_results.html", {
        "results": results,
        "query": q,
        "mode": "sublist",
    })


def testlist_add_test_row(request):
    """HTMX endpoint to render a new test row."""
    test_id = request.GET.get("test_id")
    index = request.GET.get("index", "0")
    test_list_id = request.GET.get("test_list_id", "")
    test = get_object_or_404(models.Test.objects.select_related("category"), pk=test_id)
    test_meta = get_test_metadata(test)
    return render(request, "admin/qa/testlist/partials/_test_row.html", {
        "test_meta": test_meta,
        "prefix": "testlistmembership_set",
        "index": index,
        "test_list_id": test_list_id,
        "inline_admin_form": None,
    })


def _int_param(value, default=None):
    """``value`` as a non-negative int, or ``default`` if it isn't one."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def testlist_add_sublist_card(request):
    """HTMX endpoint to render a sublist card.

    By default the card is a new sublist at formset row ``index``. With
    ``swap=1`` it's for the builder's Change button: the same saved Sublist row
    (``sublist_id``, ``order`` and ``outline`` are carried over) now pointing at
    a different child list, so saving updates that row instead of deleting it
    and adding a new one.
    """
    child_id = request.GET.get("child_id")
    index = _int_param(request.GET.get("index"), 0)
    parent_id = request.GET.get("parent_id", "")
    child = get_object_or_404(models.TestList, pk=child_id)
    if request.GET.get("swap") == "1":
        sublist_meta = get_sublist_metadata(
            child,
            sublist_pk=_int_param(request.GET.get("sublist_id")),
            order=_int_param(request.GET.get("order"), index),
            outline=request.GET.get("outline") in ("1", "true", "on"),
        )
    else:
        sublist_meta = get_sublist_metadata(child, order=index)
    return render(request, "admin/qa/testlist/partials/_sublist_card.html", {
        "sublist_meta": sublist_meta,
        "prefix": "children",
        "index": index,
        "parent_id": parent_id,
        "inline_admin_form": None,
        # a swapped-in card keeps its saved Sublist row, which only users who may
        # delete sublist rows can remove (SublistInline's delete permission)
        "can_remove": request.user.has_perm("qa.delete_sublist"),
    })


def _copy_unit_test_infos(source, new_test, user):
    """Give ``new_test`` the same references and tolerances as ``source`` on every unit.

    Each reference is copied into a new Reference row so later edits to one test's
    reference never change the other's. Tolerances are shared, reusable records by
    design (the same Tolerance is used by many tests), so those are reused as-is.
    A history entry is recorded on each new unit assignment that got a value.
    """
    comment = _("Copied from %(name)s when duplicating") % {"name": source.name}
    source_utis = models.UnitTestInfo.objects.filter(test=source).select_related("reference", "tolerance", "unit")
    for src in source_utis:
        ref = None
        if src.reference_id:
            ref = models.Reference.objects.create(
                name=src.reference.name,
                type=src.reference.type,
                value=src.reference.value,
                created_by=user,
                modified_by=user,
            )
        # the new test has no unit assignments yet (signals only add them when a
        # test list is saved), but get_or_create keeps unit/test unique regardless
        uti, created = models.UnitTestInfo.objects.get_or_create(
            unit=src.unit,
            test=new_test,
            defaults={"active": src.active, "assigned_to": src.assigned_to},
        )
        old_reference, old_tolerance = uti.reference, uti.tolerance
        uti.reference = ref
        uti.tolerance = src.tolerance
        uti.save()
        if ref is not None or src.tolerance_id:
            record_unit_test_info_change(
                uti, old_reference, old_tolerance, comment, user, ["reference_value", "tolerance"],
            )


def _visible_source_test(request, test_id):
    """The Test to copy from, as the Test admin itself would show it to this user.

    Uses the registered Test admin's own ``get_queryset`` and ``has_view_permission``
    rather than a raw ``Test.objects.get``, so any per-object restriction the Test
    admin ever gains (site, unit, group…) applies here too. Returns a 403 response
    when the user can't view tests at all, raises Http404 for a missing or malformed
    id or a test outside what the Test admin shows them.
    """
    test_admin = admin.site._registry.get(models.Test)
    if test_admin is None or not test_admin.has_view_permission(request):
        return HttpResponseForbidden(_("You don't have permission to view tests. No test was created."))
    try:
        test_id = int(test_id)
    except (TypeError, ValueError):
        raise Http404(_("Test not found"))
    source = get_object_or_404(test_admin.get_queryset(request).select_related("category"), pk=test_id)
    if not test_admin.has_view_permission(request, source):
        return HttpResponseForbidden(_("You don't have permission to view this test. No test was created."))
    return source


@transaction.atomic
def testlist_duplicate_test(request):
    """HTMX / AJAX endpoint to duplicate a Test object, prompting user for new name and copying type, category, calculation, and unit references/tolerances.

    GET only renders the dialog (no changes); POST creates the copy. The admin_view
    wrapper applies CSRF protection to the POST. The new Test is created immediately,
    so this needs permission to add tests, and the source test must be one the Test
    admin lets this user view.
    References and tolerances are only copied for users who can change them
    (``qa.change_unittestinfo``); otherwise the new test starts without any.
    Atomic so a failure while copying never leaves a half-made test behind.
    """
    if request.method not in ("GET", "POST"):
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])
    can_copy_refs_tols = request.user.has_perm("qa.change_unittestinfo")
    if not request.user.has_perm("qa.add_test"):
        return HttpResponseForbidden(_("You don't have permission to add tests. No test was created."))
    source_test_id = request.GET.get("test_id") if request.method == "GET" else request.POST.get("source_test_id")
    source = _visible_source_test(request, source_test_id)
    if isinstance(source, HttpResponse):
        return source

    if request.method == "GET":
        index = request.GET.get("index", "0")
        suggested_name = _("%(name)s (Copy)") % {"name": source.name}
        suggested_slug = slugify(suggested_name)[:128]
        return render(request, "admin/qa/testlist/partials/_duplicate_test_modal.html", {
            "source": source,
            "source_meta": get_test_metadata(source),
            "suggested_name": suggested_name,
            "suggested_slug": suggested_slug,
            "index": index,
            "can_copy_refs_tols": can_copy_refs_tols,
        })

    # POST: create new Test
    new_name = request.POST.get("new_name", "").strip()
    if not new_name:
        return HttpResponseBadRequest(_("Enter a name for the new test. No test was created."))

    new_slug = request.POST.get("new_slug", "").strip()
    if not new_slug:
        new_slug = slugify(new_name)[:128]

    # Ensure unique slug
    base_slug = new_slug
    counter = 1
    while models.Test.objects.filter(slug=new_slug).exists():
        new_slug = f"{base_slug[:120]}_{counter}"
        counter += 1

    # Ensure unique name
    if models.Test.objects.filter(name=new_name).exists():
        return HttpResponseBadRequest(
            _("A test named “%(name)s” already exists. Choose a different name. No test was created.") % {
                "name": new_name,
            },
            # shown with textContent by the builder; plain text so the name is never parsed as HTML
            content_type="text/plain; charset=utf-8",
        )

    new_test = models.Test.objects.create(
        name=new_name,
        display_name=source.display_name,
        slug=new_slug,
        description=source.description,
        procedure=source.procedure,
        category=source.category,
        type=source.type,
        chart_visibility=source.chart_visibility,
        autoreviewruleset=source.autoreviewruleset,
        flag_when=source.flag_when,
        hidden=source.hidden,
        skip_without_comment=source.skip_without_comment,
        require_comment=source.require_comment,
        display_image=source.display_image,
        choices=source.choices,
        constant_value=source.constant_value,
        wrap_low=source.wrap_low,
        wrap_high=source.wrap_high,
        calculation_procedure=source.calculation_procedure,
        formatting=source.formatting,
        created_by=request.user,
        modified_by=request.user,
    )

    if can_copy_refs_tols:
        _copy_unit_test_infos(source, new_test, request.user)
    # Without change_unittestinfo nothing is copied: the new test starts without
    # references/tolerances, and the usual signals create its (empty) unit
    # assignments when the test list is saved on an assigned unit.

    index = request.POST.get("index", "0")
    test_list_id = request.POST.get("test_list_id", "")
    test_meta = get_test_metadata(new_test)

    return render(request, "admin/qa/testlist/partials/_test_row.html", {
        "test_meta": test_meta,
        "prefix": "testlistmembership_set",
        "index": index,
        "test_list_id": test_list_id,
        "inline_admin_form": None,
    })


def _scope_utc_info(utc, via=None):
    """Assignment details for one unit in the builder's Editing dropdown."""
    return {
        "frequency": utc.frequency.name if utc.frequency_id else _("Ad Hoc"),
        "assigned_to": utc.assigned_to.name if utc.assigned_to_id else "",
        "active": utc.active,
        "utc_url": reverse("admin:qa_unittestcollection_change", args=[utc.pk]),
        "via": via,
        "utc_id": utc.pk,
    }


def get_testlist_preview_units(direct, through):
    """What the builder's Preview tab can show for each unit in the Editing dropdown.

    Keyed by unit id (as a string, for JSON). A unit the test list is assigned to
    directly gets ``preview_url``: the read-only Perform QC page for that
    assignment (its first one, if there are several frequencies). A unit that
    gets the list through a parent test list or a cycle gets ``via`` (that
    parent's name), ``via_url`` (its admin page, opened on the same unit) and
    ``via_cycle``; the builder shows the layout-only preview for those.
    """
    units = {}
    for entry in direct:
        units[str(entry["unit_id"])] = {
            "preview_url": reverse("perform_qa_preview", kwargs={"pk": entry["utc_id"]}),
        }
    if not through:
        return units
    utcs = models.UnitTestCollection.objects.in_bulk([entry["utc_id"] for entry in through])
    tl_ct = ContentType.objects.get_for_model(models.TestList)
    for entry in through:
        utc = utcs.get(entry["utc_id"])
        if utc is None:
            continue
        is_cycle = utc.content_type_id != tl_ct.pk
        url_name = "admin:qa_testlistcycle_change" if is_cycle else "admin:qa_testlist_change"
        via_url = reverse(url_name, args=[utc.object_id])
        if not is_cycle:
            via_url += "?unit=%d" % utc.unit_id
        units[str(entry["unit_id"])] = {"via": entry["via"], "via_url": via_url, "via_cycle": is_cycle}
    return units


def get_testlist_scope_units(test_list):
    """Return ``(direct, through)``: the units a test list is performed on.

    ``direct`` holds units the test list itself is assigned to. ``through`` holds
    units that get it through another assignment: a parent test list that uses it
    as a sublist, or a test list cycle that contains it (or one of those parents).
    Each unit appears once, direct assignments first, because the builder's
    machine mode shows per-unit values (UnitTestInfo is per unit and test).
    """
    direct, through = [], []
    if test_list is None or not test_list.pk:
        return direct, through

    tl_ct = ContentType.objects.get_for_model(models.TestList)
    cycle_ct = ContentType.objects.get_for_model(models.TestListCycle)
    utcs = models.UnitTestCollection.objects.select_related(
        "unit", "frequency", "assigned_to",
    ).order_by("unit__name", "pk")

    by_unit = {}
    for utc in utcs.filter(content_type=tl_ct, object_id=test_list.pk):
        if utc.unit_id in by_unit:
            entry = by_unit[utc.unit_id]
            freq = utc.frequency.name if utc.frequency_id else _("Ad Hoc")
            if freq not in entry["frequencies"]:
                entry["frequencies"].append(freq)
            continue
        entry = {"unit_id": utc.unit_id, "unit_name": utc.unit.name, "via": None}
        entry.update(_scope_utc_info(utc))
        entry["frequencies"] = [entry["frequency"]]
        by_unit[utc.unit_id] = entry
        direct.append(entry)
    for entry in direct:
        entry["frequency"] = ", ".join(entry.pop("frequencies"))
        entry["label"] = _("%(unit)s (%(frequency)s)") % {"unit": entry["unit_name"], "frequency": entry["frequency"]}

    parent_ids = list(models.Sublist.objects.filter(child=test_list).values_list("parent_id", flat=True))
    cycle_ids = list(
        models.TestListCycleMembership.objects.filter(
            test_list_id__in=[test_list.pk] + parent_ids,
        ).values_list("cycle_id", flat=True)
    )
    through_q = Q(content_type=tl_ct, object_id__in=parent_ids) | Q(content_type=cycle_ct, object_id__in=cycle_ids)
    for utc in utcs.filter(through_q):
        if utc.unit_id in by_unit:
            continue
        # UnitTestCollection.name is the assigned test list's (or cycle's) name
        entry = {"unit_id": utc.unit_id, "unit_name": utc.unit.name}
        entry.update(_scope_utc_info(utc, via=utc.name))
        entry["label"] = _("%(unit)s (via %(name)s)") % {"unit": entry["unit_name"], "name": utc.name}
        by_unit[utc.unit_id] = entry
        through.append(entry)

    return direct, through


def _machine_reference_display(test, reference):
    """Reference as the UnitTestInfo admin shows it, with Yes/No for Boolean tests."""
    if reference is None or reference.value is None:
        return None
    return reference.value_display(test)


def machine_values_display(uti):
    """The Reference and Tolerance text machine mode shows for one UnitTestInfo.

    Used by testlist_machine_values and the Reference and Tolerance dialog, so a
    saved value reads exactly as it does after a reload. The tolerance is the
    plain wording (Tolerance.plain_display); ``tolerance_title`` explains it and
    keeps the stored name, for the cell's tooltip.
    """
    tol = uti.tolerance if uti.tolerance_id else None
    return {
        "reference": _machine_reference_display(uti.test, uti.reference),
        "tolerance": tol.plain_display() if tol else None,
        "tolerance_title": tol.plain_display_title() if tol else None,
    }


class PlainToleranceSelect(forms.Select):
    """Tolerance select whose options carry Tolerance.plain_display_title as a tooltip."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if isinstance(instance, models.Tolerance):
            option["attrs"]["title"] = instance.plain_display_title()
        return option


# Types TestInstance.calculate_pass_fail never judges against a reference or
# tolerance: an upload has no value to compare and a date can't be compared, so
# their results are always No Tol Set and limits don't apply.
NO_LIMIT_TEST_TYPES = (models.UPLOAD, models.DATE, models.DATETIME)


def machine_limit_usage(test):
    """Which of a unit's reference and tolerance decide this test's pass/fail.

    Mirrors TestInstance.calculate_pass_fail: Boolean tests need a reference (a
    Boolean tolerance is optional), string types need a multiple choice
    tolerance and have no reference, other types with a value need both.
    Each of "reference" and "tolerance" is "required", "optional" or "unused".
    """
    if test.type in NO_LIMIT_TEST_TYPES:
        return {"uses_limits": False, "reference": "unused", "tolerance": "unused"}
    if test.is_boolean():
        return {"uses_limits": True, "reference": "required", "tolerance": "optional"}
    if test.is_string_type():
        return {"uses_limits": True, "reference": "unused", "tolerance": "required"}
    return {"uses_limits": True, "reference": "required", "tolerance": "required"}


def new_tolerance_types(test):
    """Tolerance types the builder's New Tolerance dialog offers for this test.

    Matches how UnitTestInfoForm filters a test's tolerances. Never Boolean: Yes/No
    tolerances are fixed records the Tolerance admin doesn't let you create, so a
    Boolean test gets an empty list (and no New Tolerance button).
    """
    if test.is_boolean():
        return []
    if test.is_string_type():
        return [models.MULTIPLE_CHOICE]
    if test.type == models.WRAPAROUND:
        return [models.ABSOLUTE]
    return [models.ABSOLUTE, models.PERCENT]


def can_view_machine_values(user):
    """Machine mode shows UnitTestInfo values, so it needs view (or change) access to them."""
    return user.has_perm("qa.view_unittestinfo") or user.has_perm("qa.change_unittestinfo")


def testlist_machine_values(request):
    """JSON for the builder's machine mode: one unit's reference and tolerance per test.

    GET ``unit=<id>``, ``tests=<comma separated test ids>`` and optionally
    ``test_list=<id>`` (for the unit's assignment details). Tests the unit has no
    UnitTestInfo for come back as ``null``. ``limits`` says, per test, whether its
    type uses a reference and tolerance at all (see machine_limit_usage). Read-only;
    changes are made in the builder's Reference and Tolerance dialog
    (testlist_machine_ref_tol) or on the UnitTestInfo admin page.
    """
    if not can_view_machine_values(request.user):
        return HttpResponseForbidden(_("You don't have permission to view references and tolerances."))

    try:
        unit = Unit.objects.get(pk=int(request.GET.get("unit", "")))
    except (ValueError, TypeError, Unit.DoesNotExist):
        raise Http404(_("Unit not found"))

    test_ids = []
    for raw in (request.GET.get("tests") or "").split(","):
        raw = raw.strip()
        if raw.isdigit() and int(raw) not in test_ids:
            test_ids.append(int(raw))

    tests = {str(tid): None for tid in test_ids}
    utis = models.UnitTestInfo.objects.filter(unit=unit, test_id__in=test_ids).select_related(
        "test", "reference", "tolerance",
    )
    for uti in utis:
        entry = machine_values_display(uti)
        entry["uti_id"] = uti.pk
        entry["uti_url"] = reverse("admin:qa_unittestinfo_change", args=[uti.pk])
        tests[str(uti.test_id)] = entry
    limits = {
        str(test.pk): machine_limit_usage(test)
        for test in models.Test.objects.filter(pk__in=test_ids).only("id", "type")
    }

    unit_info = {
        "id": unit.pk,
        "name": unit.name,
        "frequency": None,
        "assigned_to": None,
        "active": None,
        "utc_url": None,
        "via": None,
    }
    test_list_id = request.GET.get("test_list", "")
    if test_list_id.isdigit():
        test_list = models.TestList.objects.filter(pk=int(test_list_id)).first()
        direct, through = get_testlist_scope_units(test_list)
        for entry in direct + through:
            if entry["unit_id"] == unit.pk:
                for key in ("frequency", "assigned_to", "active", "utc_url", "via"):
                    unit_info[key] = entry[key]
                break

    return JsonResponse({"unit": unit_info, "tests": tests, "limits": limits})


class MachineRefTolForm(UnitTestInfoForm):
    """UnitTestInfoForm for the builder's Reference and Tolerance dialog.

    Same fields, tolerance filtering, validation and Reference creation as the
    UnitTestInfo admin page; only the ids, widgets and labels differ. The
    reference starts filled in with the current value, and an unchanged value
    keeps the current Reference instead of saving a copy of it.
    """

    class Meta:
        model = models.UnitTestInfo
        # unit, test, active and assigned_to are never changed from the dialog
        fields = ["tolerance"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "tl-reftol-%s")
        super().__init__(*args, **kwargs)
        instance = self.instance
        ref = instance.reference if instance.pk else None
        if ref is not None and ref.value is not None and "reference_value" not in self.initial:
            if instance.test.is_boolean():
                self.initial["reference_value"] = 1 if int(ref.value) == 1 else 0
            elif not instance.test.is_string_type():
                value = repr(float(ref.value))
                self.initial["reference_value"] = value[:-2] if value.endswith(".0") else value
        self.fields["reference_value"].label = _("Reference")
        # the dialog shows the current value, so "leave blank to keep" doesn't apply
        self.fields["reference_value"].help_text = ""
        self.fields["tolerance"].label = _("Tolerance")
        self.fields["tolerance"].empty_label = _("No tolerance")
        if not isinstance(self.fields["tolerance"].widget, forms.HiddenInput):
            self.fields["tolerance"].widget = PlainToleranceSelect()
            # a lazy ModelChoiceIterator, as ModelChoiceField itself gives its widget
            self.fields["tolerance"].widget.choices = self.fields["tolerance"].choices
        self.fields["tolerance"].label_from_instance = lambda tol: tol.plain_display()
        self.fields["comment"].label = _("Comment")
        self.fields["comment"].help_text = _("Why are you changing this? Saved with the history.")
        self.fields["comment"].widget.attrs.update({"rows": 3, "class": "tl-modal-textarea"})
        for name in ("reference_value", "tolerance"):
            widget = self.fields[name].widget
            if not isinstance(widget, forms.HiddenInput):
                widget.attrs["class"] = "tl-modal-input"
        # An unchanged value keeps the current Reference and emptying the field
        # clears it: UnitTestInfoForm handles both (see _reference_value_changed).


def testlist_machine_ref_tol(request, uti_id):
    """The builder's Reference and Tolerance dialog for one UnitTestInfo (unit + test).

    GET returns the dialog. POST validates with MachineRefTolForm (the UnitTestInfo
    admin form's rules), saves straight away and records the change in the
    UnitTestInfo history like the admin page does. There's no review step, as on
    the admin page. Success returns JSON with the new display values for machine
    mode; validation errors return the dialog again with status 422.
    """
    if not request.user.has_perm("qa.change_unittestinfo"):
        return HttpResponseForbidden(
            _("You don't have permission to change references and tolerances. Nothing was changed.")
        )

    uti = get_object_or_404(
        models.UnitTestInfo.objects.select_related("unit", "test", "reference", "tolerance"), pk=uti_id,
    )
    test_name = uti.test.get_display_name()
    # before the form runs: validating a POST puts the posted tolerance on `uti`
    current = machine_values_display(uti)
    status = 200
    if request.method == "POST":
        old_reference = uti.reference
        old_tolerance = uti.tolerance
        form = MachineRefTolForm(request.POST, instance=uti, initial={"modified_by": request.user})
        if form.is_valid():
            saved = form.save()
            record_unit_test_info_change(
                saved, old_reference, old_tolerance, form.cleaned_data.get("comment"), request.user,
                form.changed_data,
            )
            fresh = models.UnitTestInfo.objects.select_related("unit", "test", "reference", "tolerance").get(
                pk=uti.pk,
            )
            data = machine_values_display(fresh)
            data.update({
                "ok": True,
                "uti_id": fresh.pk,
                # the Set References & Tolerances list's two cells, so it can redraw the
                # row without reloading (which a filter or sort might no longer show)
                "reference_cell_html": str(unit_test_info_reference_html(fresh)),
                "tolerance_cell_html": str(unit_test_info_tolerance_html(fresh)),
                "uti_url": reverse("admin:qa_unittestinfo_change", args=[fresh.pk]),
                "test_id": fresh.test_id,
                "unit_id": fresh.unit_id,
                "message": _("Saved for %(test)s on %(unit)s.") % {"test": test_name, "unit": uti.unit.name},
            })
            return JsonResponse(data)
        status = 422
    else:
        form = MachineRefTolForm(instance=uti, initial={"modified_by": request.user})

    last_change = (
        models.UnitTestInfoChange.objects.filter(unit_test_info=uti).select_related("changed_by")
        .order_by("-changed").first()
    )
    return render(request, "admin/qa/testlist/partials/_machine_ref_tol_modal.html", {
        "form": form,
        "uti": uti,
        "test_name": test_name,
        "current": [v for v in (current["reference"], current["tolerance"]) if v],
        "last_change": last_change,
        "reference_hidden": isinstance(form.fields["reference_value"].widget, forms.HiddenInput),
        "can_add_tolerance": request.user.has_perm("qa.add_tolerance") and bool(new_tolerance_types(uti.test)),
    }, status=status)


def testlist_assign_machine(request):
    """The builder's "Assign to Machine" dialog: assign this test list to a unit.

    GET ``test_list=<id>`` returns the dialog. POST validates it with
    ``TestListAssignMachineForm`` (the UnitTestCollection admin's rules, with the
    test list fixed) and creates the UnitTestCollection straight away, whether or
    not the test list itself is saved afterwards. Success returns JSON for the
    Editing dropdown; validation errors return the dialog again with status 422.
    """
    if not request.user.has_perm("qa.add_unittestcollection"):
        return HttpResponseForbidden(_("You don't have permission to assign test lists to units. Nothing was saved."))

    raw_id = request.POST.get("test_list") if request.method == "POST" else request.GET.get("test_list")
    try:
        test_list = models.TestList.objects.get(pk=int(raw_id or ""))
    except (ValueError, TypeError, models.TestList.DoesNotExist):
        raise Http404(_("Test list not found"))

    tl_ct = ContentType.objects.get_for_model(models.TestList)
    status = 200
    if request.method == "POST":
        data = request.POST.copy()
        # The dialog never posts these: the assignment is always for this test list.
        data["content_type"] = tl_ct.pk
        data["object_id"] = test_list.pk
        form = TestListAssignMachineForm(data)
        if form.is_valid():
            utc = form.save()
            LogEntry.objects.log_action(
                user_id=request.user.pk,
                content_type_id=ContentType.objects.get_for_model(utc).pk,
                object_id=utc.pk,
                object_repr=str(utc),
                action_flag=ADDITION,
                change_message=[{"added": {}}],
            )
            direct, through = get_testlist_scope_units(test_list)
            entry = next((e for e in direct if e["unit_id"] == utc.unit_id), None)
            freq = utc.frequency.name if utc.frequency_id else _("Ad Hoc")
            assignment = _("%(unit)s (%(frequency)s)") % {"unit": utc.unit.name, "frequency": freq}
            return JsonResponse({
                "ok": True,
                "unit_id": utc.unit_id,
                "unit_name": utc.unit.name,
                # the Editing dropdown's option text (lists every frequency for the unit)
                "label": entry["label"] if entry else assignment,
                "utc_url": reverse("admin:qa_unittestcollection_change", args=[utc.pk]),
                "message": _("Assigned to %(label)s.") % {"label": assignment},
                # the dropdown only lists machines for users who can open machine mode
                "show_in_scope": can_view_machine_values(request.user),
                # the builder's Preview tab (same assignment get_testlist_preview_units picks)
                "preview_url": reverse(
                    "perform_qa_preview", kwargs={"pk": entry["utc_id"] if entry else utc.pk},
                ),
            })
        status = 422
    else:
        form = TestListAssignMachineForm(initial={"active": True})

    return render(request, "admin/qa/testlist/partials/_assign_machine_modal.html", {
        "form": form,
        "test_list": test_list,
    }, status=status)


# What the Save As dialog accepts for a new test list's slug.
TESTLIST_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def _next_free_testlist_slug(slug):
    """Return `slug` with -2, -3… appended: the first variant no test list uses yet."""
    max_len = models.TestList._meta.get_field("slug").max_length
    taken = set(models.TestList.objects.filter(slug__startswith=slug[:max_len - 12]).values_list("slug", flat=True))
    n = 2
    while True:
        suffix = "-%d" % n
        candidate = slug[:max_len - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def testlist_slug_available(request):
    """Tell the Save As dialog whether a slug is free for a new test list.

    Returns JSON ``{"available": bool, "valid": bool}``. When the slug is valid but
    already taken, ``suggestion`` holds the first free -2, -3… variant. Staff-only
    (the URL is wrapped in admin_view); it only reads slugs, never saves anything.
    """
    slug = (request.GET.get("slug") or "").strip()
    max_len = models.TestList._meta.get_field("slug").max_length
    if not TESTLIST_SLUG_RE.match(slug) or len(slug) > max_len:
        return JsonResponse({"available": False, "valid": False})
    if not models.TestList.objects.filter(slug=slug).exists():
        return JsonResponse({"available": True, "valid": True})
    return JsonResponse({"available": False, "valid": True, "suggestion": _next_free_testlist_slug(slug)})


class TestListAttachmentInline(get_attachment_inline("testlist")):
    # one spare blank row; admin's "Add another" adds more when it's used
    extra = 1


class TestListAdmin(QCAdminDesignMixin, SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

    change_form_template = "admin/qa/testlist/change_form.html"

    def view_on_site(self, obj):
        if obj and obj.pk:
            utc = obj.utcs.first()
            if utc:
                return utc.get_absolute_url()
            return reverse("all_lists")
        return None

    prepopulated_fields = {
        'slug': ('name',)
    }
    search_fields = ("name", "description", "slug", "sublist__parent__name", "sublist__child__name")
    readonly_fields = ("id",)

    filter_horizontal = ("tests",)

    list_display = (
        "col_id",
        "col_name",
        "col_frequency",
        "col_units",
        "col_modified",
        "col_edit",
    )
    list_display_links = None
    list_filter = [
        ActiveTestListFilter,
        SiteTestListFilter,
        UnitTestListFilter,
        FrequencyTestListFilter,
        CategoryTestListFilter,
    ]

    form = TestListAdminForm
    inlines = [TestListMembershipInline, SublistInline, TestListAttachmentInline]
    # The builder has its own "Save As…" dialog in the title row, so Django's
    # "Save as new" submit button is turned off. A POST with "_saveasnew" still
    # creates a copy (Django handles that regardless of this flag).
    save_as = False

    fieldsets = [
        (
            "Test List",
            {
                'fields': ['id', 'name', 'slug', 'description', 'javascript', 'warning_message']
            },
        ),
        (
            "Sublist Memberships",
            {
                'fields': [],
            },
        ),
    ]

    class Media:
        css = {
            "all": (
                "fontawsome/css/font-awesome.min.css",
            ),
        }
        # The Test List Builder styling and JS is inlined via testlist_assets.html
        # so it loads under DEBUG=False without a collectstatic step.
        js = (
            "admin/js/jquery.init.js",
            'jquery/js/jquery.min.js',
            "js/jquery-ui.init.js",
            "js/jquery-ui.min.js",
            "htmx/js/htmx.min.js",
        )

    @staticmethod
    def _is_save_as_new(request):
        return request.method == "POST" and "_saveasnew" in request.POST

    @staticmethod
    def _save_as_source(request):
        """The test list a "Save As…" copy was made from (or None)."""
        try:
            return models.TestList.objects.get(pk=int(request.POST.get("_saveas_source", "")))
        except (ValueError, TypeError, models.TestList.DoesNotExist):
            return None

    def get_inlines(self, request, obj):
        inlines = super().get_inlines(request, obj)
        if self._is_save_as_new(request):
            # Save As copies the tests and sublists only. Attachments stay with
            # the original, and leaving the inline out also stops the posted
            # attachment rows (which point at the original's files) from failing
            # validation.
            inlines = [inline for inline in inlines if not issubclass(inline, TestListAttachmentInline)]
        return inlines

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        if self._is_save_as_new(request):
            # every row of a Save As copy is new, so a removed row is simply left out
            return form
        # A saved test or sublist row is only deleted when the user may delete
        # rows of that inline (the same check Django uses for the formset's
        # can_delete); the form's checks must count the rows that will be kept.
        prefixes = {TestListMembershipInline: "testlistmembership_set", SublistInline: "children"}
        rows_can_delete = {}
        for inline in self.get_inline_instances(request, obj):
            prefix = prefixes.get(type(inline))
            if prefix:
                rows_can_delete[prefix] = inline.can_delete and inline.has_delete_permission(request, obj)
        return type(form.__name__, (form,), {"rows_can_delete": rows_can_delete})

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        save_as_retry = self._is_save_as_new(request)
        if save_as_retry:
            # A Save As that failed validation: Django re-renders it as a change
            # page with no object. It's really a new test list, so show it as the
            # add page, and keep posting "_saveasnew" so saving again creates the
            # copy rather than changing the original.
            add, change = True, False
            context["title"] = _("Add %s") % self.opts.verbose_name
            source = self._save_as_source(request)
            context["tl_saveas_source_pk"] = source.pk if source else ""
        context["tl_saveas_retry"] = save_as_retry
        context["tl_can_assign_machine"] = request.user.has_perm("qa.add_unittestcollection")
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def response_add(self, request, obj, post_url_continue=None):
        if not self._is_save_as_new(request) or IS_POPUP_VAR in request.POST:
            return super().response_add(request, obj, post_url_continue)

        source = self._save_as_source(request)
        if source:
            msg = format_html(_("Created “{new}” as a copy of “{source}”."), new=obj.name, source=source.name)
        else:
            msg = format_html(_("Created “{new}”."), new=obj.name)
        self.message_user(request, msg, messages.SUCCESS)

        if not self.has_view_or_change_permission(request, obj):
            return self.response_post_save_add(request, obj)
        url = reverse("admin:qa_testlist_change", args=(obj.pk,), current_app=self.admin_site.name)
        url = add_preserved_filters({"preserved_filters": self.get_preserved_filters(request), "opts": self.opts}, url)
        return HttpResponseRedirect(url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'slug-available/',
                self.admin_site.admin_view(testlist_slug_available),
                name='qa_testlist_slug_available',
            ),
            path(
                'export-testpack/',
                self.admin_site.admin_view(admin_views.ExportTestPack.as_view()),
                name='qa_export_testpack'
            ),
            path(
                'import-testpack/',
                self.admin_site.admin_view(admin_views.ImportTestPack.as_view()),
                name='qa_import_testpack'
            ),
            path(
                'description-preview/',
                self.admin_site.admin_view(testlist_description_preview),
                name='qa_testlist_desc_preview',
            ),
            path(
                'search-tests/',
                self.admin_site.admin_view(testlist_search_tests),
                name='qa_testlist_search_tests',
            ),
            path(
                'search-sublists/',
                self.admin_site.admin_view(testlist_search_sublists),
                name='qa_testlist_search_sublists',
            ),
            path(
                'add-test-row/',
                self.admin_site.admin_view(testlist_add_test_row),
                name='qa_testlist_add_test_row',
            ),
            path(
                'add-sublist-card/',
                self.admin_site.admin_view(testlist_add_sublist_card),
                name='qa_testlist_add_sublist_card',
            ),
            path(
                'duplicate-test/',
                self.admin_site.admin_view(testlist_duplicate_test),
                name='qa_testlist_duplicate_test',
            ),
            path(
                'machine-values/',
                self.admin_site.admin_view(testlist_machine_values),
                name='qa_testlist_machine_values',
            ),
            path(
                'machine-ref-tol/<int:uti_id>/',
                self.admin_site.admin_view(testlist_machine_ref_tol),
                name='qa_testlist_machine_ref_tol',
            ),
            path(
                'new-tolerance/',
                self.admin_site.admin_view(testlist_new_tolerance),
                name='qa_testlist_new_tolerance',
            ),
            path(
                'assign-machine/',
                self.admin_site.admin_view(testlist_assign_machine),
                name='qa_testlist_assign_machine',
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['export_testpack_url'] = reverse('admin:qa_export_testpack')
        extra_context['import_testpack_url'] = reverse('admin:qa_import_testpack')
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Units for the builder's "Editing" dropdown (base list vs. one machine)
        extra_context = extra_context or {}
        test_list = self.get_object(request, options.unquote(object_id))
        direct, through = get_testlist_scope_units(test_list)
        extra_context['tl_scope_direct_units'] = direct
        extra_context['tl_scope_through_units'] = through
        extra_context['tl_can_view_machine_values'] = can_view_machine_values(request.user)
        # Machine mode: set a unit's reference and tolerance in a dialog (testlist_machine_ref_tol)
        extra_context['tl_can_change_machine_values'] = request.user.has_perm('qa.change_unittestinfo')
        # Preview tab: the real Perform QC page (read-only) for directly assigned units
        extra_context['tl_can_preview_perform'] = request.user.has_perm('qa.change_testlist')
        extra_context['tl_preview_units'] = get_testlist_preview_units(direct, through)
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        # "Save and continue editing" redirects to request.path, which drops the
        # builder's ?unit=<id>; put it back so the page reopens on the same machine.
        response = super().response_change(request, obj)
        unit = request.POST.get('tl_scope_unit', '')
        if '_continue' in request.POST and unit.isdigit() and response.status_code == 302:
            location = response['Location']
            response['Location'] = '%s%sunit=%s' % (location, '&' if '?' in location else '?', unit)
        return response

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        # Prefetch the unit assignments (generic relation) in a single query so
        # the Frequency and Units columns don't issue per-row queries.
        qs = qs.prefetch_related(
            Prefetch(
                "utcs",
                queryset=models.UnitTestCollection.objects.select_related("frequency", "unit"),
            ),
        )
        return qs

    @admin.display(description=_l("ID"), ordering="id")
    def col_id(self, obj):
        return format_html('<span class="tl-mono tl-cell-id">#{}</span>', obj.pk)

    @admin.display(description=_l("Name"), ordering="name")
    def col_name(self, obj):
        url = reverse("admin:qa_testlist_change", args=(obj.pk,))
        return format_html(
            '<a class="tl-cell-name" href="{}">'
            '<span class="tl-name">{}</span>'
            '<span class="tl-slug tl-mono">{}</span>'
            '</a>',
            url, obj.name, obj.slug,
        )

    @admin.display(description=_l("Frequency"))
    def col_frequency(self, obj):
        names = []
        seen = set()
        for utc in obj.utcs.all():
            label = utc.frequency.name if utc.frequency else _("Ad Hoc")
            if label not in seen:
                seen.add(label)
                names.append(label)
        if not names:
            return ""
        return format_html_join("", '<span class="tl-freq-tag">{}</span>', ((n,) for n in names))

    @admin.display(description=_l("Units"))
    def col_units(self, obj):
        unit_names = []
        seen = set()
        for utc in obj.utcs.all():
            if utc.unit_id not in seen:
                seen.add(utc.unit_id)
                unit_names.append(utc.unit.name)
        if unit_names:
            label = _("Assigned to: %(units)s") % {"units": ", ".join(unit_names)}
        else:
            label = _("Not assigned to any unit")
        # the tooltip names the units; screen readers read the same text after the count
        return format_html(
            '<span class="tl-cell-units" title="{}">'
            '<i class="fa fa-cube" aria-hidden="true"></i> {}'
            '<span class="tl-visually-hidden"> ({})</span></span>',
            label, len(unit_names), label,
        )

    @admin.display(description=_l("Last Modified"), ordering="modified")
    def col_modified(self, obj):
        when = date_formatter(obj.modified, "d M Y")
        who = obj.modified_by.username if obj.modified_by_id else ""
        return format_html(
            '<span class="tl-cell-modified">'
            '<span class="tl-mod-date">{}</span>'
            '<span class="tl-mod-by">{}</span>'
            '</span>',
            when, who,
        )

    @admin.display(description="")
    def col_edit(self, obj):
        url = reverse("admin:qa_testlist_change", args=(obj.pk,))
        label = _("Edit %(name)s") % {"name": obj.name}
        return format_html(
            '<a class="tl-editlink" href="{}" title="{}" aria-label="{}">'
            '<i class="fa fa-pencil" aria-hidden="true"></i></a>',
            url, label, label,
        )


# The Test change form's Type select, grouped (same values as models.TEST_TYPE_CHOICES)
TEST_TYPE_GROUPS = (
    (_l("Numbers"), (models.SIMPLE, models.WRAPAROUND, models.CONSTANT, models.COMPOSITE)),
    (_l("Answers & text"), (models.BOOLEAN, models.MULTIPLE_CHOICE, models.STRING, models.STRING_COMPOSITE)),
    (_l("Dates"), (models.DATE, models.DATETIME)),
    (_l("Files"), (models.UPLOAD,)),
)

# One line under the Type select saying what the chosen type is for
TEST_TYPE_HELP = {
    models.SIMPLE: _l("A number typed in by the person performing QC."),
    models.WRAPAROUND: _l(
        "A number on a scale that wraps around, such as a gantry or collimator angle where 359 is next to 0."
    ),
    models.CONSTANT: _l("A fixed number shown on the form for use in calculations. Nobody types it in."),
    models.COMPOSITE: _l("A number calculated from other tests by a Python snippet."),
    models.BOOLEAN: _l("A Yes / No answer."),
    models.MULTIPLE_CHOICE: _l("One answer picked from a list of choices."),
    models.STRING: _l("Free text typed in by the person performing QC."),
    models.STRING_COMPOSITE: _l("Text or JSON calculated from other tests by a Python snippet."),
    models.DATE: _l("A date picked by the person performing QC."),
    models.DATETIME: _l("A date and time picked by the person performing QC."),
    models.UPLOAD: _l("A file uploaded by the person performing QC, which a Python snippet can process."),
}

# The Number format picker's presets: (format string, label). Anything else is "Custom".
TEST_FORMAT_PRESETS = (
    ("", _l("Default")),
    ("%.0f", _l("Fixed, 0 decimals (%.0f)")),
    ("%.1f", _l("Fixed, 1 decimal (%.1f)")),
    ("%.2f", _l("Fixed, 2 decimals (%.2f)")),
    ("%.3f", _l("Fixed, 3 decimals (%.3f)")),
    ("%.4f", _l("Fixed, 4 decimals (%.4f)")),
    ("%.5f", _l("Fixed, 5 decimals (%.5f)")),
    ("%.6f", _l("Fixed, 6 decimals (%.6f)")),
    ("%.0E", _l("Scientific, 1 significant figure (%.0E)")),
    ("%.1E", _l("Scientific, 2 significant figures (%.1E)")),
    ("%.2E", _l("Scientific, 3 significant figures (%.2E)")),
    ("%.3E", _l("Scientific, 4 significant figures (%.3E)")),
    ("%.4E", _l("Scientific, 5 significant figures (%.4E)")),
    ("%.5E", _l("Scientific, 6 significant figures (%.5E)")),
    ("%.0G", _l("General, up to 1 significant figure (%.0G)")),
    ("%.1G", _l("General, up to 2 significant figures (%.1G)")),
    ("%.2G", _l("General, up to 3 significant figures (%.2G)")),
    ("%.3G", _l("General, up to 4 significant figures (%.3G)")),
    ("%.4G", _l("General, up to 5 significant figures (%.4G)")),
    ("%.5G", _l("General, up to 6 significant figures (%.5G)")),
)

# Sample values the Number format preview shows formatted
TEST_FORMAT_SAMPLES = (123.4567, 0.00123456)

# Test checkboxes drawn as on/off switches on the change form
TEST_SWITCH_FIELDS = ("chart_visibility", "skip_without_comment", "require_comment", "hidden", "display_image")

# Settings that only apply to some test types, with the change form's label for each.
# The form hides them for other types, so a value left from an earlier type is cleared
# on save (TestForm.clean) rather than kept out of sight: the model refuses Choices, a
# Constant value or Wrap values on the wrong type, and a leftover Flag setting would
# flag the test list whenever a result happened to be 1 or 0 (signals.check_tli_flag
# doesn't look at the test type).
TEST_TYPE_ONLY_FIELDS = (
    ("choices", (models.MULTIPLE_CHOICE,), _l("Choices")),
    ("constant_value", (models.CONSTANT,), _l("Constant value")),
    ("wrap_low", (models.WRAPAROUND,), _l("Wrap low")),
    ("wrap_high", (models.WRAPAROUND,), _l("Wrap high")),
    ("flag_when", (models.BOOLEAN,), _l("Flag the test list")),
)


def _apply_test_format(value, fmt):
    """`value` formatted with `fmt` by the same steps as format_qc_value (old style,
    then new style only after a TypeError that isn't "a number is required"), or None
    when those steps fail. format_qc_value itself never fails: it falls back to the
    default format, which would hide a format that can't be used."""
    try:
        return fmt % value
    except TypeError as e:
        if "number is required" in str(e):
            return None
        try:
            return fmt.format(value)
        except Exception:  # noqa: BLE001 - any failure means the default format is used
            return None
    except Exception:  # noqa: BLE001
        return None


def testadmin_format_preview(request):
    """The Test change form's Number format preview: the sample values as results
    would show them with ?formatting=. Wired up via htmx; staff-only (wrapped in
    admin_view). Points out a format that can't be applied (results fall back to the
    default format) and one that leaves the number out (results show only its text)."""
    fmt = request.GET.get("formatting", "")
    samples = [(value, format_qc_value(value, fmt)) for value in TEST_FORMAT_SAMPLES]
    problem = ""
    if fmt:
        applied = [_apply_test_format(value, fmt) for value in TEST_FORMAT_SAMPLES]
        if any(a is None for a in applied):
            problem = "fallback"
        elif all(a == fmt for a in applied):
            problem = "no_number"
    return render(request, "admin/qa/test/partials/_format_preview.html", {
        "samples": samples,
        "problem": problem,
        "formatting": fmt,
    })


class TestForm(forms.ModelForm):

    class Meta:
        model = models.Test
        fields = "__all__"
        # The model field's verbose_name is "Description" (a copy/paste slip), which put two
        # "Description" labels on this form. Label it here until the model metadata migration lands.
        labels = {
            'choices': _l("Choices"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "type" in self.fields:
            labels = dict(models.TEST_TYPE_CHOICES)
            self.fields["type"].choices = [
                (group, [(t, labels[t]) for t in types]) for group, types in TEST_TYPE_GROUPS
            ]
        for name in TEST_SWITCH_FIELDS:
            if name in self.fields:
                self.fields[name].widget.attrs.update({"role": "switch", "class": "tst-switch-input"})

    def clean(self):
        """if test already has some history don't allow for the test type to be changed"""

        cleaned_data = super().clean()

        test_type = cleaned_data.get("type")

        # Clear settings left from another type (see TEST_TYPE_ONLY_FIELDS), so a value
        # hidden on the form can't block the save or act on results. Their own input
        # errors (say, text in a hidden Wrap low) don't count either.
        self.cleared_fields = []
        if test_type:
            for name, types, label in TEST_TYPE_ONLY_FIELDS:
                if test_type in types or name not in self.fields:
                    continue
                had_error = self._errors.pop(name, None) is not None
                if had_error or cleaned_data.get(name) not in (None, ""):
                    self.cleared_fields.append(name)
                cleaned_data[name] = None

        user_changing_type = self.instance.type != test_type
        # A new (unsaved) test can't have been performed yet.
        has_history = (
            self.instance.pk is not None
            and models.TestInstance.objects.filter(unit_test_info__test=self.instance).exists()
        )
        if user_changing_type and has_history and not models.Test.allow_type_transition(self.instance.type, test_type):
            msg = _(
                "You can't change the test type from %(old_test_type)s to %(new_test_type)s for a test that "
                "has already been performed. Revert to '%(old_test_type)s' before saving or create a new test with "
                "'Save as New'."
            )
            old_ttype_index = [ttype for ttype, label in models.TEST_TYPE_CHOICES].index(self.instance.type)
            old_ttype_label = models.TEST_TYPE_CHOICES[old_ttype_index][1]
            new_ttype_index = [ttype for ttype, label in models.TEST_TYPE_CHOICES].index(test_type)
            new_ttype_label = models.TEST_TYPE_CHOICES[new_ttype_index][1]
            self.add_error(
                'type',
                forms.ValidationError(msg % {
                    'old_test_type': old_ttype_label,
                    'new_test_type': new_ttype_label,
                })
            )

        if test_type not in models.NUMERICAL_TYPES:
            cleaned_data['formatting'] = ''
        else:
            fmt = cleaned_data.get('formatting')
            if fmt:
                try:
                    format_qc_value(123.4, fmt)
                except:  # noqa: E722
                    self.add_error("formatting", forms.ValidationError(_("Invalid numerical format")))

        editing_hidden = self.instance.pk is not None and cleaned_data.get("hidden")
        if editing_hidden:
            existing_ref_tols = models.UnitTestInfo.objects.filter(test=self.instance).exclude(
                reference=None,
                tolerance=None,
            )
            if existing_ref_tols.exists():
                links = []
                for uti, name in existing_ref_tols.order_by("unit__name").values_list("pk", "unit__name"):
                    url = reverse(
                        "admin:qa_unittestinfo_change", args=(uti,)
                    )
                    links.append((url, name))

                title = _("Click to edit the reference and tolerance (opens in new window)")
                html_links = format_html_join(
                    ", ", '<a href="{}" title="{}" target="_blank">{}</a>', ((u, title, l) for (u, l) in links)
                )
                msg = _(
                    "Hidden tests can not have references and tolerances set. Please remove the references "
                    "and tolerances for this test on the following units before making it hidden: "
                ) + html_links
                self.add_error("hidden", mark_safe(msg))

        # Boolean results are 0 / 1, so a Boolean test can't keep a reference
        # like 5.0 on any unit. Report it here rather than letting the on_test_save
        # signal refuse the save with a server error.
        if test_type == models.BOOLEAN and self.instance.pk is not None:
            bad_units = list(
                models.UnitTestInfo.objects.filter(
                    test=self.instance,
                    reference__isnull=False,
                ).exclude(
                    reference__value__in=(0., 1.),
                ).order_by("unit__name").values_list("unit__name", flat=True)
            )
            if bad_units:
                self.add_error("type", forms.ValidationError(
                    _(
                        "This test can't be Boolean while it has a reference other than Yes / No on these "
                        "units: %(units)s. Change those references first, then change the test type. "
                        "Nothing was saved."
                    ) % {"units": ", ".join(bad_units)}
                ))
        return cleaned_data


class TestListMembershipFilter(admin.SimpleListFilter):
    NOMEMBERSHIPS = 'nomemberships'
    HASMEMBERSHIPS = 'hasmemberships'

    title = _l('Test List Membership')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'tlmembership'

    def lookups(self, request, model_admin):
        return (
            (self.NOMEMBERSHIPS, _l('No TestList Membership')),
            (self.HASMEMBERSHIPS, _l('At Least One TestList Membership')),
        )

    def queryset(self, request, queryset):
        qs = queryset.annotate(tlcount=Count("testlistmembership"))
        if self.value() == self.NOMEMBERSHIPS:
            return qs.filter(tlcount=0)
        elif self.value() == self.HASMEMBERSHIPS:
            return qs.filter(tlcount__gt=0)
        return qs


class TestAdmin(QCAdminDesignMixin, SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

    inlines = [get_attachment_inline("test")]
    list_display = ["name", "id", "slug", "category", "type", 'obj_created', 'obj_modified']
    list_filter = ["category", "type", TestListMembershipFilter, "testlistmembership__test_list"]
    search_fields = ["name", "slug", "category__name"]
    readonly_fields = ("id",)
    save_as = True

    form = TestForm
    fieldsets = [
        (
            "Test ID",
            {
                'fields': ['id']
            },
        ),
        (
            "Test options",
            {
                'fields': ['name', 'display_name', 'slug', 'description', 'procedure', 'category'],
            },
        ),
        (
            "Test type options",
            {
                'fields': [
                    'type',
                    'flag_when',
                    'choices',
                    'constant_value',
                    'wrap_low',
                    'wrap_high',
                    'calculation_procedure',
                    'display_image',
                    'hidden',
                    'chart_visibility',
                    'skip_without_comment',
                    'require_comment',
                    'formatting',
                ],
            },
        ),
        (
            "Autoreview Rules",
            {
                'fields': ['autoreviewruleset'],
            },
        ),
        (
            "Memberships & Assignments",
            {
                'fields': [],
            },
        ),
    ]

    class Media:
        # The change form's styling and JS are inlined via admin/qa/test/test_assets.html
        # (like the Test List builder), so they load under DEBUG=False without a
        # collectstatic step. ace is the calculation procedure's code editor; the page
        # falls back to a plain textarea if it isn't loaded.
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "ace/ace.js",
            "htmx/js/htmx.min.js",
        )
        css = {
            'all': (
                "qatrack_core/css/admin.css",
                "fontawsome/css/font-awesome.min.css",
            ),
        }

    def get_urls(self):
        custom_urls = [
            path(
                'format-preview/',
                self.admin_site.admin_view(testadmin_format_preview),
                name='qa_test_format_preview',
            ),
        ]
        return custom_urls + super().get_urls()

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        """Context for the card layout in admin/qa/test/change_form.html."""
        context.update({
            "tst_type_help": {k: str(v) for k, v in TEST_TYPE_HELP.items()},
            "tst_format_presets": TEST_FORMAT_PRESETS,
            "tst_used_lists": [],
            "tst_used_utis": [],
        })
        if obj is not None and obj.pk:
            context["tst_used_lists"] = list(obj.testlist_set.order_by("name"))
            context["tst_used_utis"] = list(
                obj.unittestinfo_set.select_related("unit", "reference", "tolerance").order_by("unit__name")
            )
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    @staticmethod
    def _cleared_labels(form):
        labels = {name: label for name, _types, label in TEST_TYPE_ONLY_FIELDS}
        return [str(labels[name]) for name in getattr(form, "cleared_fields", [])]

    def construct_change_message(self, request, form, formsets, add=False):
        """Also list the settings TestForm cleared for the new type: their posted values
        didn't change, so Django wouldn't name them in the history."""
        message = super().construct_change_message(request, form, formsets, add)
        cleared = [
            label for name, label in zip(getattr(form, "cleared_fields", []), self._cleared_labels(form))
            if name not in form.changed_data
        ]
        if cleared and not add:
            for entry in message:
                if "changed" in entry:
                    entry["changed"]["fields"].extend(cleared)
                    break
            else:
                message.insert(0, {"changed": {"fields": cleared}})
        return message

    def save_model(self, request, obj, form, change):
        cleared = self._cleared_labels(form)
        if cleared:
            messages.add_message(request, messages.INFO, _(
                "Cleared %(fields)s: these settings don't apply to %(test_type)s tests."
            ) % {"fields": ", ".join(cleared), "test_type": obj.get_type_display()})

        if 'calculation_procedure' in form.changed_data:
            cp = obj.calculation_procedure or ""
            if "pyplot" in cp or "pylab" in cp:
                warning = _(
                    "Warning: Instead of using pyplot or pylab, it is recommended that you use "
                    "the object oriented interface to matplotlib."
                )
                messages.add_message(request, messages.WARNING, warning)

        if obj.procedure:
            if not obj.procedure.startswith("http"):
                warning = _("Warning: test procedure links should usually begin with http:// or https://")
                messages.add_message(request, messages.WARNING, warning)

        super().save_model(request, obj, form, change)

    @admin.display(
        description=_l("Created"),
        ordering="created",
    )
    @mark_safe
    def obj_created(self, obj):
        link_title = _("Created by %(username)s") % {'username': obj.created_by}
        dt = date_formatter(timezone.localtime(obj.created), "DATETIME_FORMAT")
        return '<abbr title="%s">%s</abbr>' % (link_title, dt)

    @admin.display(
        description=_l("Modified"),
        ordering="modified",
    )
    @mark_safe
    def obj_modified(self, obj):
        link_title = _("Modified by %(username)s") % {'username': obj.modified_by}
        dt = date_formatter(timezone.localtime(obj.modified), "DATETIME_FORMAT")
        return '<abbr title="%s">%s</abbr>' % (link_title, dt)


@admin.display(
    description=_l("Unit"),
    ordering="unit__name",
)
def unit_name(obj):
    return obj.unit.name


@admin.display(
    description=_l("Site"),
    ordering="unit__site__name",
)
def site_name(obj):
    return obj.unit.site.name if obj.unit.site else _l("Other")


@admin.display(
    description=_l("Frequency"),
    ordering="frequency__name",
)
def freq_name(obj):
    return obj.frequency.name if obj.frequency else _l("Ad Hoc")


@admin.display(
    description=_l("Assigned To"),
    ordering="assigned_to__name",
    empty_value=_l("Not assigned"),
)
def assigned_to_name(obj):
    # assigned_to is nullable (SET_NULL when its group is deleted), so an
    # assignment may have no group; returning None shows the empty_value text
    return obj.assigned_to.name if obj.assigned_to_id else None


class SiteFilter(admin.SimpleListFilter):

    title = _l('Site')
    parameter_name = "sitefilter"

    def lookups(self, request, model_admin):
        return Site.objects.values_list('pk', 'name')

    def queryset(self, request, queryset):

        if self.value():
            return queryset.filter(unit__site=self.value())

        return queryset


class UnitFilter(admin.SimpleListFilter):

    title = _l('Unit')
    parameter_name = "unitfilter"

    def lookups(self, request, model_admin):
        return models.Unit.objects.values_list('pk', 'name')

    def queryset(self, request, queryset):

        if self.value():
            return queryset.filter(unit=self.value())

        return queryset


class FrequencyFilter(admin.SimpleListFilter):

    title = _l('Frequency')
    parameter_name = "freqfilter"

    def lookups(self, request, model_admin):
        return [("adhoc", _l("Ad Hoc"))] + list(models.Frequency.objects.values_list("pk", "name"))

    def queryset(self, request, queryset):

        v = self.value()
        if self.value():
            return queryset.filter(frequency=None if v == "adhoc" else v)

        return queryset


class AssignedToFilter(admin.SimpleListFilter):

    title = _l('Assigned To')
    parameter_name = "assignedtoname"

    def lookups(self, request, model_admin):
        return models.Group.objects.values_list('pk', 'name')

    def queryset(self, request, queryset):

        if self.value():
            return queryset.filter(assigned_to=self.value())

        return queryset


class ActiveFilter(admin.SimpleListFilter):

    title = _l('Active')
    parameter_name = "activefilter"

    def lookups(self, request, model_admin):
        return ((1, _('Active')), (0, _('Not active')))

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(active=self.value())

        return queryset


class UnitTestCollectionForm(forms.ModelForm):

    unit = forms.TypedChoiceField(label=_l("Unit"), coerce=int)

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields['unit'].choices = unit_site_unit_type_choices(include_empty=True)

        freq = self.fields['frequency']
        freq.queryset = freq.queryset.order_by("name")
        freq.empty_label = _("Ad Hoc (Unscheduled)")

    def _clean_readonly(self, f):
        data = self.cleaned_data.get(f, None)
        if f == "unit" and data:
            data = Unit.objects.get(pk=data)

        if self.instance.pk and f in self.changed_data:
            if f == "object_id":
                orig = str(self.instance.tests_object)
            else:
                orig = getattr(self.instance, f)
            err_msg = _(
                "To prevent data loss, you can not change the Unit, TestList or TestListCycle "
                "of a UnitTestCollection after it has been created. The original value was: %(object_id)s"
            ) % {
                'object_id': orig
            }
            self.add_error(f, err_msg)

        return data

    def clean_content_type(self):
        return self._clean_readonly("content_type")

    def clean_object_id(self):
        return self._clean_readonly("object_id")

    def clean_unit(self):
        if self.instance.pk:
            return self._clean_readonly("unit")

        unit = self.cleaned_data.get('unit')
        if unit:
            return Unit.objects.get(pk=unit)


def _active_unit_choices():
    """Active units for a select, in ``<optgroup>``s by site when any unit has a site."""
    units = list(Unit.objects.filter(active=True).select_related("site").order_by("site__name", settings.ORDER_UNITS_BY))
    if not any(u.site_id for u in units):
        return [("", "---------")] + [(u.pk, u.name) for u in units]
    groups = {}
    for u in units:
        groups.setdefault(u.site.name if u.site_id else _("Other"), []).append((u.pk, u.name))
    return [("", "---------")] + list(groups.items())


class TestListAssignMachineForm(UnitTestCollectionForm):
    """The test list builder's "Assign to Machine" dialog.

    The UnitTestCollection admin form's rules, limited to the fields the dialog
    shows. The view always sets content_type and object_id to the test list being
    edited; they stay in the form so the unique unit/frequency/test list check runs.
    """

    class Meta:
        model = models.UnitTestCollection
        fields = ("unit", "frequency", "assigned_to", "visible_to", "active", "content_type", "object_id")
        widgets = {"content_type": forms.HiddenInput, "object_id": forms.HiddenInput}
        error_messages = {
            NON_FIELD_ERRORS: {
                "unique_together": _l(
                    "This test list is already assigned to this unit at this frequency. "
                    "Choose a different unit or frequency."
                ),
            },
        }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "tl-assign-%s")  # don't clash with the change form's id_* inputs
        super().__init__(*args, **kwargs)
        for name in ("unit", "frequency", "assigned_to", "visible_to"):
            self.fields[name].widget.attrs["class"] = "tl-modal-input"
        self.fields["visible_to"].widget.attrs["size"] = 5
        self.fields["unit"].choices = _active_unit_choices()
        self.fields["frequency"].empty_label = _("Ad Hoc")
        self.fields["assigned_to"].queryset = self.fields["assigned_to"].queryset.order_by("name")
        self.fields["visible_to"].queryset = self.fields["visible_to"].queryset.order_by("name")


# The two kinds of tests collection a unit can be assigned (UnitTestCollection.content_type).
UTC_COLLECTION_MODELS = ("testlist", "testlistcycle")
UTC_SEARCH_LIMIT = 25


def _utc_collection_type(raw_id):
    """The ContentType with this (posted) id when it is Test List or Test List Cycle, else None."""
    try:
        return ContentType.objects.get(pk=int(raw_id), app_label="qa", model__in=UTC_COLLECTION_MODELS)
    except (ValueError, TypeError, ContentType.DoesNotExist):
        return None


def _utc_collection(raw_type_id, raw_object_id):
    """``(content type, test list or cycle)`` for posted ids; either may be None when not found."""
    ct = _utc_collection_type(raw_type_id)
    if ct is None:
        return None, None
    model = ct.model_class()
    try:
        return ct, model.objects.get(pk=int(raw_object_id))
    except (ValueError, TypeError, model.DoesNotExist):
        return ct, None


def _utc_type_label(ct):
    """"Test List" / "Test List Cycle" for a collection content type."""
    if ct is None:
        return ""
    return _("Test List Cycle") if ct.model == "testlistcycle" else _("Test List")


@admin.display(
    description=_l("Frequency"),
    ordering="frequency__name",
)
def utc_frequency_tag(obj):
    """The assignment list's Frequency column (freq_name) as a small tag."""
    css = "utc-tag" if obj.frequency_id else "utc-tag utc-tag-adhoc"
    return format_html('<span class="{}">{}</span>', css, freq_name(obj))


@admin.display(
    description=_l("Assigned To"),
    ordering="assigned_to__name",
)
def utc_assigned_to_tag(obj):
    """The assignment list's Assigned To column (assigned_to_name) as a small tag."""
    name = assigned_to_name(obj)
    if name is None:
        return format_html('<span class="utc-tag-none">{}</span>', assigned_to_name.empty_value_display)
    return format_html('<span class="utc-tag utc-tag-group"><i class="fa fa-users" aria-hidden="true"></i> {}</span>', name)


def _utc_search_results(ct, q):
    """The test lists or cycles of type ``ct`` matching ``q`` (by name or slug), for the picker."""
    model = ct.model_class()
    qs = model.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    if model is models.TestList:
        qs = qs.annotate(
            utc_n_tests=Count("testlistmembership", distinct=True),
            utc_n_sublists=Count("children", distinct=True),
        )
    else:
        qs = qs.annotate(utc_n_days=Count("testlistcyclemembership", distinct=True))
    return list(qs.order_by("name")[:UTC_SEARCH_LIMIT])


def _utc_preview_context(user, ct, obj):
    """Context for the assignment page's contents preview (partials/_preview.html).

    A test list lists its tests in Perform QC order (sublists included); a cycle
    lists its days with each day's test list.
    """
    ctx = {
        "utc_ct": ct,
        "utc_obj": obj,
        "utc_type_label": _utc_type_label(ct),
        "utc_is_cycle": bool(ct and ct.model == "testlistcycle"),
        "utc_open_url": None,
    }
    if obj is None:
        return ctx
    if isinstance(obj, models.TestList):
        if user.has_perm("qa.change_testlist") or user.has_perm("qa.view_testlist"):
            ctx["utc_open_url"] = reverse("admin:qa_testlist_change", args=[obj.pk])
        ctx["utc_tests"] = obj.ordered_tests()
        ctx["utc_sublists"] = [s.child for s in obj.get_children()]
    else:
        if user.has_perm("qa.change_testlistcycle") or user.has_perm("qa.view_testlistcycle"):
            ctx["utc_open_url"] = reverse("admin:qa_testlistcycle_change", args=[obj.pk])
        can_open_lists = user.has_perm("qa.change_testlist") or user.has_perm("qa.view_testlist")
        days = []
        memberships = list(obj.testlistcyclemembership_set.select_related("test_list").order_by("order"))
        # one query for every day's test count, counted as the cycle page counts them
        counted = _cycle_test_lists_with_counts(
            models.TestList.objects.filter(pk__in={m.test_list_id for m in memberships})
        )
        n_tests = {tl.pk: tl.qcy_own_tests + tl.qcy_sublist_tests for tl in counted}
        for day, membership in enumerate(memberships, start=1):
            tl = membership.test_list
            days.append({
                "day": day,
                "test_list": tl,
                "n_tests": n_tests.get(tl.pk, 0),
                "url": reverse("admin:qa_testlist_change", args=[tl.pk]) if can_open_lists else None,
            })
        ctx["utc_days"] = days
    return ctx


class UTCLockedSelect(forms.Select):
    """The unit select on a saved assignment's page: shown as read-only text.

    The real select is still drawn (so its value is posted and
    UnitTestCollectionForm's "can't change the unit" check still runs) but tucked
    in a closed ``<details>``, which only opens to pick a unit for a Save as New
    copy. Without Save as New it is a hidden input beside the text.
    """

    def __init__(self, *args, display="", allow_change=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.display = display
        self.allow_change = allow_change

    def render(self, name, value, attrs=None, renderer=None):
        shown = format_html('<span class="qc-readonly utc-locked-value">{}</span>', self.display)
        if not self.allow_change:
            hidden = forms.HiddenInput().render(name, value, attrs, renderer)
            return format_html('<div class="utc-locked">{}{}</div>', shown, hidden)
        select = super().render(name, value, attrs, renderer)
        return format_html(
            '<div class="utc-locked">{}<details class="utc-unlock"><summary>{}</summary>{}</details></div>',
            shown, _("Choose another unit for Save as New"), select,
        )


class UnitTestCollectionAdminForm(UnitTestCollectionForm):
    """UnitTestCollectionForm with the widgets of the assignment admin page.

    Same fields and validation (the Test List builder's Assign to Machine dialog
    uses UnitTestCollectionForm too, through TestListAssignMachineForm). Here the
    content type is a pair of radio buttons ("Test List" / "Test List Cycle") for
    the htmx object picker, and a saved assignment's unit is shown read-only
    (UTCLockedSelect), since UnitTestCollectionForm refuses to change it.
    """

    # Set per request by UnitTestCollectionAdmin.get_form: may this user Save as New?
    utc_can_save_as_new = False

    class Meta:
        model = models.UnitTestCollection
        fields = "__all__"
        error_messages = {
            NON_FIELD_ERRORS: {
                "unique_together": _l(
                    "This test list or cycle is already assigned to this unit at this frequency. "
                    "Choose a different unit, frequency or test list."
                ),
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ct = self.fields["content_type"]
        ct.empty_label = None
        ct.label_from_instance = _utc_type_label
        ct.widget = forms.RadioSelect(attrs={"class": "utc-type-radio"})
        ct.widget.choices = ct.choices
        ct.widget.is_required = ct.required
        self.fields["object_id"].widget.attrs["class"] = "utc-object-raw"
        if self.instance.pk:
            unit = self.fields["unit"]
            unit.widget = UTCLockedSelect(
                choices=unit.choices,
                display=self.instance.unit.name,
                allow_change=self.utc_can_save_as_new,
            )


class UnitTestCollectionAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    # readonly_fields = ("unit","frequency",)
    filter_horizontal = ("visible_to",)
    list_display = ['name', site_name, unit_name, freq_name, assigned_to_name, 'get_content_type', "active"]
    list_filter = [SiteFilter, UnitFilter, FrequencyFilter, AssignedToFilter, ActiveFilter]
    search_fields = ['name', "unit__name", "frequency__name"]
    change_form_template = "admin/qa/unittestcollection/change_form.html"
    change_list_template = "admin/qa/unittestcollection/change_list.html"
    list_editable = ["active"]
    save_as = True
    form = UnitTestCollectionAdminForm

    # The cards of admin/qa/unittestcollection/change_form.html. "What" (the test
    # list or cycle) is drawn by the page's own picker card; the others by the
    # shared QC card. Same fields as before: every editable model field.
    fieldsets = [
        (_l("What"), {"fields": ["content_type", "object_id"], "classes": ["utc-what"]}),
        (_l("Where & When"), {"fields": ["unit", "frequency", "due_date", "auto_schedule", "active"]}),
        (_l("Who"), {"fields": ["assigned_to", "visible_to"]}),
    ]

    qc_fieldset_icons = {_l("Where & When"): "fa-calendar", _l("Who"): "fa-users"}

    class Media:
        # The page's styles and JS are inlined (admin/qa/unittestcollection/utc_assets.html)
        # so they load under DEBUG=False without a collectstatic step.
        js = (
            "htmx/js/htmx.min.js",
        )

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.select_related("unit", "unit__site", "frequency", "assigned_to", "content_type")

    def get_list_display(self, request):
        # Frequency and Assigned To are drawn as small tags. list_display keeps the
        # plain columns (their ordering and empty values) at the same positions.
        tags = {freq_name: utc_frequency_tag, assigned_to_name: utc_assigned_to_tag}
        return [tags.get(col, col) for col in super().get_list_display(request)]

    def get_form(self, request, obj=None, change=False, **kwargs):
        if change and obj is not None and not self.has_change_permission(request, obj):
            # View only: every field is read-only, so the form has none, and
            # UnitTestCollectionForm.__init__ (which sets up the unit and
            # frequency fields) can't run without them.
            kwargs["form"] = forms.ModelForm
            return super().get_form(request, obj, change=change, **kwargs)
        form = super().get_form(request, obj, change=change, **kwargs)
        can_save_as_new = self.save_as and self.has_add_permission(request)
        return type(form.__name__, (form,), {"utc_can_save_as_new": can_save_as_new})

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        """Context for the What card's picker and the contents preview."""
        form = context["adminform"].form
        if form.is_bound:
            raw_type, raw_obj = form.data.get("content_type"), form.data.get("object_id")
        elif obj is not None and obj.pk:
            raw_type, raw_obj = obj.content_type_id, obj.object_id
        else:
            raw_type, raw_obj = form.initial.get("content_type"), form.initial.get("object_id")
        ct, chosen = _utc_collection(raw_type, raw_obj)
        context.update(_utc_preview_context(request.user, ct, chosen))
        context["utc_locked"] = bool(change and obj is not None and obj.pk and "content_type" in form.fields)
        context["utc_can_save_as_new"] = getattr(form, "utc_can_save_as_new", False)
        if obj is not None and obj.pk:
            context["utc_saved_type_label"] = _utc_type_label(obj.content_type)
            context["utc_saved_is_cycle"] = obj.content_type.model == "testlistcycle"
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_urls(self):
        custom_urls = [
            path(
                "search-collections/",
                self.admin_site.admin_view(self.search_collections_view),
                name="qa_unittestcollection_search",
            ),
            path(
                "contents-preview/",
                self.admin_site.admin_view(self.contents_preview_view),
                name="qa_unittestcollection_preview",
            ),
        ]
        return custom_urls + super().get_urls()

    def search_collections_view(self, request):
        """htmx: the test lists (or cycles) matching ``q``, for the What card's picker.

        GET ``content_type`` (Test List or Test List Cycle) and ``q``. For users who
        can add or change assignments.
        """
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            return HttpResponseForbidden(_("You don't have permission to assign test lists to units."))
        ct = _utc_collection_type(request.GET.get("content_type"))
        if ct is None:
            return HttpResponseBadRequest(_("Choose Test List or Test List Cycle first."))
        q = (request.GET.get("q") or "").strip()
        return render(request, "admin/qa/unittestcollection/partials/_search_results.html", {
            "results": _utc_search_results(ct, q),
            "query": q,
            "is_cycle": ct.model == "testlistcycle",
            "utc_type_label": _utc_type_label(ct),
            "limit": UTC_SEARCH_LIMIT,
        })

    def contents_preview_view(self, request):
        """htmx: the contents preview card's body for ``content_type`` and ``object_id``.

        For anyone who can open an assignment page: view or change, and also add, since
        the Add page's picker (search_collections_view) is open to add-only users.
        """
        if not (self.has_view_or_change_permission(request) or self.has_add_permission(request)):
            return HttpResponseForbidden(_("You don't have permission to view test list assignments."))
        ct, chosen = _utc_collection(request.GET.get("content_type"), request.GET.get("object_id"))
        return render(
            request,
            "admin/qa/unittestcollection/partials/_preview.html",
            _utc_preview_context(request.user, ct, chosen),
        )

    @admin.display(
        description=_l("Content Type"),
        ordering="content_type__model",
    )
    def get_content_type(self, obj):
        if obj:
            return obj.content_type.model_class().__name__
        return _("Unknown")


class TestListCycleMembershipForm(DiscardRemovedNewRowMixin, forms.ModelForm):
    """One day of a cycle: a row of the "Test Lists in This Cycle" card.

    The card draws each row itself (day, test list, number of tests), so the test
    list and its order are hidden inputs: the search picker fills in the test list
    and dragging the rows renumbers the order. They're validated and saved exactly
    as before. A row added since the page loaded and removed again before saving is
    simply dropped (DiscardRemovedNewRowMixin).
    """

    class Meta:
        model = models.TestListCycleMembership
        fields = ("test_list", "order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "test_list" in self.fields:
            self.fields["test_list"].widget = forms.HiddenInput()
        if "order" in self.fields:
            self.fields["order"].widget = forms.HiddenInput(attrs={"class": "qcy-order-input"})


class TestListCycleMembershipInline(admin.TabularInline):
    """The cycle's days, drawn as the "Test Lists in This Cycle" card
    (admin/qa/testlistcycle/change_form.html) rather than Django's table."""

    model = models.TestListCycleMembership
    form = TestListCycleMembershipForm
    # rows are added one at a time with the card's search picker
    extra = 0


#: How many test list names the Test List Cycles list shows before "and N more"
CYCLE_SUMMARY_LIST_COUNT = 3

#: How many results the cycle's Add Test List search shows at once
CYCLE_SEARCH_LIMIT = 25


def _cycle_test_lists_with_counts(qs=None):
    """Test lists annotated with their number of tests, own tests plus their sublists'.

    One query however many lists there are (a test can't be in both a list and its
    sublist, so adding the two counts doesn't count any test twice).
    """
    qs = models.TestList.objects.all() if qs is None else qs
    return qs.annotate(
        qcy_own_tests=Count("tests", distinct=True),
        qcy_sublist_tests=Count("children__child__tests", distinct=True),
    )


def _cycle_test_list_info(test_list):
    """What a cycle row or search result shows about a test list (annotated as above)."""
    return {
        "id": test_list.pk,
        "name": test_list.name,
        "slug": test_list.slug,
        "test_count": test_list.qcy_own_tests + test_list.qcy_sublist_tests,
        "edit_url": reverse("admin:qa_testlist_change", args=[test_list.pk]),
    }


def _cycle_rows(formset):
    """The rows of the "Test Lists in This Cycle" card, in day order.

    Each row is ``{"form", "info", "saved", "removed", "day"}``. After a failed save
    the rows come back the way the user left them: in the posted order, with the
    posted test lists, and saved rows they removed still removed (hidden, their
    DELETE box ticked). New rows they removed aren't brought back.
    """
    rows = []
    for index, form in enumerate(formset.forms):
        if _unsaved_and_deleted(form):
            continue
        test_list_pk = _int_param(form["test_list"].value()) if "test_list" in form.fields else None
        if test_list_pk is None:
            test_list_pk = form.instance.test_list_id
        order = _int_param(form["order"].value()) if "order" in form.fields else form.instance.order
        rows.append({
            "form": form,
            "test_list_pk": test_list_pk,
            "saved": bool(form.instance.pk),
            "removed": form.is_bound and _posted_delete(form.data, form.prefix),
            "sort_key": (order if order is not None else len(formset.forms) + index, index),
        })
    rows.sort(key=lambda row: row["sort_key"])

    test_list_pks = {row["test_list_pk"] for row in rows if row["test_list_pk"]}
    test_lists = _cycle_test_lists_with_counts().filter(pk__in=test_list_pks) if test_list_pks else []
    info = {test_list.pk: _cycle_test_list_info(test_list) for test_list in test_lists}
    day = 0
    for row in rows:
        row["info"] = info.get(row["test_list_pk"])
        if not row["removed"]:
            day += 1
            row["day"] = day
    return rows


def _can_view_test_lists(user):
    return user.has_perm("qa.view_testlist") or user.has_perm("qa.change_testlist")


class TestListCycleAdmin(QCAdminDesignMixin, SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):
    """Admin for daily test list cycles.

    The change page (admin/qa/testlistcycle/change_form.html) shows the cycle's days
    as a builder-style card: drag to reorder, remove, and add test lists with a
    search picker (search_test_lists_view and add_row_view). The days still save
    through the membership inline formset. Styles and JS:
    admin/qa/testlistcycle/testlistcycle_assets.html.
    """
    inlines = [TestListCycleMembershipInline, get_attachment_inline("testlistcycle")]
    prepopulated_fields = {
        'slug': ('name',)
    }
    search_fields = (
        "name",
        "slug",
    )
    list_display = ["name", "day_count", "test_lists_summary", "assignment_count"]

    class Media:
        # The page's own styles and JS are inlined via testlistcycle_assets.html (like
        # the Test List builder), so they load under DEBUG=False without a collectstatic
        # step. jQuery UI drags the day rows; ace is the description and JavaScript
        # editor (admin_description_editor.js); htmx runs the Add Test List search.
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "js/jquery-ui.init.js",
            "js/jquery-ui.min.js",
            "js/collapsed_stacked_inlines.js",
            "js/admin_description_editor.js",
            "ace/ace.js",
            "htmx/js/htmx.min.js",
        )

    @admin.display(description=_l("Days"), ordering="qcy_day_count")
    def day_count(self, obj):
        return obj.qcy_day_count

    @admin.display(description=_l("Test Lists"))
    def test_lists_summary(self, obj):
        names = [m.test_list.name for m in obj.testlistcyclemembership_set.all()]
        if not names:
            return format_html('<span class="qc-empty">{}</span>', _("No test lists yet"))
        shown = ", ".join(names[:CYCLE_SUMMARY_LIST_COUNT])
        hidden = len(names) - CYCLE_SUMMARY_LIST_COUNT
        if hidden > 0:
            return _("%(names)s and %(count)d more") % {"names": shown, "count": hidden}
        return shown

    @admin.display(description=_l("Assignments"), ordering="qcy_assignment_count")
    def assignment_count(self, obj):
        return obj.qcy_assignment_count

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        memberships = models.TestListCycleMembership.objects.select_related("test_list").order_by("order")
        return qs.annotate(
            qcy_day_count=Count("testlistcyclemembership", distinct=True),
            qcy_assignment_count=Count("utcs", distinct=True),
        ).prefetch_related(Prefetch("testlistcyclemembership_set", queryset=memberships))

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        for inline_admin_formset in context.get("inline_admin_formsets", []):
            if inline_admin_formset.opts.model is models.TestListCycleMembership:
                rows = _cycle_rows(inline_admin_formset.formset)
                context.update({
                    "qcy_formset": inline_admin_formset,
                    "qcy_rows": rows,
                    "qcy_day_count": sum(1 for row in rows if not row["removed"]),
                    "qcy_editable": (
                        inline_admin_formset.has_add_permission or inline_admin_formset.has_change_permission
                    ),
                    "qcy_can_add_rows": inline_admin_formset.has_add_permission,
                    "qcy_can_reorder": inline_admin_formset.has_change_permission,
                    "qcy_can_remove_saved": inline_admin_formset.formset.can_delete,
                })
        user = request.user
        context["qcy_can_view_test_lists"] = _can_view_test_lists(user)
        context["qcy_can_view_assignments"] = (
            user.has_perm("qa.view_unittestcollection") or user.has_perm("qa.change_unittestcollection")
        )
        if obj is not None and obj.pk:
            context["qcy_saved_day_count"] = obj.testlistcyclemembership_set.count()
            context["qcy_used_in"] = list(
                obj.utcs.select_related("unit", "frequency", "assigned_to").order_by("unit__name", "frequency__name")
            )
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'search-test-lists/',
                self.admin_site.admin_view(self.search_test_lists_view),
                name='qa_testlistcycle_search_lists',
            ),
            path(
                'add-row/',
                self.admin_site.admin_view(self.add_row_view),
                name='qa_testlistcycle_add_row',
            ),
        ]
        return custom_urls + urls

    def _can_edit_days(self, request):
        """The picker is for adding or changing a cycle."""
        return self.has_add_permission(request) or self.has_change_permission(request)

    def search_test_lists_view(self, request):
        """htmx: the Add Test List dialog's results.

        ``q`` filters by name or slug; ``in_cycle`` (comma separated ids: the lists
        on the page right now) are listed but can't be picked again.
        """
        if not self._can_edit_days(request):
            return HttpResponseForbidden(_("You don't have permission to change test list cycles."))
        q = (request.GET.get("q") or "").strip()
        in_cycle = {_int_param(pk) for pk in (request.GET.get("in_cycle") or "").split(",")}
        qs = _cycle_test_lists_with_counts()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
        test_lists = list(qs.order_by("name", "pk")[:CYCLE_SEARCH_LIMIT + 1])
        results = []
        for test_list in test_lists[:CYCLE_SEARCH_LIMIT]:
            info = _cycle_test_list_info(test_list)
            info["in_cycle"] = test_list.pk in in_cycle
            results.append(info)
        return render(request, "admin/qa/testlistcycle/partials/_search_results.html", {
            "results": results,
            "query": q,
            "more": len(test_lists) > CYCLE_SEARCH_LIMIT,
        })

    def add_row_view(self, request):
        """htmx: a new day row for ``test_list`` at formset index ``index``.

        The row is a real form of the membership formset (same prefix, hidden inputs
        and fk as the rows Django renders), so it saves like any other row once the
        page bumps TOTAL_FORMS.
        """
        cycle_pk = _int_param(request.GET.get("cycle"))
        cycle = self.model.objects.filter(pk=cycle_pk).first() if cycle_pk else None
        inline = TestListCycleMembershipInline(self.model, self.admin_site)
        # the same rule as the page's Add Test List button (qcy_can_add_rows): the
        # membership model has permissions of its own
        if not (self._can_edit_days(request) and inline.has_add_permission(request, cycle)):
            return HttpResponseForbidden(_("You don't have permission to change test list cycles."))
        test_list = get_object_or_404(_cycle_test_lists_with_counts(), pk=_int_param(request.GET.get("test_list"), 0))
        index = _int_param(request.GET.get("index"), 0)

        FormSet = inline.get_formset(request, cycle)
        formset = FormSet(instance=cycle or self.model(), prefix=FormSet.get_default_prefix())
        # what BaseFormSet.empty_form does, at a real index and with the test list filled in
        form = formset.form(
            auto_id=formset.auto_id,
            prefix=formset.add_prefix(index),
            initial={"test_list": test_list.pk, "order": index},
            empty_permitted=True,
            use_required_attribute=False,
            renderer=formset.renderer,
        )
        formset.add_fields(form, None)
        return render(request, "admin/qa/testlistcycle/partials/_cycle_row.html", {
            "row": {
                "form": form,
                "info": _cycle_test_list_info(test_list),
                "saved": False,
                "removed": False,
                "day": index + 1,
            },
            "qcy_editable": True,
            "qcy_can_reorder": inline.has_change_permission(request, cycle),
            "qcy_can_view_test_lists": _can_view_test_lists(request.user),
        })


class FrequencyForm(forms.ModelForm):

    class Meta:
        model = models.Frequency
        fields = (
            'name',
            'slug',
            'recurrences',
            'window_start',
            'window_end',
        )

    def clean(self):
        """Ensure the define frequency has a valid set of occurences"""

        super().clean()

        recurrences = self.cleaned_data.get('recurrences')
        if recurrences and not scheduling.calc_nominal_interval(recurrences):
            self.add_error(
                'recurrences', 'This frequency has zero occurences. Please adjust the schedule and try again'
            )
        elif recurrences and len(recurrences.rrules) == 0:
            self.add_error(
                'recurrences', 'This frequency has exclusion rules only. Please adjust the schedule and try again'
            )
        return self.cleaned_data


# How many due dates the Frequency page's "Next due dates" list shows, and how many
# assignments its Used In card lists before pointing to the full list.
FREQUENCY_NEXT_DUE_COUNT = 8
FREQUENCY_USED_IN_LIMIT = 25
FREQUENCY_WINDOW_FIELDSET = _l("Due Window")
FREQUENCY_SCHEDULE_FIELDSET = _l("Schedule")


class FrequencyPreviewForm(forms.Form):
    """The schedule as it stands in the Frequency form, for the "Next due dates" list.

    Nothing is saved from it. Its checks are gentler than FrequencyForm's: an empty or
    half-finished schedule is normal while someone is still building it."""

    recurrences = models.Frequency._meta.get_field("recurrences").formfield(required=False)
    window_start = forms.IntegerField(min_value=0, required=False)
    window_end = forms.IntegerField(min_value=0, required=False)


def frequency_next_due_dates(data, now=None, count=FREQUENCY_NEXT_DUE_COUNT):
    """The next `count` due dates for the schedule in `data` (recurrences, window_start
    and window_end as posted by the Frequency form), worked out with the same
    qatrack_core.scheduling helpers used for real assignments: QC performed today, then
    on each due date. Each date comes with its QC window.

    Returns a dict for admin/qa/frequency/_next_due.html: ``dates``, ``classic`` and a
    friendly ``message`` (with ``is_error``) when there's nothing to list."""
    result = {"dates": [], "classic": False, "message": "", "is_error": False}
    form = FrequencyPreviewForm(data)
    if not form.is_valid():
        result["is_error"] = True
        if "recurrences" in form.errors:
            result["message"] = _("This schedule can't be read yet. Check its rules and dates.")
        else:
            result["message"] = _("The QC window start and end are whole numbers of days, 0 or more.")
        return result

    recurrences = form.cleaned_data["recurrences"]
    if recurrences is None or not (recurrences.rrules or recurrences.rdates):
        if recurrences is not None and (recurrences.exrules or recurrences.exdates):
            result["is_error"] = True
            result["message"] = _("This schedule only excludes dates. Add a rule or a date for QC to be due.")
        else:
            result["message"] = _("Add a rule or a date to the schedule to see when QC will be due.")
        return result

    frequency = models.Frequency(
        recurrences=recurrences,
        window_start=form.cleaned_data["window_start"],
        window_end=form.cleaned_data["window_end"] or 0,
    )
    if recurrences.dtstart is None:
        frequency.relocalize_recurrence()
    result["classic"] = frequency.classical

    now = timezone.localtime(now or timezone.now())
    try:
        # A first completion today: calc_due_date with no due date yet, as for a new assignment.
        due = scheduling.calc_due_date(now, None, frequency)
        while due is not None and len(result["dates"]) < count:
            window_start, window_end = scheduling.qc_window(due, frequency)
            result["dates"].append({"due": due, "window_start": window_start, "window_end": window_end})
            next_due = scheduling.calc_due_date(due, due, frequency)
            if next_due is None or next_due <= due:
                break
            due = next_due
    except (ValueError, TypeError, OverflowError):
        result["dates"] = []
        result["is_error"] = True
        result["message"] = _("This schedule can't be read yet. Check its rules and dates.")
        return result

    if not result["dates"]:
        result["is_error"] = True
        result["message"] = _("This schedule has no due dates after today. Check its dates and any end date or count.")
    return result


def _frequency_form_schedule_data(form, obj=None):
    """The recurrences/window values the Frequency change form is showing: what was
    posted when the form is bound, otherwise the saved (or default) values. (A
    view-only page's form has no fields; its values are the saved ones.)"""
    names = ("recurrences", "window_start", "window_end")
    if form.is_bound:
        return {name: form.data.get(name, "") for name in names}

    data = {}
    for name in names:
        if name in form.fields:
            value = form[name].value()
        else:
            value = getattr(obj, name, None)
        if name == "recurrences" and value and not isinstance(value, str):
            value = str(value)  # the serialized rules, as the widget shows them
        data[name] = "" if value is None else value
    return data


class FrequencyAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    prepopulated_fields = {
        'slug': ('name',)
    }
    form = FrequencyForm
    # Cards: Details, Due Window, Schedule, then the Preview and Used In cards from
    # admin/qa/frequency/change_form.html.
    fieldsets = (
        (None, {"fields": ("name", "slug")}),
        (FREQUENCY_WINDOW_FIELDSET, {"fields": ("window_start", "window_end")}),
        (FREQUENCY_SCHEDULE_FIELDSET, {"fields": ("recurrences",)}),
    )
    qc_fieldset_icons = {
        FREQUENCY_WINDOW_FIELDSET: "fa-clock-o",
        FREQUENCY_SCHEDULE_FIELDSET: "fa-repeat",
    }

    list_display = (
        "name",
        "get_recurrences",
        "window_start",
        "window_end",
    )

    class Media:
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "js/jquery-ui.min.js",
            "moment/js/moment.min.js",
            "moment/js/moment-timezone-with-data.min.js",
            "rrule/js/rrule-tz.min.js",
            "d3/js/d3-3.5.6.min.js",
            "cal-heatmap/js/cal-heatmap.min.js",
            "js/frequency_admin.js",
            # The "Next due dates" list refreshes over htmx (admin/qa/frequency/frequency_assets.html).
            "htmx/js/htmx.min.js",
        )
        css = {
            'all': ["cal-heatmap/css/cal-heatmap.css"],
        }

    def get_urls(self):
        custom_urls = [
            path(
                'next-due-dates/',
                self.admin_site.admin_view(self.next_due_dates_view),
                name='qa_frequency_next_due',
            ),
        ]
        return custom_urls + super().get_urls()

    def next_due_dates_view(self, request):
        """POST (htmx): the "Next due dates" list for the schedule in the posted form.
        For anyone who can add or change frequencies; nothing is saved. A schedule that
        can't be used yet answers 422 with its friendly message in the list's place."""
        if request.method != "POST":
            from django.http import HttpResponseNotAllowed
            return HttpResponseNotAllowed(["POST"])
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            return HttpResponseForbidden()
        next_due = frequency_next_due_dates(request.POST)
        status = 422 if next_due["is_error"] else 200
        return render(request, "admin/qa/frequency/_next_due.html", {"next_due": next_due}, status=status)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        """Context for the Preview and Used In cards in admin/qa/frequency/change_form.html."""
        form = context["adminform"].form
        context["qcf_next_due"] = frequency_next_due_dates(_frequency_form_schedule_data(form, obj))
        context["qcf_used_in"] = []
        context["qcf_used_in_count"] = 0
        if obj is not None and obj.pk:
            utcs = obj.unittestcollections.select_related("unit", "content_type").order_by("unit__name", "name")
            context["qcf_used_in_count"] = utcs.count()
            context["qcf_used_in"] = list(utcs[:FREQUENCY_USED_IN_LIMIT])
            context["qcf_used_in_more"] = context["qcf_used_in_count"] - len(context["qcf_used_in"])
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    @admin.display(description=_l("Recurrences"))
    @mark_safe
    def get_recurrences(self, obj):
        rules = str(obj.recurrences).replace("RRULE:", "").split("\n")[1:]
        processed = []
        for rule in rules:
            if rule.startswith("EXDATE") or rule.startswith("RDATE"):
                date = rule.split(":")[-1]
                date = "%s-%s-%s" % (date[:4], date[4:6], date[6:8])
                inc = "Exclude" if rule.startswith("EXDATE") else "Include"
                rule = "%s: %s" % (inc, date)

            processed.append(rule)

        return "<br/>".join(processed)


def qc_status_label(name, colour, extra_class=""):
    """A status as the design spec's status label (``.service-event-status-label``).

    The name in black on a transparent box with a 2px border in the status colour,
    so any colour a site picks stays readable and the colour always comes with its
    word. Colours that aren't a valid saved colour (``rgba(r,g,b,a)``), e.g. a typo
    in a form that failed to save, are left out rather than put in the style.
    """
    colour = colour if colour and models.color_re.match(colour) else ""
    return format_html(
        '<span class="qcs-label service-event-status-label{}" style="border-color: {}">{}</span>',
        " " + extra_class if extra_class else "",
        colour or "transparent",
        name,
    )


class StatusAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    prepopulated_fields = {
        'slug': ('name',)
    }
    model = models.TestInstanceStatus

    list_display = (
        'name',
        'is_default',
        'requires_review',
        'valid',
        'get_colour',
    )

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description'),
        }),
        (_l("Behaviour"), {
            'fields': ('is_default', 'requires_review', 'valid', 'export_by_default'),
        }),
        (_l("Colour"), {
            'fields': ('colour', 'label_preview'),
        }),
    )
    # label_preview isn't saved: it shows how the label will look (status_assets.html
    # keeps it up to date as the name and colour change).
    readonly_fields = ('label_preview',)
    qc_fieldset_icons = {
        None: "fa-info-circle",
        fieldsets[1][0]: "fa-sliders",
        fieldsets[2][0]: "fa-paint-brush",
    }

    class Media:
        js = (
            'admin/js/jquery.init.js',
            "jquery/js/jquery.min.js",
            "colorpicker/js/bootstrap-colorpicker.min.js",
            "qatrack_core/js/admin_colourpicker.js",
        )
        css = {
            'all': (
                "colorpicker/css/bootstrap-colorpicker.min.css",
                "qatrack_core/css/admin.css",
            ),
        }

    @admin.display(description=_l("Label"))
    def get_colour(self, obj):
        """The status as it's labelled across QATrack+: its name, bordered in its colour."""
        return qc_status_label(obj.name, obj.colour)

    @admin.display(description=_l("Label Preview"))
    def label_preview(self, obj):
        colour = obj.colour if obj else settings.DEFAULT_TEST_STATUS_COLOUR
        if obj and obj.name:
            return qc_status_label(obj.name, colour, "qcs-label-preview")
        return qc_status_label(_("Status name"), colour, "qcs-label-preview qcs-label-empty")


@admin.display(
    description=_l("Unit"),
    ordering="unit_test_collection__unit__name",
)
def utc_unit_name(obj):
    return obj.unit_test_collection.unit.name


def qci_status_label(status):
    """A test instance status as the design spec's status label: its colour as the
    border, black text, the status name (status colours always come with their word)."""
    if status is None:
        return ""
    colour = status.colour if status.colour and models.color_re.match(status.colour) else "transparent"
    return format_html('<span class="qci-label" style="border-color: {}">{}</span>', colour, status.name)


def qci_pass_fail_label(pass_fail):
    """A test instance's pass/fail result as a status label, using the site's own name for it."""
    if not pass_fail:
        return ""
    return format_html(
        '<span class="qci-label qci-pf-{}">{}</span>',
        pass_fail,
        models.PASS_FAIL_CHOICES_DISPLAY.get(pass_fail, pass_fail),
    )


TLI_PERFORMED = _l("Performed")
TLI_REVIEW = _l("Review")
TLI_RECORD = _l("Scheduling & Record")
TLI_COMMENTS = _l("Comments")


class TestListInstanceAdmin(QCAdminDesignMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):
    list_display = ["instance_id", utc_unit_name, "test_list", "work_completed", "created_by", "review_state"]
    list_display_links = ["instance_id"]
    list_filter = [
        "unit_test_collection__unit",
        "test_list",
    ]
    inlines = [get_attachment_inline("testlistinstance")]

    # Every field that's editable on the model stays editable (work_started,
    # work_completed, due_date, day, in_progress, all_reviewed, reviewed,
    # include_for_scheduling, user_key, modified); the rest are shown read-only.
    fieldsets = (
        (TLI_PERFORMED, {
            "fields": (
                "unit_test_collection", "test_list", "day", "due_date", "work_started", "work_completed",
                "created_by", "created",
            ),
        }),
        (TLI_REVIEW, {
            "fields": ("in_progress", "all_reviewed", "reviewed", "reviewed_by", "flagged"),
        }),
        (TLI_RECORD, {
            "fields": ("include_for_scheduling", "user_key", "modified", "modified_by"),
        }),
        (TLI_COMMENTS, {
            "fields": ("comments_display",),
        }),
    )
    readonly_fields = (
        "unit_test_collection", "test_list", "created_by", "created", "reviewed_by", "flagged", "modified_by",
        "comments_display",
    )
    qc_fieldset_icons = {
        TLI_PERFORMED: "fa-clipboard",
        TLI_REVIEW: "fa-check-square-o",
        TLI_RECORD: "fa-history",
        TLI_COMMENTS: "fa-commenting-o",
    }
    qc_wide_fields = ("comments_display",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("unit_test_collection__unit", "test_list", "created_by")

    @admin.display(description=_l("ID"), ordering="pk")
    def instance_id(self, obj):
        return obj.pk

    @admin.display(description=_l("Review Status"), ordering="all_reviewed")
    def review_state(self, obj):
        if obj.in_progress:
            return format_html('<span class="qci-label qci-pf-not_done">{}</span>', _("In Progress"))
        if obj.all_reviewed:
            return format_html('<span class="qci-label qci-pf-ok">{}</span>', _("Reviewed"))
        return format_html('<span class="qci-label qci-pf-tolerance">{}</span>', _("Unreviewed"))

    @admin.display(description=_l("Comments"))
    def comments_display(self, obj):
        """The session's comments, oldest first (they're added on the review page, not here)."""
        comments = list(obj.comments.select_related("user").order_by("submit_date")) if obj.pk else []
        if not comments:
            return format_html('<span class="qc-empty">{}</span>', _("No comments"))
        rows = format_html_join(
            "",
            '<li><span class="qci-comment-meta">{} &middot; {}</span><span class="qci-comment-text">{}</span></li>',
            (
                (c.name, date_formatter(timezone.localtime(c.submit_date), "DATETIME_FORMAT"), c.comment)
                for c in comments
            ),
        )
        return format_html('<ul class="qci-comments">{}</ul>', rows)

    def render_delete_form(self, request, context):
        instance = context['object']

        # Find related Service events with rtsqa and with initiated by
        ServiceEvent = apps.get_model('service_log', 'ServiceEvent')
        ServiceEventStatus = apps.get_model('service_log', 'ServiceEventStatus')
        se_rtsqa_qs = ServiceEvent.objects.filter(returntoserviceqa__test_list_instance=context['object'])
        se_ib_qs = instance.serviceevents_initiated.all()
        default_ses = ServiceEventStatus.get_default()
        context.update({'se_rtsqa_qs': se_rtsqa_qs, 'se_ib_qs': se_ib_qs, 'default_ses': default_ses})
        # The test instances deleted with it, listed on the confirmation page
        context['test_instances'] = instance.testinstance_set.select_related(
            "unit_test_info__test", "status", "modified_by",
        ).order_by("order", "pk")
        return super().render_delete_form(request, context)

    def has_add_permission(self, request):
        """testlistinstancess are created via front end only"""
        return False


TI_RESULT = _l("Result")
TI_CONTEXT = _l("Context")
TI_STORED = _l("Stored Analysis Results")


class TestInstanceAdmin(QCAdminDesignMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

    list_display = [
        "instance_id",
        "test_name",
        "unit_name",
        "test_list_name",
        "test_list_instance_id",
        "status_label",
        "pass_fail_label",
        "work_completed",
        "created_by",
    ]
    list_display_links = ["instance_id"]
    inlines = [get_attachment_inline("testinstance")]

    # Every field that's editable on the model stays editable (status, the values,
    # skipped, comment, work_completed, order, created); the rest are shown read-only.
    fieldsets = (
        (TI_RESULT, {
            "fields": (
                "value", "string_value", "date_value", "datetime_value", "skipped", "status",
                "pass_fail_label", "reviewed_by", "review_date", "comment",
            ),
        }),
        (TI_CONTEXT, {
            "fields": (
                "unit_test_info_link", "test_list_instance_link", "reference", "tolerance", "work_started",
                "work_completed", "order", "created", "created_by", "modified", "modified_by",
            ),
        }),
        (TI_STORED, {
            "fields": ("json_value",),
        }),
    )
    readonly_fields = (
        "pass_fail_label", "reviewed_by", "review_date", "unit_test_info_link", "test_list_instance_link",
        "reference", "tolerance", "work_started", "created_by", "modified", "modified_by",
    )
    qc_fieldset_icons = {
        TI_RESULT: "fa-check-circle-o",
        TI_CONTEXT: "fa-sitemap",
        TI_STORED: "fa-database",
    }

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "test_list_instance", "test_list_instance__test_list", "unit_test_info", "unit_test_info__test",
            "created_by", "unit_test_info__unit", "status",
        )

    @admin.display(description=_l("ID"), ordering="pk")
    def instance_id(self, obj):
        return obj.pk

    @admin.display(description=_l("Test List Instance"), ordering="test_list_instance_id")
    def test_list_instance_id(self, obj):
        return obj.test_list_instance_id

    @admin.display(description=_l("Status"), ordering="status__name")
    def status_label(self, obj):
        return qci_status_label(obj.status)

    @admin.display(description=_l("Pass Fail"), ordering="pass_fail")
    def pass_fail_label(self, obj):
        return qci_pass_fail_label(obj.pass_fail)

    @admin.display(description=_l("Unit Test Info"))
    def unit_test_info_link(self, obj):
        uti = obj.unit_test_info
        url = reverse("admin:qa_unittestinfo_change", args=(uti.pk,), current_app=self.admin_site.name)
        return format_html('<a href="{}">{} &middot; {}</a>', url, uti.test.name, uti.unit.name)

    @admin.display(description=_l("Test List Instance"))
    def test_list_instance_link(self, obj):
        tli = obj.test_list_instance
        url = reverse("admin:qa_testlistinstance_change", args=(tli.pk,), current_app=self.admin_site.name)
        completed = date_formatter(timezone.localtime(tli.work_completed), "DATETIME_FORMAT") if tli.work_completed else ""
        return format_html(
            '<a href="{}">{} &middot; {}</a>',
            url,
            tli.test_list.name,
            completed or _("ID %(id)s") % {"id": tli.pk},
        )

    @admin.display(
        description=_l("Test List Name"),
        ordering="test_list_instance__test_list__name",
    )
    def test_list_name(self, obj):
        return obj.test_list_instance.test_list.name

    @admin.display(
        description=_l("Test Name"),
        ordering="unit_test_info__test__name",
    )
    def test_name(self, obj):
        return obj.unit_test_info.test.name

    @admin.display(
        description=_l("Unit Name"),
        ordering="unit_test_info__unit__number",
    )
    def unit_name(self, obj):
        return obj.unit_test_info.unit

    def has_add_permission(self, request):
        """testistinstancess are created via front end only"""
        return False


class ToleranceForm(forms.ModelForm):

    model = models.Tolerance

    def validate_unique(self):
        super().validate_unique()
        if not self.instance.pk:
            params = forms.model_to_dict(self.instance)
            params.pop("id")
            if models.Tolerance.objects.filter(**params).count() > 0:
                errs = [_("Duplicate Tolerance. A Tolerance with these values already exists")]
                self._update_errors({forms.models.NON_FIELD_ERRORS: errs})


class MachineNewToleranceForm(ToleranceForm):
    """ToleranceForm for the builder's New Tolerance dialog.

    Same model validation (including the limit order check in
    Tolerance.clean_tols) and duplicate check as the Tolerance admin; the types
    are limited to the ones that fit the test (new_tolerance_types).
    ``duplicate`` holds the existing tolerance when the duplicate check fails,
    so the dialog can offer it.
    """

    LIMIT_FIELDS = ("act_low", "tol_low", "tol_high", "act_high")

    class Meta:
        model = models.Tolerance
        fields = ["type", "act_low", "tol_low", "tol_high", "act_high", "mc_pass_choices", "mc_tol_choices"]

    def __init__(self, *args, types=None, **kwargs):
        kwargs.setdefault("auto_id", "tl-newtol-%s")
        super().__init__(*args, **kwargs)
        self.duplicate = None
        labels = dict(models.TOL_TYPE_CHOICES)
        self.types = list(types or [])
        self.fields["type"].choices = [(t, labels[t]) for t in self.types]
        if len(self.types) == 1:
            self.fields["type"].widget = forms.HiddenInput()
            self.initial.setdefault("type", self.types[0])
        else:
            self.initial.setdefault("type", models.ABSOLUTE)
        for name, field in self.fields.items():
            if name != "type" or len(self.types) > 1:
                field.widget.attrs["class"] = "tl-modal-input"
        for name in self.LIMIT_FIELDS:
            self.fields[name].widget.attrs["step"] = "any"

    def validate_unique(self):
        super().validate_unique()
        if not self.instance.pk and self.has_error(forms.models.NON_FIELD_ERRORS):
            params = forms.model_to_dict(self.instance)
            params.pop("id")
            self.duplicate = models.Tolerance.objects.filter(**params).first()


def testlist_new_tolerance(request):
    """The builder's New Tolerance dialog, opened from the Reference and Tolerance dialog.

    GET ``uti=<UnitTestInfo id>`` returns the dialog, offering only the tolerance
    types that fit that test (new_tolerance_types; none for Boolean tests, which
    is a 400). POST validates with MachineNewToleranceForm (the Tolerance admin's
    ToleranceForm) and creates the Tolerance straight away, with created_by and
    modified_by set as the admin does. It isn't applied to any unit: the
    Reference and Tolerance dialog does that when saved. Success returns JSON for
    that dialog's Tolerance select; errors return this dialog again with status 422.
    """
    if not request.user.has_perm("qa.add_tolerance"):
        return HttpResponseForbidden(_("You don't have permission to create tolerances. Nothing was saved."))

    raw_id = request.POST.get("uti") if request.method == "POST" else request.GET.get("uti")
    try:
        uti = models.UnitTestInfo.objects.select_related("test", "unit").get(pk=int(raw_id or ""))
    except (ValueError, TypeError, models.UnitTestInfo.DoesNotExist):
        raise Http404(_("Unit test info not found"))

    types = new_tolerance_types(uti.test)
    if not types:
        return HttpResponseBadRequest(_("New tolerances can't be created for this test type. Nothing was saved."))

    status = 200
    if request.method == "POST":
        form = MachineNewToleranceForm(request.POST, types=types)
        if form.is_valid():
            tol = form.save(commit=False)
            tol.created_by = request.user
            tol.modified_by = request.user
            tol.save()
            return JsonResponse({
                "ok": True,
                "id": tol.pk,
                "label": tol.plain_display(),
                "title": tol.plain_display_title(),
                "message": _("Created %(tolerance)s.") % {"tolerance": tol.plain_display()},
            })
        status = 422
    else:
        form = MachineNewToleranceForm(types=types)

    return render(request, "admin/qa/testlist/partials/_machine_new_tolerance_modal.html", {
        "form": form,
        "uti": uti,
        "test_name": uti.test.get_display_name(),
        "is_choice": types == [models.MULTIPLE_CHOICE],
        "type_label": dict(models.TOL_TYPE_CHOICES)[types[0]] if len(types) == 1 else "",
    }, status=status)


def tolerance_limit_zones(tol):
    """The result zones a numerical tolerance gives, low to high, for the limits preview.

    Returns ``[zone, (field, value), zone, …]``: each zone is OK, TOLERANCE or ACTION
    and each ``(field, value)`` a limit that is set. A blank limit isn't used, as in
    TestInstance.float_pass_fail, so a zone runs on to the next limit that is set.
    Two equal limits next to each other (allowed: Tolerance.clean_tols only needs
    them in order) have no zone between them, since no value lies strictly between.
    Limits that are out of order (which won't save) give ``None`` for every zone.
    tolerance_assets.html draws the same zones in the browser as limits are typed.
    """
    fields = (models.ACT_LOW, models.TOL_LOW, models.TOL_HIGH, models.ACT_HIGH)
    limits = [(f, getattr(tol, f)) for f in fields if getattr(tol, f) is not None]
    if not limits:
        return []
    if any(low > high for (_lf, low), (_hf, high) in zip(limits, limits[1:])):
        result = [None]
        for limit in limits:
            result += [limit, None]
        return result

    def zone(value):
        al = tol.act_low if tol.act_low is not None else float("-inf")
        tl = tol.tol_low if tol.tol_low is not None else float("-inf")
        th = tol.tol_high if tol.tol_high is not None else float("inf")
        ah = tol.act_high if tol.act_high is not None else float("inf")
        if not al <= value <= ah:
            return models.ACTION
        if not tl <= value <= th:
            return models.TOLERANCE
        return models.OK

    values = [v for _f, v in limits]
    # A point inside each gap between limits (and beyond each end) tells its zone.
    points = [values[0] - 1] + [(a + b) / 2. for a, b in zip(values, values[1:])] + [values[-1] + 1]
    result = [zone(points[0])]
    for i, ((field, value), point) in enumerate(zip(limits, points[1:])):
        result.append((field, value))
        if i + 1 < len(limits) and limits[i + 1][1] == value:
            # no gap between equal limits, so no zone to show
            continue
        result.append(zone(point))
    return result


class ToleranceAdmin(QCAdminDesignMixin, BasicSaveUserAdmin):
    form = ToleranceForm
    list_filter = ["type"]

    fieldsets = (
        (_l("Type"), {
            # bool_warning_only is only for Boolean tolerances, which this page never
            # edits; it stays in the form (as before) but is hidden (tolerance_assets.html).
            'fields': ('type', 'bool_warning_only'),
        }),
        (_l("Limits"), {
            'fields': ('act_low', 'tol_low', 'tol_high', 'act_high', 'limits_preview'),
        }),
        (_l("Multiple Choice Values"), {
            'fields': ('mc_pass_choices', 'mc_tol_choices', 'choices_preview'),
        }),
    )
    # The previews aren't saved: tolerance_assets.html redraws them as values are typed.
    readonly_fields = ('limits_preview', 'choices_preview')
    qc_wide_fields = ('limits_preview', 'choices_preview')
    qc_fieldset_icons = {
        fieldsets[0][0]: "fa-info-circle",
        fieldsets[1][0]: "fa-arrows-h",
        fieldsets[2][0]: "fa-list-ul",
    }

    # The old Media script (js/tolerance_admin.js) hid bool_warning_only by Django's
    # .form-row markup, which the cards don't have: tolerance_assets.html does it now,
    # along with showing only the card that fits the chosen type.

    LIMIT_FIELDS = (models.ACT_LOW, models.TOL_LOW, models.TOL_HIGH, models.ACT_HIGH)

    @staticmethod
    def _status_words():
        return {models.OK: models.OK_DISP, models.TOLERANCE: models.TOL_DISP, models.ACTION: models.ACT_DISP}

    @classmethod
    def limit_labels(cls):
        return {f: str(models.Tolerance._meta.get_field(f).verbose_name) for f in cls.LIMIT_FIELDS}

    @admin.display(description=_l("Preview"))
    def limits_preview(self, obj):
        words = self._status_words()
        labels = self.limit_labels()
        items, warning = [], ""
        for item in tolerance_limit_zones(obj) if obj else []:
            if isinstance(item, tuple):
                field, value = item
                items.append({"limit": True, "field": field, "label": labels[field], "value": obj._plain_limit(value)})
            else:
                items.append({"zone": item or "unknown", "word": words.get(item, "?")})
        limits = [(f, getattr(obj, f)) for f in self.LIMIT_FIELDS if obj and getattr(obj, f) is not None]
        for (low_field, low), (high_field, high) in zip(limits, limits[1:]):
            if low > high:
                # Same words as the server's check (Tolerance.clean_tols)
                warning = _("%(high)s must be at least %(low)s.") % {"high": labels[high_field], "low": labels[low_field]}
                break
        return loader.render_to_string("admin/qa/tolerance/_limits_preview.html", {
            "items": items,
            "warning": warning,
            "type": obj.type if obj else "",
        })

    @admin.display(description=_l("Preview"))
    def choices_preview(self, obj):
        def split(value):
            return [c.strip() for c in (value or "").split(",") if c.strip()]

        pass_choices = split(obj.mc_pass_choices) if obj else []
        tol_choices = split(obj.mc_tol_choices) if obj else []
        # Results are matched to the choices ignoring case, OK list first.
        lowered = {c.lower() for c in pass_choices}
        return loader.render_to_string("admin/qa/tolerance/_choices_preview.html", {
            "pass_choices": pass_choices,
            "tol_choices": tol_choices,
            "in_both": [c for c in tol_choices if c.lower() in lowered],
            "words": self._status_words(),
            "type": obj.type if obj else "",
        })

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj is not None and obj.pk:
            utis = models.UnitTestInfo.objects.filter(tolerance=obj).exclude(test__hidden=True)
            context["qct_used_count"] = utis.count()
            context["qct_used_units"] = list(
                utis.values("unit_id", "unit__name").annotate(n=Count("id")).order_by("unit__name")
            )
            if request.user.has_perm("qa.view_unittestinfo") or request.user.has_perm("qa.change_unittestinfo"):
                # tolerance__id__exact (and unit__id__exact) are lookups the Unit Test
                # Info list accepts without a list filter of its own.
                context["qct_used_url"] = "%s?tolerance__id__exact=%d" % (
                    reverse("admin:qa_unittestinfo_changelist"), obj.pk
                )
        # For tolerance_assets.html's previews (json_script)
        context["qct_js"] = {
            "words": {k: str(v) for k, v in self._status_words().items()},
            "labels": self.limit_labels(),
            "percent": models.PERCENT,
            "choice": models.MULTIPLE_CHOICE,
        }
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.exclude(type=models.BOOLEAN)

    def has_change_permission(self, request, obj=None):

        if obj and obj.type == models.BOOLEAN:
            return False
        return super().has_change_permission(request, obj)


# QC result colours from the design spec, for the result (pass/fail) labels on the
# Auto Review pages. Always drawn with the result's name.
QC_RESULT_COLOURS = {
    models.OK: "#00a65a",
    models.TOLERANCE: "#f39c12",
    models.ACTION: "#dd4b39",
    models.NO_TOL: "#00c0ef",
    models.NOT_DONE: "#b5bbc8",
}


def qc_result_label(pass_fail):
    """A QC result (OK, Tolerance, …) as a label bordered in its design spec colour."""
    return format_html(
        '<span class="qca-result" style="border-color: {}">{}</span>',
        QC_RESULT_COLOURS.get(pass_fail, "#d2d6de"),
        models.PASS_FAIL_CHOICES_DISPLAY.get(pass_fail, pass_fail),
    )


def auto_review_rule_display(rule):
    """"OK → [Approved]": the result and the status label it sets."""
    return format_html(
        '<span class="qca-rule">{} <span class="qca-arrow" aria-hidden="true">&rarr;</span>'
        '<span class="tl-visually-hidden">{}</span> {}</span>',
        qc_result_label(rule.pass_fail),
        _("sets the status to"),
        qc_status_label(rule.status.name, rule.status.colour),
    )


def status_label_data():
    """{status id: {"name", "colour"}} for pages that redraw a status label in the browser."""
    return {
        str(s.pk): {"name": s.name, "colour": s.colour if models.color_re.match(s.colour or "") else ""}
        for s in models.TestInstanceStatus.objects.order_by("name")
    }


class AutoReviewAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    list_display = ("__str__", "pass_fail", "status", "status_label")
    list_editable = ["pass_fail", "status"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("status")

    @admin.display(description=_l("Status Label"), ordering="status__name")
    def status_label(self, obj):
        """The saved status as its label; autoreviewrule/change_list.html redraws it as the select changes."""
        return qc_status_label(obj.status.name, obj.status.colour)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["qca_statuses"] = status_label_data()
        return super().changelist_view(request, extra_context=extra_context)


class AutoReviewRuleCheckboxes(forms.CheckboxSelectMultiple):
    """The rule set's rules as a checkbox list grouped by result, each with its status label.

    Replaces the old two-list (filter_horizontal) picker; it posts the same rule ids.
    Groups follow PASS_FAIL_CHOICES order (OK, Tolerance, …) and only results that
    have rules are shown.
    """

    template_name = "admin/qa/autoreviewruleset/_rules_checkboxes.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        by_result = {}
        for _group, group_options, _index in context["widget"]["optgroups"]:
            for option in group_options:
                rule = getattr(option["value"], "instance", None)
                if rule is None:
                    continue
                option["status_label"] = qc_status_label(rule.status.name, rule.status.colour)
                by_result.setdefault(rule.pass_fail, []).append(option)
        context["widget"]["result_groups"] = [
            {"key": key, "label": qc_result_label(key), "name": display, "options": by_result[key]}
            for key, display in models.PASS_FAIL_CHOICES if key in by_result
        ]
        return context


class AutoReviewRuleSetAdminForm(forms.ModelForm):

    # Same field as the model's (required, the same rules), drawn as a checkbox list.
    rules = forms.ModelMultipleChoiceField(
        queryset=models.AutoReviewRule.objects.select_related("status").order_by("status__name", "pk"),
        widget=AutoReviewRuleCheckboxes,
        label=models.AutoReviewRuleSet._meta.get_field("rules").verbose_name,
        help_text=models.AutoReviewRuleSet._meta.get_field("rules").help_text,
    )

    class Meta:
        model = models.AutoReviewRuleSet
        fields = '__all__'

    def clean_is_default(self):

        is_default = self.cleaned_data['is_default']
        if is_default and not self.initial.get('is_default', False):
            if self.instance.pk is None and models.AutoReviewRuleSet.objects.filter(is_default=True).exists():
                raise forms.ValidationError(
                    _("There must be one default auto review rule set. Edit another rule set to be default first.")
                )
        return is_default


class AutoReviewRuleSetAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    list_display = ("__str__", "is_default", 'get_rules_display')

    form = AutoReviewRuleSetAdminForm

    fieldsets = (
        (None, {
            'fields': ('name', 'is_default'),
        }),
        (_l("Rules"), {
            'fields': ('rules',),
        }),
    )
    qc_wide_fields = ('rules',)
    qc_fieldset_icons = {
        None: "fa-info-circle",
        fieldsets[1][0]: "fa-check-square-o",
    }

    # How many tests the Used In card lists before pointing to the Tests list.
    USED_IN_LIMIT = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            Prefetch("rules", queryset=models.AutoReviewRule.objects.select_related("status"))
        )

    @admin.display(description=_l("Rules"))
    def get_rules_display(self, obj):
        order = [key for key, _display in models.PASS_FAIL_CHOICES]
        rules = sorted(obj.rules.all(), key=lambda r: (order.index(r.pass_fail) if r.pass_fail in order else 99, r.pk))
        return format_html_join(mark_safe("<br>"), "{}", ((auto_review_rule_display(rule),) for rule in rules))

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj is not None and obj.pk:
            tests = models.Test.objects.filter(autoreviewruleset=obj).order_by("name")
            context["qca_used_count"] = tests.count()
            context["qca_used_tests"] = list(tests.only("pk", "name")[:self.USED_IN_LIMIT])
            if request.user.has_perm("qa.view_test") or request.user.has_perm("qa.change_test"):
                context["qca_can_view_tests"] = True
                # A lookup the Tests list accepts without a list filter of its own.
                context["qca_used_url"] = "%s?autoreviewruleset__id__exact=%d" % (
                    reverse("admin:qa_test_changelist"), obj.pk
                )
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)


class AutoSaveAdmin(QCAdminDesignMixin, BaseQATrackAdmin):
    list_display = (
        "created", "created_by", 'modified', 'modified_by', 'unit', 'unit_test_collection', 'test_list', 'recover'
    )
    # The saved values are shown, not edited: qatrack_core's JSONField has no form field
    # of its own, so the form would show them as Python text and save that text back
    # as a plain string, which Perform QC can no longer recover.
    exclude = ("data",)
    readonly_fields = ("saved_data",)
    qc_wide_fields = ("saved_data",)

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.select_related(
            "created_by", "modified_by", "unit_test_collection", "unit_test_collection__unit", "test_list"
        )

    @admin.display(description=_l("Unit"), ordering="unit_test_collection__unit__name")
    def unit(self, obj):
        return obj.unit_test_collection.unit.name

    @staticmethod
    def recover_url(obj):
        """The Perform QC page with this auto save loaded, built as that page's own "Auto
        Saved Sessions" menu builds it: on the saved cycle day, and through Continue for a
        session that was already in progress."""
        if obj.test_list_instance_id:
            base = reverse("continue_tli", kwargs={'pk': obj.test_list_instance_id})
        else:
            base = reverse("perform_qa", kwargs={'pk': obj.unit_test_collection_id})
        return base + "?autosave_id=%d&day=%d" % (obj.pk, obj.day + 1)

    @admin.display(description=_l("Saved Data"))
    def saved_data(self, obj):
        """The auto save's values as indented JSON, read-only."""
        if obj is None or obj.data in (None, "", {}, []):
            return format_html('<span class="qc-empty">{}</span>', _("Nothing saved yet"))
        text = json.dumps(obj.data, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        return format_html('<pre class="qcas-data">{}</pre>', text)

    @admin.display(description=_l("Recover"))
    def recover(self, obj):
        # A small button-style link (styled in admin/qa/autosave/change_list.html).
        return format_html(
            '<a href="{}" class="qcas-recover-btn" title="{}"><i class="fa fa-undo" aria-hidden="true"></i> {}</a>',
            self.recover_url(obj),
            _("Click to continue this auto saved session"),
            _("Recover"),
        )

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        """Context for the summary card in admin/qa/autosave/change_form.html."""
        if obj is not None and obj.pk:
            context["qcas_summary"] = autosave_summary(obj)
            context["qcas_recover_url"] = self.recover_url(obj)
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)


def autosave_summary(autosave):
    """What an auto save holds, counted from its data ({"tests": {slug: value}, "skips",
    "comments", "tli_comment"}, as qa.views.perform.autosave saves it): how many tests
    have a value, how many were skipped and how many have a comment."""
    data = autosave.data if isinstance(autosave.data, dict) else {}

    def count(key, test):
        values = data.get(key)
        return sum(1 for v in values.values() if test(v)) if isinstance(values, dict) else 0

    return {
        "values": count("tests", lambda v: v not in (None, "")),
        "skips": count("skips", bool),
        "comments": count("comments", lambda v: bool(v and str(v).strip())),
        "has_tli_comment": bool(str(data.get("tli_comment") or "").strip()),
    }


admin.site.register([models.Tolerance], ToleranceAdmin)
admin.site.register([models.AutoReviewRule], AutoReviewAdmin)
admin.site.register([models.AutoReviewRuleSet], AutoReviewRuleSetAdmin)
admin.site.register([models.AutoSave], AutoSaveAdmin)
admin.site.register([models.Category], CategoryAdmin)
admin.site.register([models.TestList], TestListAdmin)
admin.site.register([models.Test], TestAdmin)
admin.site.register([models.UnitTestInfo], UnitTestInfoAdmin)
admin.site.register([models.UnitTestCollection], UnitTestCollectionAdmin)

admin.site.register([models.TestListCycle], TestListCycleAdmin)
admin.site.register([models.Frequency], FrequencyAdmin)
admin.site.register([models.TestInstanceStatus], StatusAdmin)
admin.site.register([models.TestInstance], TestInstanceAdmin)
admin.site.register([models.TestListInstance], TestListInstanceAdmin)
