"""Tests for the staged-upload sweep, and the lines it must never cross.

Everything outside ``uploads/tmp`` is part of the clinical record, so most of
these tests are about what the command leaves alone rather than what it removes.
"""

import datetime
import os
import shutil
import sys
import tempfile
import time
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from qatrack.attachments.models import Attachment
from qatrack.qa import models as qam
from qatrack.qa.tests import utils


@override_settings(AUTOSAVE_DAYS_TO_KEEP=30, SESSION_COOKIE_AGE=14 * 24 * 60 * 60)
class TestCleanStagedAttachments(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        media = os.path.join(self.base, 'media')
        uploads = os.path.join(media, 'uploads')
        self.tmp = os.path.join(uploads, 'tmp')
        os.makedirs(self.tmp)
        self.settings_override = override_settings(MEDIA_ROOT=media, UPLOAD_ROOT=uploads, TMP_UPLOAD_ROOT=self.tmp)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.base, True)
        self.uploads = uploads
        self.user = User.objects.create_user('uploader', password='x')

    # helpers

    def _age_file(self, path, days_old):
        then = time.time() - days_old * 24 * 60 * 60
        os.utime(path, (then, then))

    def _staged(self, days_old, name='abandoned.txt'):
        attachment = Attachment.objects.create(
            attachment=ContentFile(b'x' * 1024, name=name),
            label=name,
            created_by=self.user,
        )
        assert attachment.is_in_tmp and not attachment.has_owner
        # `created` is auto_now_add, so it is set behind the model's back.
        Attachment.objects.filter(pk=attachment.pk).update(created=timezone.now() - datetime.timedelta(days=days_old))
        self._age_file(attachment.attachment.path, days_old)
        attachment.refresh_from_db()
        return attachment

    def _loose_file(self, folder, name, days_old):
        path = os.path.join(folder, name)
        with open(path, 'wb') as f:
            f.write(b'record')
        self._age_file(path, days_old)
        return path

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('clean_staged_attachments', *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    # the boundary

    def test_the_boundary_is_the_autosave_window_plus_the_margin(self):
        assert 'more than 37 days ago' in self._run()

    @override_settings(SESSION_COOKIE_AGE=60 * 24 * 60 * 60)
    def test_a_longer_login_session_pushes_the_boundary_out(self):
        """A page left open can be submitted for as long as the session lasts."""
        assert 'more than 67 days ago' in self._run()

    def test_files_newer_than_the_cutoff_are_kept(self):
        inside_window = self._staged(days_old=29)
        inside_margin = self._staged(days_old=35, name='margin.txt')
        self._run('--delete')
        for attachment in (inside_window, inside_margin):
            assert Attachment.objects.filter(pk=attachment.pk).exists()
            assert os.path.exists(attachment.attachment.path)

    def test_a_negative_margin_is_refused(self):
        with pytest.raises(CommandError):
            self._run('--margin-days', '-1')

    def test_the_margin_can_be_set(self):
        old = self._staged(days_old=35)
        self._run('--margin-days', '0', '--delete')
        assert not Attachment.objects.filter(pk=old.pk).exists()

    # reporting and deleting

    def test_it_only_reports_by_default(self):
        old = self._staged(days_old=40)
        loose = self._loose_file(self.tmp, 'loose.txt', days_old=40)
        output = self._run()
        assert Attachment.objects.filter(pk=old.pk).exists(), 'a report deleted a row'
        assert os.path.exists(old.attachment.path), 'a report deleted a file'
        assert os.path.exists(loose)
        assert 'Report only' in output
        assert '2 abandoned staged upload(s)' in output, output

    def test_abandoned_staged_uploads_are_removed_with_delete(self):
        old = self._staged(days_old=40)
        path = old.attachment.path
        loose = self._loose_file(self.tmp, 'loose.txt', days_old=40)
        self._run('--delete')
        assert not Attachment.objects.filter(pk=old.pk).exists()
        assert not os.path.exists(path), 'the row went but the file stayed'
        assert not os.path.exists(loose)

    def test_a_staged_row_whose_file_is_already_gone_is_removed(self):
        old = self._staged(days_old=40)
        os.remove(old.attachment.path)
        self._run('--delete')
        assert not Attachment.objects.filter(pk=old.pk).exists()

    def test_an_empty_staging_folder_says_so(self):
        assert 'No abandoned staged uploads found.' in self._run()

    # what must never be touched

    def test_files_outside_the_staging_folder_are_never_touched(self):
        record_dir = os.path.join(self.uploads, 'testinstance', '1')
        os.makedirs(record_dir)
        record = self._loose_file(record_dir, 'record.pdf', days_old=4000)
        beside = self._loose_file(self.uploads, 'beside.txt', days_old=4000)
        nested_dir = os.path.join(self.tmp, 'nested')
        os.makedirs(nested_dir)
        nested = self._loose_file(nested_dir, 'nested.txt', days_old=4000)
        self._run('--delete')
        assert os.path.exists(record)
        assert os.path.exists(beside)
        assert os.path.exists(nested), 'went into a folder inside staging'
        assert os.path.isdir(nested_dir)

    def test_a_symlink_out_of_staging_is_not_followed_or_deleted(self):
        outside_dir = os.path.join(self.base, 'elsewhere')
        os.makedirs(outside_dir)
        target_file = self._loose_file(outside_dir, 'record.pdf', days_old=4000)
        file_link = os.path.join(self.tmp, 'file_link.pdf')
        dir_link = os.path.join(self.tmp, 'dir_link')
        try:
            os.symlink(target_file, file_link)
            os.symlink(outside_dir, dir_link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip('this account cannot create symbolic links')

        output = self._run('--delete')

        assert os.path.exists(target_file), 'deleted a file outside staging through a link'
        assert os.path.islink(file_link), 'removed the link itself'
        assert os.path.islink(dir_link)
        assert 'not a plain file' in output

    def test_anything_seen_as_a_link_is_left_alone(self):
        """The link guard itself, for machines where links cannot be created.

        Windows only lets privileged accounts make symbolic links, so the test
        above skips there; this one checks the same guard by telling the
        command that an old, otherwise removable file is a link.
        """
        old = self._staged(days_old=400)
        path = old.attachment.path
        target = 'qatrack.attachments.management.commands.clean_staged_attachments._is_link'
        with mock.patch(target, side_effect=lambda p: os.path.basename(p) == os.path.basename(path)):
            output = self._run('--delete')
        assert os.path.exists(path)
        assert 'not a plain file' in output

    @pytest.mark.skipif(sys.platform != 'win32', reason='junctions are a Windows feature')
    def test_a_junction_out_of_staging_is_not_followed(self):
        import _winapi

        outside_dir = os.path.join(self.base, 'elsewhere')
        os.makedirs(outside_dir)
        target_file = self._loose_file(outside_dir, 'record.pdf', days_old=4000)
        junction = os.path.join(self.tmp, 'junction')
        _winapi.CreateJunction(outside_dir, junction)

        self._run('--delete')

        assert os.path.exists(target_file)
        assert os.path.isjunction(junction)

    def test_a_staged_file_of_a_saved_attachment_is_kept(self):
        """A row with an owner is a record, even if its move out of staging failed."""
        old = self._staged(days_old=400)
        test = utils.create_test()
        # Set the owner without save(), which would move the file out of staging.
        Attachment.objects.filter(pk=old.pk).update(test=test)
        output = self._run('--delete')
        assert Attachment.objects.filter(pk=old.pk).exists()
        assert os.path.exists(old.attachment.path)
        assert 'belongs to a saved record' in output

    def test_finalized_attachments_are_never_touched(self):
        test = utils.create_test()
        attachment = Attachment.objects.create(
            attachment=ContentFile(b'record', name='record.txt'),
            label='record.txt',
            test=test,
            created_by=self.user,
        )
        assert attachment.finalized
        Attachment.objects.filter(pk=attachment.pk).update(created=timezone.now() - datetime.timedelta(days=4000))
        self._age_file(attachment.attachment.path, 4000)
        self._run('--delete')
        assert Attachment.objects.filter(pk=attachment.pk).exists()
        assert os.path.exists(attachment.attachment.path)

    def test_an_upload_a_resumable_autosave_refers_to_is_kept(self):
        """The autosave clock runs from its last change, not from the upload.

        So an upload staged long ago can still be wanted by an autosave that was
        touched recently, and the age of the upload alone is not enough.
        """
        old = self._staged(days_old=400)
        utc = utils.create_unit_test_collection()
        qam.AutoSave.objects.create(
            unit_test_collection=utc,
            test_list=utc.tests_object,
            created_by=self.user,
            modified_by=self.user,
            # Upload tests store the attachment id as their value.
            data={'tests': {'upload_test': str(old.pk), 'numeric': 1.5}},
        )
        self._run('--delete')
        assert Attachment.objects.filter(pk=old.pk).exists()
        assert os.path.exists(old.attachment.path)

    def test_a_staging_folder_that_holds_the_records_is_refused(self):
        with override_settings(TMP_UPLOAD_ROOT=self.uploads):
            with pytest.raises(CommandError):
                self._run('--delete')
