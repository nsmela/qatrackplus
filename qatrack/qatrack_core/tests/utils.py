def get_next_id(obj):
    if obj is None:
        return 1
    return obj.id + 1


def setup_view(view, request, *args, **kwargs):
    """
    Mimic ``as_view()``, but returns view instance.
    Use this function to get view instances on which you can run unit tests,
    by testing specific methods.
    """

    view.request = request
    view.args = args
    view.kwargs = kwargs
    return view


# Flatpickr's format tokens and their strftime equivalents, for the tokens QATrack+ uses.
FLATPICKR_TO_STRFTIME = {'Y': '%Y', 'y': '%y', 'm': '%m', 'n': '%-m', 'd': '%d', 'j': '%-d', 'M': '%b', 'F': '%B',
                         'H': '%H', 'i': '%M', 'S': '%S'}


def picker_format(name='FLATPICKR_DATETIME_FMT'):
    """The strftime equivalent of a date picker format (FLATPICKR_DATE_FMT or FLATPICKR_DATETIME_FMT).

    Tests compare what the pickers show with this rather than a format written out
    by hand, so they keep checking the right thing if the configured format changes.
    """
    from django.utils.formats import get_format
    return ''.join(FLATPICKR_TO_STRFTIME.get(c, c) for c in get_format(name))


MOMENT_TO_STRFTIME = (('YYYY', '%Y'), ('MMMM', '%B'), ('MMM', '%b'), ('MM', '%m'), ('DD', '%d'), ('HH', '%H'),
                      ('mm', '%M'), ('ss', '%S'))


def moment_format(name='MOMENT_DATETIME_FMT'):
    """The strftime equivalent of a moment.js format (MOMENT_DATE_FMT or MOMENT_DATETIME_FMT)."""
    from django.utils.formats import get_format
    fmt = get_format(name)
    for token, strftime in MOMENT_TO_STRFTIME:
        fmt = fmt.replace(token, strftime)
    return fmt
