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
