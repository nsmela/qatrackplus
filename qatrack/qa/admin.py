import json
import re

from django import VERSION, forms
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers, options, widgets
from django.contrib.admin.helpers import flatten_fieldsets
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
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
from django.utils.translation import pgettext
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


class CategoryAdmin(DjangoMpttAdmin):
    """QC categories admin"""
    prepopulated_fields = {
        'slug': ('name',)
    }
    list_display = (
        "name",
        "get_description",
    )

    def get_description(self, obj):
        """Just used to disable ordering by description"""
        return obj.description if obj else ""

    get_description.short_name = _l("Description")


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

        for field in readonly:
            self.fields[field].widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()

        if not self.instance or not self.instance.test:
            return cleaned_data

        reference_value = cleaned_data.get("reference_value", "")
        tolerance = cleaned_data.get("tolerance")

        # Validate percent tolerance requires numerical reference
        if tolerance and tolerance.type == models.PERCENT:
            if not reference_value:
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
                if reference_value:
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

    def _reference_for_validation(self):
        """The reference save() is about to attach, as an unsaved Reference (or None).

        Returns _KEEP_REFERENCE when save() leaves the stored reference alone.
        Only the value matters here: it's what UnitTestInfo.clean checks.
        """
        if 'reference_value' not in self.cleaned_data:
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

        if reference_value is not None and reference_value != '':  # Non-empty reference value
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
        elif 'reference_value' in self.cleaned_data:
            # reference_value field was in the form but empty - clear the reference
            instance.reference = None

        if commit:
            instance.save()
        return instance


def record_unit_test_info_change(uti, old_reference, old_tolerance, comment, user, changed_fields):
    """Add a history entry (UnitTestInfoChange) for a reference/tolerance change.

    Shared by the UnitTestInfo admin page and the test list builder's Reference
    and Tolerance dialog, so both keep the same history. ``changed_fields`` is the
    form's ``changed_data``; nothing is recorded unless the comment, reference or
    tolerance was touched. Returns the new entry, or None.
    """
    if not uti or not uti.pk:
        return None
    if not any(k in changed_fields for k in ('comment', 'reference_value', 'tolerance')):
        return None
    return models.UnitTestInfoChange.objects.create(
        unit_test_info=uti,
        comment=comment,
        reference=old_reference,
        reference_changed=old_reference != uti.reference,
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


class SetMultipleReferencesAndTolerancesForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    contenttype = forms.CharField(widget=forms.HiddenInput, required=False)
    tolerance = forms.ModelChoiceField(
        queryset=models.Tolerance.objects.all(),
        required=False,
        empty_label=_("No Tolerance Set"),
    )
    reference = forms.FloatField(required=False)
    comment = forms.CharField(
        label=_l("Comment"),
        widget=forms.Textarea,
        required=False,
        help_text=_("Include an optional comment about why these references/tolerances are being updated")
    )


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


class UnitTestInfoAdmin(BaseQATrackAdmin):
    """Admin interface for UnitTestInfo model"""

    change_list_template = "admin/qa/unittestinfo/change_list.html"
    form = UnitTestInfoForm

    fieldsets = (
        (None, {
            'fields': (
                'unit',
                'test',
                'reference_display',
                'tolerance',
            )
        }),
        (
            _('Reference Value'), {
                'fields': (
                    'test_type',
                    'reference_value',
                    'reference_set_by',
                    'reference_set',
                    'comment',
                ),
            }
        ),
        (_('History'), {
            'fields': ('history',),
        }),
    )

    list_display = [test_name, "unit", test_type, "reference_display", "tolerance"]
    list_filter = [
        ActiveUnitTestInfoFilter, "unit__site", "unit", "test__category", "test__testlistmembership__test_list"
    ]
    # "reference" stays read-only (so the form never edits it) though the page
    # shows reference_display, which reads Yes/No for Boolean tests.
    readonly_fields = ("reference", "reference_display", "test", "unit", "history")
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
        even for older references stored with the numerical type.
        """
        if obj is None or obj.reference is None:
            return None
        return obj.reference.value_display(obj.test)

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
            # a new Reference object is created on every save, so only call it a
            # change when the flag is set *and* the displayed value differs
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

    @admin.action(description=_("Set references and tolerances for selected tests"))
    def set_multiple_references_and_tolerances(self, request, queryset):
        """Set references and tolerances for multiple UnitTestInfo objects"""
        if request.POST.get('post') == 'yes':
            tolerance_id = request.POST.get('tolerance')
            reference_value = request.POST.get('reference')

            if tolerance_id:
                try:
                    tolerance = models.Tolerance.objects.get(pk=tolerance_id)
                except models.Tolerance.DoesNotExist:
                    self.message_user(request, _("Invalid tolerance selected"), level=messages.ERROR)
                    return None
            else:
                tolerance = None

            # Check if all tests are of the same type
            test_types = set(uti.test.type for uti in queryset)
            if len(test_types) > 1:
                self.message_user(
                    request,
                    _("Cannot set the same reference value for tests of different types"),
                    level=messages.ERROR
                )
                return None

            test_type = test_types.pop() if test_types else None

            # Check for incompatible tolerance/test type combinations
            if test_type and tolerance:
                incompatible = False

                # Boolean tests can only use boolean tolerances
                if test_type == models.BOOLEAN and tolerance.type != models.BOOLEAN:
                    incompatible = True
                # Multiple choice tests can only use multiple choice tolerances
                elif test_type == models.MULTIPLE_CHOICE and tolerance.type != models.MULTIPLE_CHOICE:
                    incompatible = True
                # Boolean/MC tolerances can only be used with their respective test types
                elif tolerance.type == models.BOOLEAN and test_type != models.BOOLEAN:
                    incompatible = True
                elif tolerance.type == models.MULTIPLE_CHOICE and test_type != models.MULTIPLE_CHOICE:
                    incompatible = True

                if incompatible:
                    self.message_user(
                        request, _("The selected tolerance is not compatible with the test type"), level=messages.ERROR
                    )
                    return None

            for uti in queryset:
                changed = False

                if tolerance:
                    uti.tolerance = tolerance
                    changed = True

                if reference_value:
                    if uti.test.type == models.BOOLEAN:
                        try:
                            value = bool(int(reference_value))
                        except (ValueError, TypeError):
                            self.message_user(request, _("Invalid boolean value"), level=messages.ERROR)
                            return None
                    elif uti.test.type == models.MULTIPLE_CHOICE:
                        if not uti.test.choices or reference_value not in uti.test.choices.split(","):
                            self.message_user(
                                request, _("Invalid choice for multiple choice test"), level=messages.ERROR
                            )
                            return None
                        value = reference_value
                    else:
                        try:
                            # For numerical tests, convert to float since the test expects float values
                            value = float(reference_value)
                        except (ValueError, TypeError):
                            self.message_user(request, _("Invalid numerical value"), level=messages.ERROR)
                            return None

                    ref = models.Reference(
                        value=value,
                        name=str(value),
                        type=models.BOOLEAN if uti.test.type == models.BOOLEAN else models.NUMERICAL,
                        created_by=request.user,
                        modified_by=request.user,
                    )
                    ref.save()
                    uti.reference = ref
                    changed = True

                if changed:
                    uti.save()

            self.message_user(request, _("Successfully updated references and tolerances"))
            return None

        context = {
            'title': _("Set references and tolerances"),
            'queryset': queryset,
            'opts': self.model._meta,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, 'admin/qa/unittestinfo/set_multiple.html', context)

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

    def _posted_ids(self, prefix, field):
        """Return the ids posted in `<prefix>-<n>-<field>`, leaving out rows marked for removal.

        A row the user removed in the builder is still posted (with its DELETE
        box ticked) so Django can delete it; it must not count towards the
        duplicate-name and maximum-size checks.
        """
        pattern = re.compile(r"^%s-(\d+)-%s$" % (re.escape(prefix), re.escape(field)))
        ids = []
        for key, value in self.data.items():
            match = pattern.match(key)
            if match and value and not _posted_delete(self.data, "%s-%s" % (prefix, match.group(1))):
                ids.append(value)
        return ids

    def clean(self):
        test_ids = self._posted_ids("testlistmembership_set", "test")
        # (macro name, test name) for every test, direct or through a sublist
        tests = list(models.Test.objects.filter(id__in=test_ids).values_list("slug", "name"))

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

    # Categories and types are drawn with one neutral pill / badge style
    # (.tl-cat-pill, .tl-type-badge): colour in QATrack+ means QC status, so
    # it isn't used to tell categories or test types apart.

    # Badges are short type abbreviations shown in the builder; the context
    # tells translators to keep them short.
    t = test.type
    if t == models.BOOLEAN:
        type_badge = pgettext("test type badge", "Y/N")
        type_label = _("Boolean")
    elif t in (models.SIMPLE, models.NUMERICAL):
        type_badge = pgettext("test type badge", "Num")
        type_label = _("Numerical")
    elif t == models.WRAPAROUND:
        type_badge = pgettext("test type badge", "Num")
        type_label = _("Wraparound")
    elif t == models.MULTIPLE_CHOICE:
        type_badge = pgettext("test type badge", "M/C")
        type_label = _("Multiple Choice")
    elif t == models.COMPOSITE:
        type_badge = pgettext("test type badge", "Comp")
        type_label = _("Composite")
    elif t == models.CONSTANT:
        type_badge = pgettext("test type badge", "Const")
        type_label = _("Constant")
    elif t == models.STRING:
        type_badge = pgettext("test type badge", "Text")
        type_label = _("String")
    elif t == models.STRING_COMPOSITE:
        type_badge = pgettext("test type badge", "JSON")
        type_label = _("String Composite")
    elif t == models.UPLOAD:
        type_badge = pgettext("test type badge", "File")
        type_label = _("File Upload")
    elif t in (models.DATE, models.DATETIME):
        type_badge = pgettext("test type badge", "Date")
        type_label = _("Date") if t == models.DATE else _("Date & Time")
    else:
        type_badge = pgettext("test type badge", "Test")
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
        "type_badge": type_badge,
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


class TestListMembershipForm(forms.ModelForm):

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


class SublistForm(forms.ModelForm):

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
        return super().get_formset(request, obj, **kwargs)


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


class ActiveTestListFilter(admin.SimpleListFilter):

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


class UnitTestListFilter(admin.SimpleListFilter):

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


class SiteTestListFilter(admin.SimpleListFilter):

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


class FrequencyTestListFilter(admin.SimpleListFilter):

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


class CategoryTestListFilter(admin.SimpleListFilter):
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
    })


def testlist_test_desc_modal(request):
    """HTMX endpoint to view or update a test's description.

    This saves the Test straight away (not when the test list is saved), so it
    needs the same permission as editing the Test itself, not just staff access.
    """
    if not request.user.has_perm("qa.change_test"):
        return HttpResponseForbidden(_("You don't have permission to change tests. Nothing was changed."))
    test_id = request.GET.get("test_id") or request.POST.get("test_id")
    index = request.GET.get("index", "0")
    test = get_object_or_404(models.Test.objects.select_related("category"), pk=test_id)
    if request.method == "POST":
        desc = request.POST.get("description", "")
        # Browsers send textarea line breaks as \r\n, so compare with line
        # endings normalized: re-saving an untouched description isn't a change.
        if desc.replace("\r\n", "\n") != (test.description or "").replace("\r\n", "\n"):
            test.description = desc
            test.modified_by = request.user
            with transaction.atomic():
                # Only these fields, so a stale in-memory Test can't overwrite
                # other fields. "modified" is auto_now, which Django only
                # refreshes when it's listed in update_fields.
                test.save(update_fields=["description", "modified", "modified_by"])
                LogEntry.objects.log_action(
                    user_id=request.user.pk,
                    content_type_id=ContentType.objects.get_for_model(test).pk,
                    object_id=test.pk,
                    object_repr=str(test),
                    action_flag=CHANGE,
                    change_message=_("Changed description from the test list builder."),
                )
        test_meta = get_test_metadata(test)
        return render(request, "admin/qa/testlist/partials/_test_desc_cell.html", {
            "test_meta": test_meta,
            "index": index,
        })
    return render(request, "admin/qa/testlist/partials/_test_desc_modal.html", {
        "test": test,
        "test_meta": get_test_metadata(test),
        "index": index,
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


@transaction.atomic
def testlist_duplicate_test(request):
    """HTMX / AJAX endpoint to duplicate a Test object, prompting user for new name and copying type, category, calculation, and unit references/tolerances.

    The new Test is created immediately, so this needs permission to add tests.
    References and tolerances are only copied for users who can change them
    (``qa.change_unittestinfo``); otherwise the new test starts without any.
    Atomic so a failure while copying never leaves a half-made test behind.
    """
    can_copy_refs_tols = request.user.has_perm("qa.change_unittestinfo")
    if not request.user.has_perm("qa.add_test"):
        return HttpResponseForbidden(_("You don't have permission to add tests. No test was created."))
    source_test_id = request.GET.get("test_id") or request.POST.get("source_test_id")
    source = get_object_or_404(models.Test.objects.select_related("category"), pk=source_test_id)

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
    saved value reads exactly as it does after a reload.
    """
    return {
        "reference": _machine_reference_display(uti.test, uti.reference),
        "tolerance": str(uti.tolerance) if uti.tolerance_id else None,
    }


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
        self.fields["tolerance"].label = _("Tolerance")
        self.fields["tolerance"].empty_label = _("No tolerance")
        self.fields["comment"].label = _("Comment")
        self.fields["comment"].help_text = _("Why are you changing this? Saved with the history.")
        self.fields["comment"].widget.attrs.update({"rows": 3, "class": "tl-modal-textarea"})
        for name in ("reference_value", "tolerance"):
            widget = self.fields[name].widget
            if not isinstance(widget, forms.HiddenInput):
                widget.attrs["class"] = "tl-modal-input"

    def _reference_for_validation(self):
        # matches save(): an unchanged value keeps the current Reference
        if "reference_value" not in self.changed_data:
            return self._KEEP_REFERENCE
        return super()._reference_for_validation()

    def save(self, commit=True):
        if "reference_value" not in self.changed_data:
            # Unchanged: keep the current Reference (UnitTestInfoForm.save would
            # save a new one with the same value, or clear it when blank).
            self.cleaned_data.pop("reference_value", None)
        return super().save(commit=commit)


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
            fresh = models.UnitTestInfo.objects.select_related("test", "reference", "tolerance").get(pk=uti.pk)
            data = machine_values_display(fresh)
            data.update({
                "ok": True,
                "uti_id": fresh.pk,
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


class TestListAdmin(SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

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
        "col_tests",
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
                'test-desc-modal/',
                self.admin_site.admin_view(testlist_test_desc_modal),
                name='qa_testlist_test_desc_modal',
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
        qs = qs.annotate(test_count=Count("testlistmembership", distinct=True))
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

    @admin.display(description=_l("Tests"), ordering="test_count")
    def col_tests(self, obj):
        return format_html('<span class="tl-count-badge">{}</span>', obj.test_count)

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

    @admin.display(description=_l("Modified"), ordering="modified")
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


class TestForm(forms.ModelForm):

    class Meta:
        model = models.Test
        fields = "__all__"

    def clean(self):
        """if test already has some history don't allow for the test type to be changed"""

        cleaned_data = super().clean()

        test_type = cleaned_data.get("type")
        user_changing_type = self.instance.type != test_type
        has_history = models.TestInstance.objects.filter(unit_test_info__test=self.instance).exists()
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


class TestAdmin(SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

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
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "js/test_admin.js",
            "js/admin_description_editor.js",
            "ace/ace.js",
            "select2/js/select2.js",
        )
        css = {
            'all': (
                "qatrack_core/css/admin.css",
                "select2/css/select2.css",
            ),
        }

    def save_model(self, request, obj, form, change):
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
)
def assigned_to_name(obj):
    return obj.assigned_to.name


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


class UnitTestCollectionAdmin(BaseQATrackAdmin):
    # readonly_fields = ("unit","frequency",)
    filter_horizontal = ("visible_to",)
    list_display = ['name', site_name, unit_name, freq_name, assigned_to_name, 'get_content_type', "active"]
    list_filter = [SiteFilter, UnitFilter, FrequencyFilter, AssignedToFilter, ActiveFilter]
    search_fields = ['name', "unit__name", "frequency__name"]
    change_form_template = "admin/treenav/menuitem/change_form.html"
    list_editable = ["active"]
    save_as = True
    form = UnitTestCollectionForm

    class Media:
        js = (
            'jquery/js/jquery.min.js',
            "js/jquery-ui.init.js",
            "js/jquery-ui.min.js",
            "js/select2.min.js",
        )

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.select_related("unit", "unit__site", "frequency", "assigned_to", "content_type")

    @admin.display(
        description=_l("Content Type"),
        ordering="content_type__model",
    )
    def get_content_type(self, obj):
        if obj:
            return obj.content_type.model_class().__name__
        return _("Unknown")


class TestListCycleMembershipInline(DynamicRawIDMixin, admin.TabularInline):

    model = models.TestListCycleMembership
    dynamic_raw_id_fields = ("test_list",)


class TestListCycleAdmin(SaveUserMixin, SaveInlineAttachmentUserMixin, BaseQATrackAdmin):
    """Admin for daily test list cycles"""
    inlines = [TestListCycleMembershipInline, get_attachment_inline("testlistcycle")]
    prepopulated_fields = {
        'slug': ('name',)
    }
    search_fields = (
        "name",
        "slug",
    )
    list_display = ["name", "all_lists"]

    class Media:
        js = (
            'admin/js/jquery.init.js',
            'jquery/js/jquery.min.js',
            "js/jquery-ui.init.js",
            "js/jquery-ui.min.js",
            "js/collapsed_stacked_inlines.js",
            "js/m2m_drag_admin.js",
            "js/admin_description_editor.js",
            "ace/ace.js",
        )

    def all_lists(self, obj):
        return ', '.join("%s: %s" % x for x in enumerate(obj.all_lists().values_list("name", flat=True)))

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("test_lists")


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


class FrequencyAdmin(BaseQATrackAdmin):
    prepopulated_fields = {
        'slug': ('name',)
    }
    form = FrequencyForm
    fields = (
        "name",
        "slug",
        "window_start",
        "window_end",
        "recurrences",
    )

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
        )
        css = {
            'all': ["cal-heatmap/css/cal-heatmap.css"],
        }

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


class StatusAdmin(BaseQATrackAdmin):
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

    @admin.display(description=_l("Color"))
    @mark_safe
    def get_colour(self, obj):
        return '<div style="display: inline-block; width: 20px; height:20px; background-color: %s;"></div>' % obj.colour


@admin.display(
    description=_l("Unit"),
    ordering="unit_test_collection__unit__name",
)
def utc_unit_name(obj):
    return obj.unit_test_collection.unit.name


class TestListInstanceAdmin(SaveInlineAttachmentUserMixin, BaseQATrackAdmin):
    list_display = ["__str__", utc_unit_name, "test_list", "work_completed", "created_by"]
    list_filter = [
        "unit_test_collection__unit",
        "test_list",
    ]
    inlines = [get_attachment_inline("testlistinstance")]

    def render_delete_form(self, request, context):
        instance = context['object']

        # Find related Service events with rtsqa and with initiated by
        ServiceEvent = apps.get_model('service_log', 'ServiceEvent')
        ServiceEventStatus = apps.get_model('service_log', 'ServiceEventStatus')
        se_rtsqa_qs = ServiceEvent.objects.filter(returntoserviceqa__test_list_instance=context['object'])
        se_ib_qs = instance.serviceevents_initiated.all()
        default_ses = ServiceEventStatus.get_default()
        context.update({'se_rtsqa_qs': se_rtsqa_qs, 'se_ib_qs': se_ib_qs, 'default_ses': default_ses})
        return super().render_delete_form(request, context)

    def has_add_permission(self, request):
        """testlistinstancess are created via front end only"""
        return False


class TestInstanceAdmin(SaveInlineAttachmentUserMixin, BaseQATrackAdmin):

    list_display = [
        "__str__",
        "test_list_instance",
        "test_name",
        "unit_name",
        "test_list_name",
        "work_completed",
        "created_by",
    ]
    inlines = [get_attachment_inline("testinstance")]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "test_list_instance", "test_list_instance__test_list", "unit_test_info", "unit_test_info__test",
            "created_by"
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
                "label": str(tol),
                "message": _("Created %(tolerance)s.") % {"tolerance": tol},
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


class ToleranceAdmin(BasicSaveUserAdmin):
    form = ToleranceForm
    list_filter = ["type"]

    class Media:
        js = (
            "admin/js/jquery.init.js",
            'jquery/js/jquery.min.js',
            "js/tolerance_admin.js",
        )

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.exclude(type=models.BOOLEAN)

    def has_change_permission(self, request, obj=None):

        if obj and obj.type == models.BOOLEAN:
            return False
        return super().has_change_permission(request, obj)


class AutoReviewAdmin(BaseQATrackAdmin):
    list_display = (str, "pass_fail", "status")
    list_editable = ["pass_fail", "status"]


class AutoReviewRuleSetAdminForm(forms.ModelForm):

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


class AutoReviewRuleSetAdmin(BaseQATrackAdmin):
    list_display = ("__str__", "is_default", 'get_rules_display')

    filter_horizontal = ("rules",)

    form = AutoReviewRuleSetAdminForm

    @admin.display(description=_l("Rules"))
    @mark_safe
    def get_rules_display(self, obj):
        return "<br>".join(str(rule) for rule in obj.rules.all().order_by('pass_fail'))


class AutoSaveAdmin(BaseQATrackAdmin):
    list_display = (
        "created", "created_by", 'modified', 'modified_by', 'unit', 'unit_test_collection', 'test_list', 'recover'
    )

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        return qs.select_related(
            "created_by", "modified_by", "unit_test_collection", "unit_test_collection__unit", "test_list"
        )

    def unit(self, obj):
        return obj.unit_test_collection.unit.name

    @mark_safe
    def recover(self, obj):
        href = reverse("perform_qa", kwargs={'pk': obj.unit_test_collection_id}) + "?autosave_id=%d" % obj.pk
        title = _("Click to continue this auto saved session")
        return '<a href="%s" title="%s">%s</a>' % (href, title, _("Recover"))


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
