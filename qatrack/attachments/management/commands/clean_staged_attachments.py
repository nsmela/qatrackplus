"""Find, and when asked remove, staged uploads nobody can still be using.

When someone attaches a file while performing QC, the file is written to the
staging folder ``MEDIA_ROOT/uploads/tmp`` straight away and an ``Attachment``
row with no owner is created for it. When the test list is submitted the row is
given its owner and the file is moved to its permanent home under
``uploads/<type>/<id>/``. If the form is abandoned instead, the row and the file
stay in staging, and nothing else in QATrack+ ever removes them, so the folder
only grows.

**Everything outside the staging folder is part of the clinical record and is
never touched by this command.** Inside the staging folder it is still
cautious. A file is kept if:

* it is a symbolic link, a junction, a folder, or anything other than a plain
  file (links are never followed, so nothing outside staging can be reached);
* any attachment that belongs to a saved record points at it;
* an autosave that a user could still resume refers to it;
* it, or its attachment row, is newer than the cut-off.

By default the command only reports what it would remove. Nothing is deleted
unless ``--delete`` is given, and every removal is written to the QATrack+ log.
"""

import datetime
import logging
import math
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from qatrack.attachments.models import Attachment
from qatrack.qa.models import AutoSave

logger = logging.getLogger('qatrack')

# Extra days on top of the longest window in which a staged upload could still
# be wanted (see `boundary_days` below). Nothing is lost by waiting a few more
# days; a record could be lost by not.
DEFAULT_MARGIN_DAYS = 7

OWNER_ID_FIELDS = ['%s_id' % name for name in Attachment.OWNER_MODELS]


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _is_link(path):
    """True for a symbolic link or a Windows junction."""
    return os.path.islink(path) or os.path.isjunction(path)


def _is_inside(path, folder):
    """True when `path` is strictly inside `folder` (both already normalised)."""
    try:
        return path != folder and os.path.commonpath([path, folder]) == folder
    except ValueError:  # different drives on Windows
        return False


def _ids_in(value, found):
    """Collect every value in an autosave payload that could be an attachment id.

    Upload tests store their attachment id as the test's value, which looks just
    like a numeric result, so every whole number is collected. Keeping a few
    files we did not need to is harmless; deleting one a user is about to
    resume is not.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        found.add(value)
    elif isinstance(value, float) and value.is_integer():
        found.add(int(value))
    elif isinstance(value, str) and value.strip().isdigit():
        found.add(int(value.strip()))
    elif isinstance(value, dict):
        for v in value.values():
            _ids_in(v, found)
    elif isinstance(value, list | tuple):
        for v in value:
            _ids_in(v, found)


class Command(BaseCommand):
    help = (
        'Report, and with --delete remove, abandoned staged uploads in MEDIA_ROOT/uploads/tmp. '
        'Only plain files directly inside uploads/tmp are ever considered: nothing else under the media '
        'folder is touched, links are never followed, and a file is always kept if a saved attachment or '
        'a resumable autosave refers to it, or if it is newer than the cut-off. Reports only unless '
        '--delete is given.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--margin-days',
            type=int,
            default=DEFAULT_MARGIN_DAYS,
            help=(
                'Extra days to wait beyond AUTOSAVE_DAYS_TO_KEEP (or the login session length, if that is '
                'longer) before a staged upload counts as abandoned (default %d).' % DEFAULT_MARGIN_DAYS
            ),
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Actually remove the abandoned staged uploads. Without this the command only reports.',
        )

    def handle(self, *args, **options):
        margin = options['margin_days']
        if margin < 0:
            raise CommandError('--margin-days cannot be negative.')

        tmp_root = self.staging_folder()
        cutoff, boundary_days = self.cutoff(margin)

        self.stdout.write('Staging folder: %s' % tmp_root)
        self.stdout.write(
            'Anything staged more than %d days ago (before %s) that nothing refers to counts as abandoned.'
            % (boundary_days, cutoff.isoformat(timespec='seconds'))
        )

        if not os.path.isdir(tmp_root):
            self.stdout.write(self.style.SUCCESS('The staging folder does not exist, so there is nothing to do.'))
            return

        in_autosave = self.ids_in_autosaves()
        rows_by_file, rowless_staged = self.staged_rows(tmp_root)

        candidates = []  # (path or None, [row pks], size)
        seen = set()
        for entry in os.scandir(tmp_root):
            path = _norm(entry.path)
            seen.add(path)
            if _is_link(entry.path) or not entry.is_file(follow_symlinks=False):
                self.stdout.write('Skipping %s: not a plain file, so it is left alone.' % entry.path)
                continue

            rows = rows_by_file.get(path, [])
            if any(row['owned'] for row in rows):
                self.stdout.write(
                    self.style.WARNING(
                        'Keeping %s: it belongs to a saved record but was never moved out of staging. '
                        'Please look into this one by hand.' % entry.path
                    )
                )
                continue
            if any(row['pk'] in in_autosave for row in rows):
                continue

            stat = entry.stat(follow_symlinks=False)
            modified = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC)
            if modified >= cutoff or any(row['created'] >= cutoff for row in rows):
                continue

            candidates.append((entry.path, [row['pk'] for row in rows], stat.st_size))

        # Staging rows whose file has already gone: the row is all that is left.
        for path, rows in rows_by_file.items():
            if path in seen:
                continue
            if any(row['owned'] or row['pk'] in in_autosave or row['created'] >= cutoff for row in rows):
                continue
            candidates.append((None, [row['pk'] for row in rows], 0))
        for row in rowless_staged:
            if row['pk'] not in in_autosave and row['created'] < cutoff:
                candidates.append((None, [row['pk']], 0))

        if not candidates:
            self.stdout.write(self.style.SUCCESS('No abandoned staged uploads found.'))
            return

        total = sum(size for _, _, size in candidates)
        self.stdout.write('%d abandoned staged upload(s), %.1f MiB:' % (len(candidates), total / (1024 * 1024)))
        for path, pks, _ in candidates:
            self.stdout.write('  %s%s' % (path or '(file already gone)', self.describe_rows(pks)))

        if not options['delete']:
            self.stdout.write(self.style.WARNING('Report only: nothing was removed. Pass --delete to remove these.'))
            return

        self.remove(candidates, tmp_root)

    def staging_folder(self):
        """The real path of the staging folder, after checking it is a sensible one.

        A misconfigured TMP_UPLOAD_ROOT that pointed at the media or uploads
        folder itself would turn a staging sweep into a sweep of records, so
        refuse to run at all in that case.
        """
        tmp_root = _norm(os.path.realpath(settings.TMP_UPLOAD_ROOT))
        for name in ('MEDIA_ROOT', 'UPLOAD_ROOT'):
            protected = _norm(os.path.realpath(getattr(settings, name)))
            if tmp_root == protected or _is_inside(protected, tmp_root):
                raise CommandError(
                    'TMP_UPLOAD_ROOT (%s) is the same as, or contains, %s (%s). Refusing to run, because '
                    'that would put permanent records within reach of this command.' % (tmp_root, name, protected)
                )
        return tmp_root

    def cutoff(self, margin):
        """When a staged upload stops being something anyone could still use.

        A user can come back to an autosave for AUTOSAVE_DAYS_TO_KEEP days after
        it was last changed, and a page left open can be submitted for as long
        as the login session lasts. Autosaves still in the database are checked
        separately, so this window mainly guards the gaps between those clocks.
        """
        keep_days = getattr(settings, 'AUTOSAVE_DAYS_TO_KEEP', 30)
        session_days = math.ceil(getattr(settings, 'SESSION_COOKIE_AGE', 0) / (24 * 60 * 60))
        boundary_days = max(keep_days, session_days) + margin
        return timezone.now() - datetime.timedelta(days=boundary_days), boundary_days

    def ids_in_autosaves(self):
        found = set()
        for data in AutoSave.objects.values_list('data', flat=True).iterator():
            _ids_in(data, found)
        return found

    def staged_rows(self, tmp_root):
        """Attachment rows whose file name points into the staging folder.

        Returns a mapping of normalised file path to rows, plus unowned rows
        with no file name at all (which can only ever be staging leftovers).
        """
        storage = Attachment._meta.get_field('attachment').storage
        by_file = {}
        rowless = []
        for values in Attachment.objects.values('pk', 'attachment', 'created', *OWNER_ID_FIELDS).iterator():
            row = {
                'pk': values['pk'],
                'created': values['created'],
                'owned': any(values[f] is not None for f in OWNER_ID_FIELDS),
            }
            name = values['attachment']
            if not name:
                if not row['owned']:
                    rowless.append(row)
                continue
            # Resolve the folder the same way the staging folder was resolved,
            # so a media folder reached through a link still matches up.
            # Only files directly inside staging are considered, as that is the
            # only place QATrack+ stages uploads.
            full = storage.path(name)
            path = _norm(os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full)))
            if os.path.dirname(path) == tmp_root:
                by_file.setdefault(path, []).append(row)
        return by_file, rowless

    def describe_rows(self, pks):
        if not pks:
            return ' (no attachment row)'
        return ' (staged attachment %s)' % ', '.join(str(pk) for pk in pks)

    def remove(self, candidates, tmp_root):
        removed_rows = removed_files = 0
        failures = 0
        unowned = {'%s__isnull' % name: True for name in Attachment.OWNER_MODELS}
        for path, pks, _ in candidates:
            if pks:
                # Delete only rows that are still unowned: if someone submitted
                # the form a moment ago, the row now belongs to a record and the
                # file has been moved, so both are left alone.
                with transaction.atomic():
                    deleted = (
                        Attachment.objects.filter(pk__in=pks, **unowned).delete()[1].get(Attachment._meta.label, 0)
                    )
                removed_rows += deleted
                if deleted:
                    logger.info('clean_staged_attachments: removed staged attachment row(s) %s', pks)
                if deleted != len(pks):
                    self.stdout.write(
                        'Keeping %s: it was claimed by a record while this ran.' % (path or self.describe_rows(pks))
                    )
                    continue

            if path is None:
                continue

            # Check once more, right before removing, that this is still a plain
            # file directly inside the staging folder and not a link.
            if _is_link(path) or not os.path.isfile(path) or os.path.dirname(_norm(os.path.realpath(path))) != tmp_root:
                self.stdout.write('Keeping %s: it is no longer a plain file in the staging folder.' % path)
                continue
            try:
                os.remove(path)
            except OSError as e:
                failures += 1
                self.stderr.write(self.style.ERROR('Could not remove %s: %s' % (path, e)))
                continue
            removed_files += 1
            logger.info('clean_staged_attachments: removed staged file %s', path)

        self.stdout.write(
            self.style.SUCCESS('Removed %d staged attachment row(s) and %d file(s).' % (removed_rows, removed_files))
        )
        if failures:
            raise CommandError('%d staged file(s) could not be removed; see the messages above.' % failures)
