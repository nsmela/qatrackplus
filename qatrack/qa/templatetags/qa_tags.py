import collections

from django import template
from django.conf import settings
from django.template.loader import get_template
from django.utils import timezone
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from qatrack.qa import models
from qatrack.qatrack_core import scheduling
from qatrack.qatrack_core.dates import end_of_day, format_as_date, start_of_day

register = template.Library()


@register.simple_tag
def qa_value_form(form, test_list, perms, user, test_info=None, unit_test_collection=None, show_category=True):
    template = get_template("qa/qavalue_form.html")
    c = {
        "user": user,
        "form": form,
        "perms": perms,
        "test_list": test_list,
        "test_info": test_info,
        'unit_test_collection': unit_test_collection,
        'show_category': show_category,
    }
    return template.render(c)


@register.simple_tag
def qa_table_colspan(perms, offset=0):
    perms_to_check = ['can_view_ref_tol', 'can_view_history']
    span = 6 - offset + sum(1 for p in perms_to_check if perms['qa'][p])
    return "%d" % (span)


def _interpolate(message, **values):
    """Fill a translated message's named placeholders, escaping the message and the values.

    The message comes from a translation catalogue and the values can be user data (choices,
    reference values), so neither is trusted as HTML. Returns a SafeString ready for format_html.
    """
    return mark_safe(conditional_escape(message) % {k: conditional_escape(v) for k, v in values.items()})


def _tolerance_limits(tol):
    """The four limits of an Absolute/Percent tolerance, e.g. "(-2.000, -1.000, 1.000, 2.000)".

    Formatted the same way as the stored tolerance name, without its type prefix.
    """
    vals = (tol.act_low, tol.tol_low, tol.tol_high, tol.act_high)
    fmt = "%.2f%%" if tol.type == models.PERCENT else "%.3f"
    return "(%s)" % ", ".join(fmt % v if v is not None else "--" for v in vals)


@register.simple_tag
def reference_tolerance_span(test, ref, tol):

    if ref is None and not (test.is_mult_choice() or test.is_string_type()):
        # Translators: shown on Perform QC when a test has no reference value
        return format_html("<span>{}</span>", _("No Ref"))

    if test.is_boolean():
        ref_display = ref.value_display(test)
        return format_html(
            '<span title="{}">{}</span>',
            _("Passing value = %(value)s") % {"value": ref_display},
            ref_display,
        )

    if not tol:
        title = _("No Tolerance Set")
        if ref:
            return format_html('<span title="{}">{}</span>', title, ref.value_display())
        # Translators: short form of "No Tolerance Set" shown on Perform QC
        return format_html('<span title="{}">{}</span>', title, _("No Tol"))

    tsd = settings.TEST_STATUS_DISPLAY
    if tol.type == models.MULTIPLE_CHOICE:
        title = "%s;  %s; %s" % (
            _("%(status)s Values: %(choices)s") % {"status": tsd['ok'], "choices": ", ".join(tol.pass_choices())},
            _("%(status)s Values: %(choices)s") % {"status": tsd['tolerance'], "choices": ", ".join(tol.tol_choices())},
            _("All other choices are failing"),
        )
        # Translators: short label for a multiple choice test's tolerance on Perform QC
        return format_html('<span><abbr title="{}"><em>{}</em></abbr></span>', title, _("Choice"))

    if tol.type in (models.ABSOLUTE, models.PERCENT):
        tsds = settings.TEST_STATUS_DISPLAY_SHORT
        # Translators: L and H stand for Low and High; e.g. "(ACT L, TOL L, TOL H, ACT H) = (-2, -1, 1, 2)"
        title = _("(%(act)s L, %(tol)s L, %(tol)s H, %(act)s H) = %(limits)s") % {
            "act": tsds["action"],
            "tol": tsds["tolerance"],
            "limits": _tolerance_limits(tol),
        }
        return format_html('<span> <abbr title="{} ">{}</abbr></span>', title, ref.value_display() if ref else "")


@register.filter
def reference_display(ref, test=None):
    """Display a reference, reading Yes/No when ``test`` is a Boolean test.

    Usage: ``{{ ti.reference|reference_display:ti.unit_test_info.test }}``
    """
    if ref is None:
        return ""
    return ref.value_display(test)


@register.simple_tag
def tolerance_for_reference(tol, ref, test=None):

    if not ref and tol and tol.type != models.MULTIPLE_CHOICE:
        return ""

    tsd = settings.TEST_STATUS_DISPLAY
    if ref and (ref.type == models.BOOLEAN or (test is not None and test.is_boolean())):
        expected = ref.value_display(test)
        failing = _("No") if int(ref.value) == 1 else _("Yes")
        return format_html(
            "<span>{}; {}</span>",
            _interpolate(_("%(status)s: %(value)s"), status=tsd['ok'], value=expected),
            _interpolate(_("%(status)s: %(value)s"), status=tsd['action'], value=failing),
        )

    if not tol:
        return format_html("<span><em>{}</em></span>", _("N/A"))

    if tol.type == models.MULTIPLE_CHOICE:
        return format_html(
            "<span>{}<br>  {}<br> {}</span>",
            _interpolate(_("%(status)s: %(choices)s"), status=tsd['ok'], choices=", ".join(tol.pass_choices())),
            _interpolate(_("%(status)s: %(choices)s"), status=tsd['tolerance'], choices=", ".join(tol.tol_choices())),
            _("All others fail"),
        )

    tols = {k: "-" if v is None else "%.4g" % v for k, v in tol.tolerances_for_value(ref.value).items()}
    return format_html(
        "<span>{}<br> {}<br> {}</span>",
        _interpolate(
            _("%(status)s: Between %(low)s & %(high)s"),
            status=tsd['ok'], low=tols[models.TOL_LOW], high=tols[models.TOL_HIGH],
        ),
        _interpolate(
            # Translators: there is no colon after the status here, matching the long-standing display
            _("%(status)s Between %(low)s & %(high)s"),
            status=tsd['tolerance'], low=tols[models.ACT_LOW], high=tols[models.ACT_HIGH],
        ),
        _interpolate(
            _("%(status)s: < %(low)s or > %(high)s"),
            status=tsd['action'], low=tols[models.ACT_LOW], high=tols[models.ACT_HIGH],
        ),
    )


@register.simple_tag
def history_display(history, unit, test_list, test, frequency=None):
    template = get_template("qa/history.html")

    # Set start / end dates of 1 year, or the span of the history elements, whichever is larger
    one_year = timezone.timedelta(days=365)
    end_date = end_of_day(timezone.now())
    start_date = start_of_day(end_date - one_year)
    if history:
        start_date = history[-1][0].work_completed
        end_date = history[0][0].work_completed
        hist_covers_less_than_1_year = end_date - start_date < one_year
        if hist_covers_less_than_1_year:
            start_date = end_date - one_year
    date_range = "%s - %s" % (format_as_date(start_date), format_as_date(end_date))

    c = {
        "history": history,
        "date_range": date_range,
        "unit": unit,
        "test_list": test_list,
        "test": test,
        "show_icons": settings.ICON_SETTINGS['SHOW_STATUS_ICONS_HISTORY'],
        'frequency': frequency
    }
    return template.render(c)


@register.filter
def as_pass_fail_status(test_list_instance, show_label=True):
    template = get_template("qa/pass_fail_status.html")
    # statuses_to_exclude = [models.NO_TOL]
    statuses_to_exclude = ['no_tol']
    c = {"instance": test_list_instance, "exclude": statuses_to_exclude, "show_label": show_label, 'show_icons': True}
    return template.render(c)


@register.filter
def as_review_status(test_list_instance):
    statuses = collections.defaultdict(lambda: {"count": 0})
    comment_count = 0
    for ti in test_list_instance.testinstance_set.all():
        statuses[ti.status.name]["count"] += 1
        statuses[ti.status.name]["valid"] = ti.status.valid
        statuses[ti.status.name]["requires_review"] = ti.status.requires_review
        statuses[ti.status.name]["reviewed_by"] = test_list_instance.reviewed_by
        statuses[ti.status.name]["reviewed"] = test_list_instance.reviewed
        statuses[ti.status.name]["colour"] = ti.status.colour
        if ti.comment:
            comment_count += 1
    # if test_list_instance.comment:
    #     comment_count += 1
    comment_count += test_list_instance.comments.count()
    template = get_template("qa/review_status.html")
    c = {
        "statuses": dict(statuses),
        "comments": comment_count,
        "show_icons": settings.ICON_SETTINGS['SHOW_REVIEW_ICONS'],
    }
    return template.render(c)


@register.filter(expects_local_time=True)
def as_due_date(unit_test_collection):
    template = get_template("qa/due_date.html")
    c = {"unit_test_collection": unit_test_collection, "show_icons": settings.ICON_SETTINGS["SHOW_DUE_ICONS"]}
    return template.render(c)


@register.filter(expects_local_time=True)
def as_qc_window(unit_test_collection):

    start, end = scheduling.qc_window(unit_test_collection.due_date, unit_test_collection.frequency)
    if start:
        start = format_as_date(start)

    if end:
        end = format_as_date(end)

    if start:
        return "%s - %s" % (start, end)
    elif unit_test_collection.due_date:
        start = format_as_date(unit_test_collection.due_date)
        return "%s - %s" % (start, end)

    return ""


@register.filter(is_safe=True, expects_local_time=True)
def as_time_delta(time_delta):
    hours, remainder = divmod(time_delta.seconds, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    return '%dd %dh %dm %ds' % (time_delta.days, hours, minutes, seconds)


as_time_delta.safe = True  # noqa: E305


@register.filter
def as_data_attributes(unit_test_collection):
    utc = unit_test_collection
    due_date = utc.due_date
    last_done = utc.last_done_date()

    attrs = {
        "frequency": utc.frequency.slug,
        "due_date": due_date.isoformat() if due_date else "",
        "last_done": last_done.isoformat() if last_done else "",
        "id": utc.pk,
        "unit_number": utc.unit.number,
    }

    return " ".join(['data-%s=%s' % (k, v) for k, v in list(attrs.items()) if v])


@register.filter
def hour_min(duration):
    if duration in (None, ""):
        return ""
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f'{hours:0>2}:{minutes:0>2}'


@register.simple_tag
def service_status_label(status, size=None):
    template = get_template('service_log/service_event_status_label.html')
    return template.render({'colour': status.colour, 'name': status.name, 'size': '10.5' if size is None else size})


@register.simple_tag
def service_event_btn(event, size='xs'):
    template = get_template('service_log/service_event_btn.html')
    return template.render({'colour': event.service_status.colour, 'id': event.id, 'size': size})
