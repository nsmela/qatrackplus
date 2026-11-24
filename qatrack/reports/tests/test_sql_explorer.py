"""Tests for the SQL query tool (SQL Explorer) pages.

#819: on MySQL, opening any saved query returned HTTP 500. Opening a saved
query makes SQL Explorer build its schema sidebar, which describes each listed
table. Django's MySQL backend describes a table with `SELECT * FROM <table>
LIMIT 1`, and the readonly user can't read auth_user.password (see
deploy/mysql/generate_ro_privileges.sql), so MySQL refuses with error 1143.
mysqlclient raises that as OperationalError, SQL Explorer only skips tables
that raise ProgrammingError, and the error escaped to the page.

The test suite connects with full privileges, so these tests make Django's
table description raise the error MySQL gives the readonly user, and leave
everything else in SQL Explorer running for real.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import OperationalError, connections
from django.test import TestCase
from django.urls import reverse
from explorer.ee.db_connections.models import DatabaseConnection
from explorer.models import Query

# EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES as it was before the #819 fix.
PRE_819_SCHEMA_PREFIXES = ['auth_', 'qa', 'service_log', 'units', 'parts']

# What MySQL says when the readonly user runs `SELECT * FROM auth_user`.
MYSQL_COLUMN_ACCESS_DENIED = (
    1143,
    "SELECT command denied to user 'qatrack_reports'@'localhost' for column 'password' in table 'auth_user'",
)


class TestSavedQueryWithMySQLReadonlyUser(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('sqladmin', 'sqladmin@example.com', 'password')
        self.client.force_login(self.user)

        # SQL Explorer's migrations create this row, but a TransactionTestCase
        # elsewhere in the suite may have flushed it.
        connection = DatabaseConnection.objects.default() or DatabaseConnection.objects.create(
            alias='default',
            name='default',
            engine=DatabaseConnection.DJANGO,
            default=True,
        )
        # A query saved through the UI always has a connection, and the schema
        # sidebar is only built for queries that do.
        self.query = Query.objects.create(
            title='Issue 819',
            sql='SELECT 819 AS issue_819',
            created_by_user=self.user,
            database_connection=connection,
        )
        self.url = reverse('query_detail', kwargs={'query_id': self.query.pk})

        # SQL Explorer caches the schema; start and finish each test without it.
        cache.clear()
        self.addCleanup(cache.clear)

        self.described_tables = []
        introspection = connections['default'].introspection
        describe_table = introspection.get_table_description

        def describe_as_mysql_readonly_user(cursor, table_name):
            self.described_tables.append(table_name)
            if table_name == 'auth_user':
                raise OperationalError(*MYSQL_COLUMN_ACCESS_DENIED)
            return describe_table(cursor, table_name)

        patcher = mock.patch.object(
            introspection,
            'get_table_description',
            side_effect=describe_as_mysql_readonly_user,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_old_schema_prefixes_reproduce_819(self):
        """With the settings from before the fix, opening the query fails with
        the MySQL error, as reported in #819.

        If this starts failing after upgrading SQL Explorer, Explorer now
        handles the error itself, and the auth_user workaround in settings.py
        can be reconsidered.
        """
        with mock.patch('explorer.schema.EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES', PRE_819_SCHEMA_PREFIXES):
            with self.assertRaisesMessage(OperationalError, "for column 'password' in table 'auth_user'"):
                self.client.get(self.url)
        self.assertIn('auth_user', self.described_tables)

    def test_saved_query_runs(self):
        """With the current settings, the query opens and shows its results."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['error'])
        self.assertEqual([str(h) for h in response.context['headers']], ['issue_819'])
        self.assertEqual([list(row) for row in response.context['data']], [[819]])

    def test_schema_skips_only_auth_user(self):
        """The sidebar still lists the other auth tables and QATrack+'s own."""
        self.client.get(self.url)

        self.assertNotIn('auth_user', self.described_tables)
        for table in ['auth_group', 'auth_permission', 'auth_user_groups', 'qa_testlist', 'units_unit']:
            self.assertIn(table, self.described_tables)
