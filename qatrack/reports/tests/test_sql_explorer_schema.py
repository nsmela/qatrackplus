"""Which tables the SQL Explorer schema sidebar tries to describe (#819).

SQL Explorer isn't in INSTALLED_APPS during the test run (USE_SQL_REPORTS is
off by default), so these tests check the setting directly, using the same
rule SQL Explorer uses: a table is included when its name starts with one of
EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES, and the exclude list is ignored once
an include list is set.
"""

from django.apps import apps
from django.conf import settings


def _in_schema(table_name):
    return any(table_name.startswith(p) for p in settings.EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES)


def _auth_tables():
    tables = set()
    for model in apps.get_app_config('auth').get_models(include_auto_created=True):
        tables.add(model._meta.db_table)
    return tables


def test_auth_user_is_not_in_schema():
    """The readonly user can't read auth_user.password, so on MySQL describing
    auth_user raises an error SQL Explorer doesn't catch, and every saved query
    returns HTTP 500."""
    assert not _in_schema('auth_user')


def test_other_auth_tables_stay_in_schema():
    auth_tables = _auth_tables()
    assert 'auth_user' in auth_tables
    missing = sorted(t for t in auth_tables - {'auth_user'} if not _in_schema(t))
    assert missing == []


def test_qatrack_tables_stay_in_schema():
    for table in ['qa_testlist', 'service_log_serviceevent', 'units_unit', 'parts_part']:
        assert _in_schema(table), table
