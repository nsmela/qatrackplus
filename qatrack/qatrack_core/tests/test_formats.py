"""The date formats handed to the browser (siteConfig in site_base.html) exist in every language.

Django's get_format() answers with the setting's own *name* when no format module
defines it, so a language without one hands the date pickers "FLATPICKR_DATETIME_FMT"
as the format and every picker on the site breaks for its users.
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

# Spanish has no format module until qatrackplus/qatrackplus#873.
LANGUAGES = [
    pytest.param(code, marks=pytest.mark.xfail(
        strict=True, raises=AssertionError, reason='no qatrack/formats/es until qatrackplus/qatrackplus#873',
    )) if code == 'es' else code
    for code, name in settings.LANGUAGES
]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('name', JS_FORMATS)
def test_every_language_has_every_javascript_date_format(language, name):
    with translation.override(language):
        value = get_format(name)
    assert value and value != name, '%s has no %s (see qatrack/formats/)' % (language, name)
