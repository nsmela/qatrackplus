"""Guard tests for the static files used by the QA admin pages.

These catch two kinds of mistake when tidying up ``qatrack/admin_media``:
deleting a JS/CSS file that a QA admin ``Media`` class still loads, and
leaving a template pointing at the retired Test List drag-and-drop script.
"""

import os

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

import qatrack.qa.admin  # noqa: F401  (registers the QA admins)

RETIRED_SCRIPT = 'm2m_drag_admin_testlist.js'


def _media_paths(media):
    """Return every JS and CSS path a Django ``Media`` object refers to."""
    paths = [getattr(js, 'path', js) for js in media._js]
    for css_paths in media._css.values():
        paths.extend(getattr(css, 'path', css) for css in css_paths)
    return [str(p) for p in paths]


def _qa_admin_media():
    """Yield (admin name, Media) for every admin and inline defined in qatrack.qa.admin."""
    for model, model_admin in admin.site._registry.items():
        if type(model_admin).__module__ != 'qatrack.qa.admin':
            continue
        yield type(model_admin).__name__, model_admin.media
        for inline_cls in model_admin.inlines:
            if inline_cls.__module__ == 'qatrack.qa.admin':
                yield inline_cls.__name__, inline_cls(model, admin.site).media


class TestQAAdminStaticFiles(SimpleTestCase):

    def test_qa_admin_media_files_exist(self):
        """Every JS/CSS file listed in a QA admin Media class can be found by staticfiles."""
        checked = 0
        missing = []
        for name, media in _qa_admin_media():
            for path in _media_paths(media):
                if path.startswith(('http://', 'https://', '//', '/')):
                    continue
                checked += 1
                if not finders.find(path):
                    missing.append('%s: %s' % (name, path))
        self.assertGreater(checked, 0, 'No QA admin Media files were found to check')
        self.assertEqual(missing, [])

    def test_retired_testlist_drag_script_not_referenced(self):
        """No template or Python module still loads the old Test List drag-and-drop script."""
        root = settings.PROJECT_ROOT
        # qatrack/static is gitignored collectstatic output and may hold a stale copy
        collected = os.path.join(root, 'static')
        skip_dirs = {'__pycache__', 'node_modules'}
        offenders = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in skip_dirs and os.path.join(dirpath, d) != collected
            ]
            for filename in filenames:
                if not filename.endswith(('.html', '.py', '.js')) or filename == os.path.basename(__file__):
                    continue
                full = os.path.join(dirpath, filename)
                with open(full, encoding='utf-8', errors='ignore') as f:
                    if RETIRED_SCRIPT in f.read():
                        offenders.append(os.path.relpath(full, root))
        self.assertEqual(offenders, [])

    def test_retired_testlist_drag_script_removed(self):
        self.assertIsNone(finders.find('js/%s' % RETIRED_SCRIPT))
