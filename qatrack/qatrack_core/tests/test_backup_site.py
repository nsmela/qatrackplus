"""`backup_site` must archive the uploads whatever the database step did.

The command cannot back up a PostgreSQL or MySQL database, or one on any engine
it does not know. It used to stop there, before it reached the uploads, so a
PostgreSQL site that read "Please use pg_dump" and arranged its own database
dump still had no copy of its uploaded files, and nothing said so.

It must also keep old backups whenever today's backup is incomplete, so that
nothing is deleted on the strength of a backup that is missing something.
"""

import datetime
import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class TestUploadsAreBackedUpIndependently(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.media = Path(self.root, 'media')
        (self.media / 'uploads').mkdir(parents=True)
        (self.media / 'uploads' / 'patient-qc.txt').write_text('x', encoding='utf-8')
        self.backups = Path(self.root, 'backups')

    def _run(self, engine, name='qatrackplus'):
        databases = {'default': {'ENGINE': engine, 'NAME': name}}
        out = StringIO()
        with override_settings(
            DATABASES=databases,
            MEDIA_ROOT=str(self.media),
            BACKUP_DIR=str(self.backups),
        ):
            call_command('backup_site', stdout=out, stderr=StringIO())
        return out.getvalue()

    def _uploads_zips(self):
        return sorted(self.backups.glob('*/uploads.zip'))

    def _old_daily_backup(self):
        """An old daily backup that retention would delete after a complete run."""
        old = self.backups / '2000-01-01-daily'
        old.mkdir(parents=True)
        long_ago = datetime.datetime(2000, 1, 1).timestamp()
        os.utime(old, (long_ago, long_ago))
        return old

    def test_postgresql_still_gets_its_uploads_archived(self):
        output = self._run('django.db.backends.postgresql')
        assert 'pg_dump' in output, 'the database step should still say what it cannot do'
        zips = self._uploads_zips()
        assert zips, 'no uploads archive was written for a PostgreSQL site'
        assert 'patient-qc.txt' in ZipFile(zips[0]).namelist()

    def test_postgresql_is_told_plainly_the_database_was_not_backed_up(self):
        output = self._run('django.db.backends.postgresql')
        assert 'was NOT backed up' in output

    def test_mysql_still_gets_its_uploads_archived(self):
        self._run('django.db.backends.mysql')
        assert self._uploads_zips(), 'no uploads archive was written for a MySQL site'

    def test_an_unimplemented_engine_still_gets_its_uploads_archived(self):
        self._run('django.db.backends.oracle')
        assert self._uploads_zips(), 'no uploads archive was written'

    def test_old_backups_are_kept_when_the_database_was_not_backed_up(self):
        old = self._old_daily_backup()
        output = self._run('django.db.backends.postgresql')
        assert old.exists(), 'an old backup was deleted after a run that did not back up the database'
        assert 'Old daily backups have been kept' in output

    def test_old_backups_are_removed_after_a_complete_backup(self):
        """The retention step still works once both halves succeed."""
        db = Path(self.root, 'qatrack.db')
        db.write_bytes(b'')
        old = self._old_daily_backup()
        self._run('django.db.backends.sqlite3', name=str(db))
        assert not old.exists(), 'retention did not run after a complete backup'

    def test_a_missing_uploads_directory_is_not_a_failure(self):
        """A site with no uploads yet must still be able to rotate its backups."""
        db = Path(self.root, 'qatrack.db')
        db.write_bytes(b'')
        shutil.rmtree(self.media / 'uploads')
        old = self._old_daily_backup()
        output = self._run('django.db.backends.sqlite3', name=str(db))
        assert 'does not exist' in output
        assert not old.exists()

    def test_an_unwritable_archive_is_reported_and_keeps_old_backups(self):
        db = Path(self.root, 'qatrack.db')
        db.write_bytes(b'')
        old = self._old_daily_backup()
        with mock.patch('shutil.make_archive', side_effect=OSError('disk full')):
            output = self._run('django.db.backends.sqlite3', name=str(db))
        assert 'Failed to back up uploads' in output
        assert 'disk full' in output
        assert old.exists(), 'an old backup was deleted after a run that did not back up the uploads'
