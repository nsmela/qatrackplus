import json

from braces.views import PermissionRequiredMixin
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.context_processors import PermWrapper
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.db.transaction import atomic
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.template.defaultfilters import truncatechars
from django.template.loader import get_template, render_to_string
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, UpdateView, View
from django_comments.models import Comment
from listable.views import (
    DATE_RANGE,
    LAST_14_DAYS,
    NONEORNULL,
    SELECT_MULTI,
    TEXT,
    THIS_MONTH,
    THIS_WEEK,
    THIS_YEAR,
    TODAY,
    YESTERDAY,
    BaseListableView,
)

from qatrack.attachments.models import Attachment
from qatrack.faults import forms, models
from qatrack.qa.views.perform import ChooseUnit
from qatrack.qatrack_core.serializers import QATrackJSONEncoder
from qatrack.service_log import models as sl_models
from qatrack.units.models import Unit

SECTION_FIELDS = {
    "occurrence": ["occurred", "unit", "modality"],
    "fault-types": ["fault_types_field"],
    "related-ses": ["related_service_events"],
    "attachments": ["attachments", "attachments_delete_ids"],
}

# A fault type created from the details page can be given a description before
# the section is saved. It travels with the section form in a field named with
# this prefix followed by the new code.
NEW_FAULT_TYPE_DESC_PREFIX = "new_fault_type_desc-"


def section_form_class(section):
    keep = set(SECTION_FIELDS[section])

    class _SectionForm(forms.FaultForm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            for name in list(self.fields):
                if name not in keep:
                    self.fields.pop(name, None)

    return _SectionForm


def section_template(section):
    return "faults/sections/_section_%s.html" % section.replace("-", "_")


def save_section(section, form, request):
    fault = form.save(commit=False)
    fault.modified_by = request.user
    fault.save()

    if section == "fault-types":
        _save_fault_types(fault, form)
        _save_new_fault_type_descriptions(request)
    elif section == "related-ses":
        _save_related_ses(fault, form)
    elif section == "attachments":
        _save_attachments(fault, request)

    return fault


def _save_new_fault_type_descriptions(request):
    """Give fault types created from the details page the description the user
    typed for them. Only blank descriptions are filled in, so a type someone
    else created in the meantime keeps its own description."""
    marker = forms.NEW_FAULT_TYPE_MARKER
    for value in request.POST.getlist("fault-fault_types_field"):
        if not value.startswith(marker):
            continue
        code = value[len(marker):]
        description = request.POST.get(NEW_FAULT_TYPE_DESC_PREFIX + code, "").strip()
        if description:
            models.FaultType.objects.filter(code__iexact=code, description="").update(description=description)


def fault_type_row(fault_type=None, new_code=None, new_description=""):
    """One row of the fault types table. New codes don't exist yet, so rows are
    plain dicts rather than FaultType instances."""
    if fault_type is not None:
        return {
            "code": fault_type.code,
            "slug": fault_type.slug,
            "description": fault_type.description,
            "value": fault_type.code,
            "is_new": False,
        }
    return {
        "code": new_code,
        "slug": "",
        "description": new_description,
        "value": forms.NEW_FAULT_TYPE_MARKER + new_code,
        "is_new": True,
    }


def fault_type_rows(fault, form=None):
    """Rows for the fault types section: what the user posted when a bound form
    is being redisplayed, otherwise what is saved on the fault."""
    if form is None or not form.is_bound:
        return [fault_type_row(ft) for ft in fault.fault_types.order_by("code")]

    marker = forms.NEW_FAULT_TYPE_MARKER
    values = form.data.getlist("fault-fault_types_field")
    existing = {
        ft.code: ft for ft in models.FaultType.objects.filter(code__in=[v for v in values if not v.startswith(marker)])
    }
    rows = []
    for value in values:
        if value.startswith(marker):
            code = value[len(marker):]
            desc = form.data.get(NEW_FAULT_TYPE_DESC_PREFIX + code, "")
            rows.append(fault_type_row(new_code=code, new_description=desc))
        elif value in existing:
            rows.append(fault_type_row(existing[value]))
    return rows


def related_service_events(fault, form=None):
    """Service events for the related SEs section, newest first."""
    if form is not None and form.is_bound:
        ids = [v for v in form.data.getlist("fault-related_service_events") if v.isdigit()]
        qs = sl_models.ServiceEvent.objects.filter(pk__in=ids)
    else:
        qs = fault.related_service_events.all()
    return qs.select_related("service_status").order_by("-id")


def section_context(fault, section, form=None, editing=False, saved=False):
    context = {"fault": fault, "editing": editing, "saved": saved}
    if form is not None:
        context["form"] = form

    if section == "fault-types":
        context["fault_type_rows"] = fault_type_rows(fault, form if editing else None)
    elif section == "related-ses":
        context["service_events"] = related_service_events(fault, form if editing else None)
    elif section == "attachments":
        context["attachments"] = fault.attachment_set.all()
    elif section == "occurrence" and editing:
        # Lets the edit partial limit the modality choices to the chosen unit
        # without asking the server for unit information.
        context["unit_modalities"] = {
            str(unit.pk): [m.pk for m in unit.modalities.all()]
            for unit in Unit.objects.prefetch_related("modalities")
        }

    return context


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


class FaultSectionMixin(PermissionRequiredMixin):
    raise_exception = True
    permission_required = "faults.change_fault"

    def dispatch(self, request, *args, **kwargs):
        # The section name ends up in a template path, so only known sections
        # get that far.
        if kwargs.get("section") not in SECTION_FIELDS:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_fault(self):
        qs = models.Fault.objects.select_related(
            "created_by", "modified_by"
        ).prefetch_related("faultreviewinstance_set", "fault_types")
        return get_object_or_404(qs, pk=self.kwargs['pk'])

    def render_section(self, fault, status=200, **kwargs):
        section = self.kwargs["section"]
        context = section_context(fault, section, **kwargs)
        return render(self.request, section_template(section), context, status=status)


class FaultSectionDetail(FaultSectionMixin, View):

    def get(self, request, pk, section):
        return self.render_section(self.get_fault())


class FaultSectionEdit(FaultSectionMixin, View):

    def get(self, request, pk, section):
        fault = self.get_fault()
        form = section_form_class(section)(instance=fault, user=request.user)
        return self.render_section(fault, form=form, editing=True)

    def post(self, request, pk, section):
        fault = self.get_fault()
        form = section_form_class(section)(request.POST, request.FILES, instance=fault, user=request.user)

        if not form.is_valid():
            # 422 so htmx callers (and tests) can tell a rejected save from a
            # successful one; site_base.html lets htmx swap it in to show the errors.
            return self.render_section(fault, status=422, form=form, editing=True)

        save_section(section, form, request)
        fault = self.get_fault()
        response = self.render_section(fault, saved=True)
        response.content += render_to_string(
            "faults/sections/_last_modified_oob.html", {"fault": fault}, request=self.request,
        ).encode("utf-8")
        return response


class FaultList(BaseListableView):

    model = models.Fault
    template_name = 'faults/fault_list.html'
    paginate_by = 50

    kwarg_filters = None

    headers = {
        'actions': _l('Actions'),
        'get_id': _l('ID'),
        'get_fault_types': _l("Fault Types"),
        'unit__site__name': _l("Site"),
        'unit__name': _l("Unit"),
        'modality__name': _l("Modality"),
        'get_occurred': _l("Occurred On"),
    }

    widgets = {
        'actions': None,
        'get_id': TEXT,
        'get_fault_types': TEXT,
        'unit__site__name': SELECT_MULTI,
        'unit__name': SELECT_MULTI,
        'modality__name': SELECT_MULTI,
        'get_occurred': DATE_RANGE,
        'review_status': DATE_RANGE,
    }

    search_fields = {
        'actions': False,
        'review_status': 'faultreviewinstance__reviewed',
        'get_fault_types': 'fault_types__code',
        'get_occurred': 'occurred',
        'get_id': 'id',
    }

    order_fields = {
        'actions': False,
        'review_status': 'faultreviewinstance__reviewed',
        'get_fault_types': 'fault_types__code',
        'get_occurred': 'occurred',
    }

    date_ranges = {
        "occurred": [TODAY, YESTERDAY, THIS_WEEK, LAST_14_DAYS, THIS_MONTH, THIS_YEAR],
        "review_status": [TODAY, YESTERDAY, THIS_WEEK, LAST_14_DAYS, THIS_MONTH, THIS_YEAR],
    }

    select_related = [
        "unit__site",
        "unit",
        "modality",
        "created_by",
        "modified_by",
    ]

    prefetch_related = [
        "fault_types",
        "faultreviewinstance_set",
        "faultreviewinstance_set__reviewed_by",
        "faultreviewinstance_set__fault_review_group__group",
        "comments",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Store templates on view initialization so we don't have to reload them for every row!
        self.templates = {
            'actions': get_template('faults/fault_actions.html'),
            'occurred': get_template("faults/fault_occurred.html"),
            'review_status': get_template("faults/fault_review_status.html"),
            'fault_types': get_template("faults/fault_types.html"),
        }

    def get_queryset(self):
        return super().get_queryset().annotate(
            review_count=Max("faultreviewinstance"),
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        current_url = resolve(self.request.path_info).url_name
        context['icon'] = 'fa-exclamation-triangle'
        context['view_name'] = current_url
        context['page_title'] = _l("All Faults")
        return context

    def get_fields(self, request=None):

        fields = (
            "actions",
            "id",
            "get_occurred",
            "get_fault_types",
        )

        multiple_sites = len(set(Unit.objects.values_list("site_id"))) > 1
        if multiple_sites:
            fields += ("unit__site__name",)

        fields += (
            "unit__name",
            "modality__name",
            "review_status",
        )
        return fields

    def get_filters(self, field, queryset=None):

        filters = super().get_filters(field, queryset=queryset)

        if field == 'unit__site__name':
            filters = [(NONEORNULL, _("Other")) if f == (NONEORNULL, 'None') else f for f in filters]

        return filters

    def actions(self, fault):
        c = {
            'fault': fault,
            'next': reverse('fault_list'),
            'perms': PermWrapper(self.request.user),
        }
        return self.templates['actions'].render(c)

    def review_status(self, fault):
        c = {
            'fault': fault,
            'comments': fault.comments.count(),
        }
        return self.templates['review_status'].render(c)

    def get_occurred(self, fault):
        c = {'fault': fault}
        return self.templates['occurred'].render(c)

    def get_fault_types(self, fault):
        c = {'fault': fault}
        return self.templates['fault_types'].render(c)

    def get_fault_types_descriptions(self, fault):
        c = {'fault': fault}
        return self.templates['fault_types_descriptions'].render(c)


class UnreviewedFaultList(FaultList):

    headers = FaultList.headers
    headers["selected"] = mark_safe(
        '<input type="checkbox" class="test-selected-toggle" title="%s"/>' % _("Select All")
    )
    search_fields = FaultList.search_fields
    search_fields["selected"] = False
    order_fields = FaultList.order_fields
    order_fields['selected'] = False

    def get_queryset(self):
        return super().get_queryset().filter(review_count=None)

    def get_fields(self, request=None):
        fields = super().get_fields(request=request)
        if settings.REVIEW_BULK:
            fields += ("selected",)

        return fields

    def selected(self, obj):
        return mark_safe('<input type="checkbox" class="test-selected" data-fault="%s" title="%s"/>' % (
            obj.id,
            _("Check to include this fault bulk setting approval statuses"),
        ))

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['page_title'] = _l("Unreviewed Faults")
        context['bulk_review'] = settings.REVIEW_BULK
        return context


class CreateFault(PermissionRequiredMixin, CreateView):

    model = models.Fault
    template_name = 'faults/fault_form.html'
    form_class = forms.FaultForm

    permission_required = "faults.add_fault"
    raise_exception = True

    def get_form_kwargs(self):
        """Add user to form kwargs"""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    @atomic
    def form_valid(self, form):

        context = self.get_context_data()
        reviews_valid = all(f.is_valid() for f in context['review_forms'])
        if not reviews_valid:
            return self.render_to_response(context)

        fault = save_valid_fault_form(form, self.request)
        save_valid_review_forms(context['review_forms'], fault)

        return HttpResponseRedirect(reverse('fault_list'))

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data['status_tag_colours'] = sl_models.ServiceEventStatus.get_colour_dict()
        if self.request.method == 'POST':
            data_key = "%s-related_service_events" % context_data['form'].prefix
            qs = sl_models.ServiceEvent.objects.filter(pk__in=self.request.POST.getlist(data_key))
            context_data['se_statuses'] = {se.id: se.service_status.id for se in qs}
        else:
            context_data['se_statuses'] = {}

        context_data['se_statuses_json'] = json.dumps(context_data['se_statuses'])
        units_choices = [{'id': str(k), 'text': str(v)} for k, v in context_data['form'].fields['unit'].choices]
        context_data['units_json'] = json.dumps(units_choices)
        
        modality_choices = [{'id': str(k), 'text': str(v)} for k, v in context_data['form'].fields['modality'].choices]
        context_data['modalities_json'] = json.dumps(modality_choices)
        
        context_data['fault_json'] = 'null'
        if context_data['form'].errors:
            context_data['form_errors_json'] = context_data['form'].errors.as_json()
        else:
            context_data['form_errors_json'] = '{}'

        frgs = models.FaultReviewGroup.objects.order_by("-required", "group__name")
        context_data['review_forms'] = []
        for idx, frg in enumerate(frgs):
            prefix = "review-form-%d" % idx
            data = self.request.POST if self.request.method == "POST" else None
            frg_form = forms.InlineReviewForm(data, fault_review_group=frg, prefix=prefix)
            context_data['review_forms'].append(frg_form)
            
        review_errors = {f.prefix: f.errors.get_json_data() for f in context_data['review_forms'] if f.errors}
        context_data['review_errors_json'] = json.dumps(review_errors)
        
        review_forms_data = []
        for f in context_data['review_forms']:
            review_forms_data.append({
                'prefix': f.prefix,
                'group_name': f.fields['group'].initial,
                'required': f.fields['reviewed_by'].required,
                'users': [{'id': u.id, 'name': u.get_full_name() or u.username} for u in f.fields['reviewed_by'].queryset],
                'selected': f.data.get(f.prefix + '-reviewed_by') if f.is_bound else (f.initial.get('reviewed_by').id if hasattr(f.initial.get('reviewed_by'), 'id') else f.initial.get('reviewed_by'))
            })
        context_data['review_forms_json'] = json.dumps(review_forms_data)
        
        return context_data


class EditFault(PermissionRequiredMixin, UpdateView):

    model = models.Fault
    template_name = 'faults/fault_form.html'
    form_class = forms.FaultForm

    permission_required = "faults.change_fault"
    raise_exception = True

    def get_form_kwargs(self):
        """Add user to form kwargs"""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    @atomic
    def form_valid(self, form):

        context = self.get_context_data()

        reviews_valid = all(f.is_valid() for f in context['review_forms'])
        if not reviews_valid:
            return self.render_to_response(context)

        fault = save_valid_fault_form(form, self.request)

        reviewed = timezone.now()
        for review_form in context['review_forms']:

            frg = models.FaultReviewGroup.objects.filter(
                group__name=review_form.cleaned_data['group'],
            ).first()

            reviewed_by = review_form.cleaned_data['reviewed_by']

            update_existing_review = review_form.instance is not None
            if update_existing_review:
                reviewer_changed = review_form.instance.reviewed_by != reviewed_by
                if reviewer_changed and not reviewed_by:
                    review_form.instance.delete()
                elif reviewer_changed:
                    review_form.instance.reviewed = reviewed
                    review_form.instance.reviewed_by = reviewed_by
                    review_form.instance.save()
            elif reviewed_by:
                models.FaultReviewInstance.objects.create(
                    reviewed=reviewed,
                    reviewed_by=reviewed_by,
                    fault=fault,
                    fault_review_group=frg,
                )

        return HttpResponseRedirect(reverse('fault_list'))

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data['status_tag_colours'] = sl_models.ServiceEventStatus.get_colour_dict()
        context_data['se_statuses'] = {}
        if self.request.method == 'POST':
            data_key = "%s-related_service_events" % context_data['form'].prefix
            qs = sl_models.ServiceEvent.objects.filter(pk__in=self.request.POST.getlist(data_key))
            context_data['se_statuses'] = {se.id: se.service_status.id for se in qs}
        elif self.object:
            context_data['se_statuses'] = {
                se.id: se.service_status.id for se in self.object.related_service_events.order_by('-id')
            }

        context_data['se_statuses_json'] = json.dumps(context_data['se_statuses'])
        units_choices = [{'id': str(k), 'text': str(v)} for k, v in context_data['form'].fields['unit'].choices]
        context_data['units_json'] = json.dumps(units_choices)
        
        modality_choices = [{'id': str(k), 'text': str(v)} for k, v in context_data['form'].fields['modality'].choices]
        context_data['modalities_json'] = json.dumps(modality_choices)
        
        fault_json = {
            'id': self.object.id,
            'unit': self.object.unit_id if self.object.unit else None,
            'modality': self.object.modality_id if self.object.modality else None,
            'occurred': self.object.occurred.isoformat() if self.object.occurred else None,
            'fault_types': [ft.code for ft in self.object.fault_types.all()],
            'related_service_events': [se.id for se in self.object.related_service_events.order_by('-id')],
            'attachments': [{'id': a.id, 'name': a.label, 'url': a.attachment.url} for a in self.object.attachment_set.all()]
        }
        context_data['fault_json'] = json.dumps(fault_json)
        
        if context_data['form'].errors:
            context_data['form_errors_json'] = context_data['form'].errors.as_json()
        else:
            context_data['form_errors_json'] = '{}'

        frgs = models.FaultReviewGroup.objects.order_by("-required", "group__name")

        # if there are existing reviews we will use those to populate the initial data
        fris = {}
        for fri in self.object.faultreviewinstance_set.exclude(fault_review_group=None):
            fris[fri.fault_review_group.group.name] = fri

        context_data['review_forms'] = []
        for idx, frg in enumerate(frgs):
            data = self.request.POST if self.request.method == "POST" else None
            prefix = "review-form-%d" % idx
            instance = fris.get(frg.group.name)
            frg_form = forms.InlineReviewForm(data, instance=instance, fault_review_group=frg, prefix=prefix)
            context_data['review_forms'].append(frg_form)

        review_errors = {f.prefix: f.errors.get_json_data() for f in context_data['review_forms'] if f.errors}
        context_data['review_errors_json'] = json.dumps(review_errors)
        
        review_forms_data = []
        for f in context_data['review_forms']:
            review_forms_data.append({
                'prefix': f.prefix,
                'group_name': f.fields['group'].initial,
                'required': f.fields['reviewed_by'].required,
                'users': [{'id': u.id, 'name': u.get_full_name() or u.username} for u in f.fields['reviewed_by'].queryset],
                'selected': f.data.get(f.prefix + '-reviewed_by') if f.is_bound else (f.initial.get('reviewed_by').id if hasattr(f.initial.get('reviewed_by'), 'id') else f.initial.get('reviewed_by'))
            })
        context_data['review_forms_json'] = json.dumps(review_forms_data)
        
        return context_data


class DeleteFault(PermissionRequiredMixin, DeleteView):

    permission_required = "faults.delete_fault"
    raise_exception = True

    model = models.Fault

    def get_success_url(self):
        return self.request.GET.get("next", reverse("fault_list"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The confirmation page shows the fault's sections read-only.
        for section in SECTION_FIELDS:
            context.update(section_context(self.object, section))
        return context

    @atomic
    def delete(self, request, *args, **kwargs):
        Comment.objects.for_model(models.Fault).filter(object_pk=kwargs['pk']).delete()
        res = super().delete(self, request, *args, **kwargs)
        messages.success(request, _("Successfully deleted Fault {fault_id}").format(fault_id=kwargs['pk']))
        return res


def fault_create_ajax(request):
    """Simple view to handle an ajax post of the FaultForm"""

    form = forms.FaultForm(request.POST)

    frgs = models.FaultReviewGroup.objects.order_by("-required", "group__name")
    review_forms = []
    for idx, frg in enumerate(frgs):
        prefix = "review-form-%d" % idx
        frg_form = forms.InlineReviewForm(request.POST, fault_review_group=frg, prefix=prefix)
        review_forms.append(frg_form)

    review_forms_valid = all(f.is_valid() for f in review_forms)

    if form.is_valid() and review_forms_valid:
        fault = save_valid_fault_form(form, request)
        save_valid_review_forms(review_forms, fault)
        fault_id = fault.id
        msg = _("Fault ID %d was created" % fault_id)
    else:
        fault_id = None
        msg = _("Please resolve the errors below and submit again")

    results = {
        'error': fault_id is None,
        'errors': form.errors,
        'review_errors': [f.errors for f in review_forms],
        'message': msg,
    }
    return JsonResponse(results, encoder=QATrackJSONEncoder)


def _save_fault_types(fault, form):
    if "fault_types_field" not in form.cleaned_data:
        return
    new_faults = set(models.FaultType.objects.filter(code__in=form.cleaned_data['fault_types_field']))
    cur_faults = set(fault.fault_types.all())
    to_remove = cur_faults - new_faults
    to_add = new_faults - cur_faults
    fault.fault_types.remove(*to_remove)
    fault.fault_types.add(*to_add)

def _save_related_ses(fault, form):
    if "related_service_events" not in form.cleaned_data:
        return
    related_service_events = form.cleaned_data.get('related_service_events', [])
    sers = sl_models.ServiceEvent.objects.filter(pk__in=related_service_events)
    fault.related_service_events.set(sers)

def _save_attachments(fault, request):
    for f in request.FILES.getlist('fault-attachments'):
        Attachment.objects.create(
            attachment=f,
            comment="Uploaded %s by %s" % (timezone.now(), request.user.username),
            label=f.name,
            fault=fault,
            created_by=request.user
        )

    a_ids = []
    for val in request.POST.getlist('fault-attachments_delete_ids', ''):
        if val:
            a_ids.extend([v.strip() for v in val.split(',') if v.strip()])
    if a_ids:
        Attachment.objects.filter(id__in=a_ids).delete()

def save_valid_fault_form(form, request):
    """helper for EditFault, CreateFault, and create_ajax for processing FaultForm"""

    fault = form.save(commit=False)

    if not fault.id:
        fault.created_by = request.user

    fault.modified_by = request.user
    fault.save()

    comment = form.cleaned_data.get('comment', '')
    if comment:
        comment = Comment(
            submit_date=timezone.now(),
            user=request.user,
            content_object=fault,
            comment=comment,
            site=get_current_site(request)
        )
        comment.save()

    _save_fault_types(fault, form)
    _save_related_ses(fault, form)
    _save_attachments(fault, request)

    return fault


def save_valid_review_forms(forms, fault):
    reviewed = timezone.now()
    for review_form in forms:
        reviewed_by = review_form.cleaned_data['reviewed_by']
        if not reviewed_by:
            continue

        frg = models.FaultReviewGroup.objects.filter(
            group__name=review_form.cleaned_data['group'],
        ).first()
        models.FaultReviewInstance.objects.create(
            reviewed=reviewed,
            reviewed_by=reviewed_by,
            fault=fault,
            fault_review_group=frg,
        )


def fault_type_autocomplete(request):
    """Look for fault types matching users query.  If the fault type doesn't
    exist, return it as a first option so user can select it and have it
    created when they submit the form."""

    q = request.GET.get('q', '').replace(forms.NEW_FAULT_TYPE_MARKER, "").lower()
    qs = models.FaultType.objects.filter(
        Q(code__icontains=q) | Q(code__icontains=q.strip()),
    ).order_by("code")

    qs = qs.values_list("id", "code", "description", "slug")

    results = []

    exact_match = None
    for ft_id, code, description, slug in qs:
        code = code
        description = description or ''
        text = "%s: %s" % (code, truncatechars(description, 80)) if description else code
        if code.lower() == q.strip():
            exact_match = {'id': code, 'code': code, 'text': text, 'description': description, 'slug': slug}
        else:
            results.append({'id': code, 'text': text, 'description': description, 'code': code, 'slug': slug})

    new_option = q and exact_match is None
    if new_option and request.user.has_perm("faults.add_faulttype"):
        # allow user to create a new match
        new_result = {'id': "%s%s" % (forms.NEW_FAULT_TYPE_MARKER, q), 'text': "*%s*" % q, 'code': q, 'description': ''}
        results = [new_result] + results
    elif q and exact_match:
        # put the exact match first in the list
        # put the exact match first in the list
        results = [exact_match] + results

    return JsonResponse({'results': results}, encoder=QATrackJSONEncoder)


class FaultDetails(FaultList):

    template_name = 'faults/fault_details.html'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.templates['fault_types'] = get_template("faults/fault_type_chips.html")

    def get_queryset(self):
        fault = models.Fault.objects.prefetch_related("fault_types").get(pk=self.kwargs['pk'])
        return super().get_queryset().filter(fault_types__in=fault.fault_types.all())

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        qs = models.Fault.objects.select_related(
            "created_by",
            "modified_by",
        ).prefetch_related(
            "faultreviewinstance_set",
            "fault_types",
        )
        fault = get_object_or_404(qs, pk=self.kwargs['pk'])
        context['fault'] = fault

        # Every section starts read-only. Edit forms (and the widgets they need)
        # are only fetched when someone clicks a section's pencil.
        for section in SECTION_FIELDS:
            context.update(section_context(fault, section))

        return context


def create_reviews_for_fault(fault, user):

    frgs = models.FaultReviewGroup.objects.filter(group__in=user.groups.all())
    frgs = frgs or [None]
    reviewed = timezone.now()
    reviews = []
    for frg in frgs:
        reviews.append(
            models.FaultReviewInstance(
                reviewed=reviewed,
                reviewed_by=user,
                fault=fault,
                fault_review_group=frg,
            )
        )
    return reviews


@require_POST
def review_fault(request, pk):
    fault = get_object_or_404(models.Fault.objects.all(), pk=pk)
    form = forms.ReviewFaultForm(request.POST, instance=fault)
    if form.is_valid():
        fault = form.save(commit=False)
        fault.modified_by = request.user
        fault.save()
        acknowledge = fault.faultreviewinstance_set.first() is None
        if acknowledge:
            reviews = create_reviews_for_fault(fault, request.user)
            for review in reviews:
                review.save()
        else:
            fault.faultreviewinstance_set.all().delete()

        if is_htmx(request):
            # The details page swaps in just the Record box (and, out of band, the
            # status label in the page header). The changed button and status
            # say what happened, so there's no flash message to leave behind for
            # the next full page load.
            fault = models.Fault.objects.select_related("created_by", "modified_by").get(pk=fault.pk)
            return render(request, "faults/_fault_record.html", {"fault": fault, "oob_status": True})

        if acknowledge:
            messages.success(request, _("Successfully acknowledged %(fault)s ") % {'fault': fault})
        else:
            messages.warning(request, _("Successfully unacknowledged %(fault)s ") % {'fault': fault})
    else:  # pragma: nocover
        messages.error(request, _("Sorry, something went wrong trying to review this fault. It has not been updated"))

    return HttpResponseRedirect(reverse('fault_details', kwargs={'pk': fault.pk}))


@require_POST
@atomic
def bulk_review(request):
    faults = request.POST.getlist('faults')
    faults = models.Fault.objects.unreviewed().filter(pk__in=faults)

    to_create = []
    for f in faults:
        reviews = create_reviews_for_fault(f, request.user)
        to_create.extend(reviews)
    models.FaultReviewInstance.objects.bulk_create(to_create)

    count = len(to_create)
    msg = _("Successfully reviewed %(count)s faults") % {'count': count}
    messages.add_message(request=request, message=msg, level=messages.SUCCESS)
    return JsonResponse({"ok": True})


class FaultsByUnit(FaultList):

    model = models.Fault
    template_name = 'faults/fault_list.html'

    def get_fields(self, request):
        exclude = ['unit__site__name', 'unit__name']
        fields = super().get_fields(request)
        return [f for f in fields if f not in exclude]

    def get_queryset(self):
        return super().get_queryset().filter(unit__number=self.kwargs['unit_number'])

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        unit = get_object_or_404(Unit, number=self.kwargs['unit_number'])
        context['unit'] = unit
        context['page_title'] = "%s: %s" % (_("Faults for"), unit.site_unit_name())
        return context


class FaultsByUnitFaultType(FaultList):

    model = models.Fault
    template_name = 'faults/fault_list.html'

    def get_fields(self, request):
        exclude = ['unit__site__name', 'unit__name', 'fault_types']
        fields = super().get_fields(request)
        return [f for f in fields if f not in exclude]

    def get_queryset(self):
        return super().get_queryset().filter(
            unit__number=self.kwargs['unit_number'],
            fault_types__slug=self.kwargs['slug'],
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        unit = get_object_or_404(Unit, number=self.kwargs['unit_number'])
        fault_type = get_object_or_404(models.FaultType, slug=self.kwargs['slug'])
        context['unit'] = unit
        context['fault_type'] = fault_type
        title = _("{fault_type} faults for: {site_and_unit_name}").format(
            fault_type=fault_type,
            site_and_unit_name=unit.site_unit_name(),
        )
        context['page_title'] = title
        return context


class FaultTypeList(BaseListableView):

    model = models.FaultType
    template_name = 'faults/fault_type_list.html'
    paginate_by = 50

    kwarg_filters = None

    fields = (
        "actions",
        "code",
        'count',
        "description",
    )

    headers = {
        'actions': _l('Actions'),
        'code': _l('Fault Type'),
        'count': _l("# of Occurrences"),
        'description': _l("Description"),
    }

    widgets = {
        'actions': None,
        'code': TEXT,
        'count': None,
        'description': TEXT,
    }

    search_fields = {
        'actions': False,
        'count': None,
    }

    order_fields = {
        'actions': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.templates = {
            'actions': get_template('faults/fault_type_actions.html'),
            'description': get_template("faults/fault_type_description.html"),
        }

    def get_queryset(self):
        return super().get_queryset().order_by("code").annotate(
            count=Count("faults"),
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        current_url = resolve(self.request.path_info).url_name
        context['view_name'] = current_url
        context['page_title'] = _l("All Fault Types")
        return context

    def actions(self, fault_type):
        c = {
            'fault_type': fault_type,
            'next': reverse('fault_type_list'),
            'perms': PermWrapper(self.request.user),
        }
        return self.templates['actions'].render(c)

    def description(self, fault_type):
        c = {'fault_type': fault_type}
        return self.templates['description'].render(c)


class FaultTypeDetails(FaultList):

    template_name = 'faults/fault_type_details.html'

    def get_queryset(self):
        return super().get_queryset().filter(
            fault_types__slug=self.kwargs['slug'],
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        fault_type = get_object_or_404(models.FaultType, slug=self.kwargs['slug'])
        unit_faults = models.Fault.objects.filter(
            fault_types=fault_type,
        ).values(
            "unit__name",
            "unit__number",
            "unit_id",
        ).annotate(unit_count=Count("unit__%s" % settings.ORDER_UNITS_BY)).order_by(
            "-unit_count",
        )
        context['fault_type'] = fault_type
        context['unit_faults'] = unit_faults

        return context


class ChooseUnitForViewFaults(ChooseUnit):
    template_name = 'units/unittype_choose_for_faults.html'
    split_sites = True


@require_POST
def edit_fault_type_description(request, slug):
    if not request.user.has_perm('faults.change_faulttype'):
        return JsonResponse({"error": "Permission denied."}, status=403)

    fault_type = get_object_or_404(models.FaultType, slug=slug)

    # The details page posts from inside the fault types form, where every row
    # has its own editor, so the field is named after the slug there.
    new_description = request.POST.get("description-%s" % slug, request.POST.get("description"))
    if new_description is None:
        # A request with no description at all shouldn't wipe the existing one.
        return HttpResponseBadRequest(_("No description was provided."))

    fault_type.description = new_description.strip()
    fault_type.save()

    if is_htmx(request):
        return render(request, "faults/sections/_fault_type_row.html", {
            "row": fault_type_row(fault_type),
            "editing": True,
        })

    return JsonResponse({
        "status": "success",
        "description": fault_type.description
    })


PICKER_LIMIT = 30


def _picker_fault(request, pk):
    if not request.user.has_perm("faults.change_fault"):
        raise PermissionDenied
    return get_object_or_404(models.Fault.objects.select_related("unit"), pk=pk)


def fault_type_picker(request, pk):
    """Search results for the fault types picker on the details page.

    Types already in the section form are left out, and a "Create" option comes
    first when nothing matches the search exactly and the user may add types.
    """
    _picker_fault(request, pk)
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return HttpResponse("")

    marker = forms.NEW_FAULT_TYPE_MARKER
    selected = {v.replace(marker, "", 1).lower() for v in request.GET.getlist("fault-fault_types_field")}

    matches = models.FaultType.objects.filter(Q(code__icontains=q) | Q(description__icontains=q)).order_by("code")
    results = [ft for ft in matches[:PICKER_LIMIT + len(selected)] if ft.code.lower() not in selected][:PICKER_LIMIT]

    exact = q.lower() in selected or models.FaultType.objects.filter(code__iexact=q).exists()
    can_create = not exact and request.user.has_perm("faults.add_faulttype")

    return render(request, "faults/sections/_fault_type_picker_results.html", {
        "results": results,
        "create_code": q if can_create else None,
        "new_marker": marker,
        "fault_pk": pk,
    })


def fault_type_picker_row(request, pk):
    """One fault types table row for a code chosen in the picker."""
    _picker_fault(request, pk)
    value = request.GET.get("code", "").strip()
    marker = forms.NEW_FAULT_TYPE_MARKER
    code = value.replace(marker, "", 1).strip()
    if not code:
        return HttpResponseBadRequest(_("No fault type code was provided."))

    fault_type = models.FaultType.objects.filter(code__iexact=code).first()
    if fault_type:
        row = fault_type_row(fault_type)
    elif request.user.has_perm("faults.add_faulttype"):
        row = fault_type_row(new_code=code)
    else:
        return HttpResponseForbidden(_("You don't have permission to create fault types."))

    return render(request, "faults/sections/_fault_type_row.html", {"row": row, "editing": True})


def _unit_service_events(fault):
    return sl_models.ServiceEvent.objects.filter(
        unit_service_area__unit=fault.unit,
    ).select_related("service_status")


def fault_se_picker(request, pk):
    """Search results for the related service events picker: service events on
    the fault's unit that aren't already related, newest first."""
    fault = _picker_fault(request, pk)
    q = request.GET.get("q", "").strip()
    selected = [v for v in request.GET.getlist("fault-related_service_events") if v.isdigit()]

    qs = _unit_service_events(fault).exclude(pk__in=selected)
    if q:
        search = Q(problem_description__icontains=q)
        if q.lstrip("#").isdigit():
            search |= Q(id__icontains=q.lstrip("#"))
        qs = qs.filter(search)

    return render(request, "faults/sections/_se_picker_results.html", {
        "results": qs.order_by("-id")[:PICKER_LIMIT],
        "fault_pk": pk,
    })


def fault_se_picker_row(request, pk):
    """One related service events table row for a service event chosen in the picker."""
    fault = _picker_fault(request, pk)
    se_id = request.GET.get("se", "")
    if not se_id.isdigit():
        return HttpResponseBadRequest(_("No service event was provided."))
    service_event = get_object_or_404(_unit_service_events(fault), pk=se_id)
    return render(request, "faults/sections/_se_row.html", {"se": service_event, "editing": True})
