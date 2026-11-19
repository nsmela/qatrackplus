"""Template helpers for the QC admin card layout (admin/qa/change_form.html).

The shared QC change form draws each fieldset as a card and lays its fields out
in a two-column grid. These helpers let a ModelAdmin tune that without its own
template, through optional attributes (all of them optional):

``qc_fieldset_icons``
    ``{fieldset name: "fa-icon"}``. ``None`` is the key for an unnamed fieldset.
``qc_wide_fields``
    Field names that should span both columns, on top of the ones picked
    automatically (text areas, multi-selects, the recurrence widget).
``qc_inline_icons``
    ``{inline model name: "fa-icon"}`` for the inline cards.
"""

from django import forms, template
from django.utils.translation import gettext as _

register = template.Library()

DEFAULT_FIRST_ICON = "fa-info-circle"
DEFAULT_ICON = "fa-sliders"
DEFAULT_INLINE_ICON = "fa-list-ul"


@register.simple_tag
def qc_fieldset_title(fieldset):
    """A fieldset's card title: its name, or "Details" when it has none."""
    return fieldset.name or _("Details")


@register.simple_tag
def qc_fieldset_icon(model_admin, fieldset, first=False):
    """The Font Awesome icon for a fieldset's card."""
    icons = getattr(model_admin, "qc_fieldset_icons", None) or {}
    if fieldset.name in icons:
        return icons[fieldset.name]
    return DEFAULT_FIRST_ICON if first else DEFAULT_ICON


@register.simple_tag
def qc_inline_icon(model_admin, inline_admin_formset):
    """The Font Awesome icon for an inline's card."""
    icons = getattr(model_admin, "qc_inline_icons", None) or {}
    return icons.get(inline_admin_formset.opts.model._meta.model_name, DEFAULT_INLINE_ICON)


def _field_name(admin_field):
    """The field name of an AdminField or AdminReadonlyField."""
    if admin_field.is_readonly:
        return admin_field.field["name"]
    return admin_field.field.name


@register.simple_tag
def qc_field_name(admin_field):
    name = _field_name(admin_field)
    # Readonly callables (e.g. a ModelAdmin method) have a function as their name.
    return name if isinstance(name, str) else getattr(name, "__name__", "")


@register.simple_tag
def qc_is_wide(admin_field, model_admin):
    """True when a field should span both columns of the card grid."""
    name = qc_field_name(admin_field)
    if name in (getattr(model_admin, "qc_wide_fields", None) or ()):
        return True
    if admin_field.is_readonly:
        return False
    widget = admin_field.field.field.widget
    # RelatedFieldWidgetWrapper (the "+" add links) wraps the real widget.
    widget = getattr(widget, "widget", widget)
    if isinstance(widget, forms.Textarea | forms.SelectMultiple):  # incl. FilteredSelectMultiple
        return True
    return "recurrence" in type(widget).__module__.lower()


@register.simple_tag
def qc_is_required(admin_field):
    """True for an editable field the form requires."""
    return not admin_field.is_readonly and admin_field.field.field.required


@register.simple_tag
def qc_label(admin_field):
    """A field's label without Django admin's trailing colon."""
    if admin_field.is_readonly:
        return admin_field.field["label"]
    return admin_field.field.label


@register.simple_tag
def qc_help_text(admin_field):
    if admin_field.is_readonly:
        return admin_field.field.get("help_text", "")
    return admin_field.field.help_text


@register.simple_tag
def qc_label_for(admin_field):
    """The id a field's <label for=""> should point at, or "" for none.

    Django gives no id for some widgets: a split date and time (two inputs) and a list of
    checkboxes. A split widget's label points at its first input; a checkbox list gets no
    ``for`` at all, as on Django's own admin forms.
    """
    if admin_field.is_readonly:
        return ""
    bound = admin_field.field
    if bound.id_for_label:
        return bound.id_for_label
    widget = bound.field.widget
    widget = getattr(widget, "widget", widget)
    if isinstance(widget, forms.MultiWidget) and bound.auto_id:
        return "%s_0" % bound.auto_id
    return ""


@register.simple_tag
def qc_hide_label(fieldset, admin_field):
    """True when a field's label would only repeat its card's title.

    That is a card with one field, labelled the same as the card (e.g. Comments in the
    Comments card). The label is then kept for screen readers but not shown. A required
    field keeps its label, so its required marker stays visible.
    """
    fields = [f for line in fieldset for f in line if f.is_readonly or not f.field.is_hidden]
    if len(fields) != 1 or qc_is_required(admin_field):
        return False
    label = str(qc_label(admin_field) or "").strip().lower()
    return bool(label) and label == str(qc_fieldset_title(fieldset)).strip().lower()
