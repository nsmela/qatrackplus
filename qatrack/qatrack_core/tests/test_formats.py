"""The date formats handed to the browser (siteConfig in site_base.html) exist in every language,
and agree with the formats the forms render dates in.

Date boxes are filled in by Django and then read by Flatpickr. When the two use
different formats, Flatpickr does not complain: it misreads the date and the form
submits the wrong one.
"""

import pytest
from django.conf import settings
from django.utils import translation
from django.utils.formats import get_format

JS_FORMATS = (
    'MOMENT_DATE_DATA_FMT',
    'MOMENT_DATE_FMT',
    'MOMENT_DATETIME_FMT',
    'FLATPICKR_DATE_FMT',
    'FLATPICKR_DATETIME_FMT',
    'DATERANGEPICKER_DATE_FMT',
)

# Flatpickr's tokens and their strftime equivalents, for the tokens QATrack+ uses.
FLATPICKR_TO_STRFTIME = {'Y': '%Y', 'm': '%m', 'd': '%d', 'M': '%b', 'H': '%H', 'i': '%M', 'S': '%S'}


def flatpickr_to_strftime(fmt):
    return ''.join(FLATPICKR_TO_STRFTIME.get(c, c) for c in fmt)


LANGUAGES = [code for code, name in settings.LANGUAGES]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('name', JS_FORMATS)
def test_every_language_has_every_javascript_date_format(language, name):
    """get_format() answers with the setting's own name when no format module defines it."""
    with translation.override(language):
        value = get_format(name)
    assert value and value != name, '%s has no %s (see qatrack/formats/)' % (language, name)


@pytest.mark.parametrize('language', LANGUAGES)
def test_date_pickers_read_what_the_forms_render(language):
    """The perform, service event and fault forms render dates in these settings' formats."""
    with translation.override(language):
        assert flatpickr_to_strftime(get_format('FLATPICKR_DATETIME_FMT')) == settings.DATETIME_INPUT_FORMATS[2]
        assert flatpickr_to_strftime(get_format('FLATPICKR_DATE_FMT')) == settings.DATE_INPUT_FORMATS[0]
