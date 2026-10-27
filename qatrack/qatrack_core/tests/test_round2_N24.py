"""Guard tests for the retired ``drag_admin.js`` and ``jquery-1.7.1.min.js`` admin scripts.

Both files used to live in ``qatrack/admin_media/js/`` but nothing loaded them
any more (the admin pages get jQuery from Django's own admin and drag-and-drop
from ``m2m_drag_admin.js``), so they were removed. These tests make sure no
template or Python module starts pointing at them again, and that every JS/CSS
file listed by any app's admin ``Media`` still resolves through staticfiles.
"""

import os
import re

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

RETIRED_FILES = ('drag_admin.js', 'jquery-1.7.1.min.js')

# Match ``drag_admin.js`` on a boundary so ``m2m_drag_admin.js`` doesn't count.
RETIRED_PATTERN = re.compile(r'(?<![\w-])(?:drag_admin\.js|jquery-1\.7\.1)')


def _media_paths(media):
    """Return every JS and CSS path a Django ``Media`` object refers to."""
    paths = [getattr(js, 'path', js) for js in media._js]
    for css_paths in media._css.values():
        paths.extend(getattr(css, 'path', css) for css in css_paths)
    return [str(p) for p in paths]


def _all_admin_media():
    """Yield (name, Media) for every registered admin, its inlines and its form widgets, across all apps."""
    for model, model_admin in admin.site._registry.items():
        name = '%s.%s' % (type(model_admin).__module__, type(model_admin).__name__)
        yield name, model_admin.media
        form = getattr(model_admin, 'form', None)
        for field_name, field in getattr(form, 'base_fields', {}).items():
            yield '%s.form.%s' % (name, field_name), field.widget.media
        for inline_cls in model_admin.inlines:
            yield '%s.%s' % (inline_cls.__module__, inline_cls.__name__), inline_cls(model, admin.site).media


class TestRetiredAdminScripts(SimpleTestCase):

    def test_retired_files_removed(self):
        for filename in RETIRED_FILES:
            self.assertFalse(
                os.path.exists(os.path.join(settings.PROJECT_ROOT, 'admin_media', 'js', filename)),
                filename,
            )

    def test_retired_files_not_referenced(self):
        """No template, Python module or JS file (outside collected static output) loads the retired scripts."""
        root = settings.PROJECT_ROOT
        # qatrack/static is gitignored collectstatic output and may hold stale copies
        collected = os.path.join(root, 'static')
        skip_dirs = {'__pycache__', 'node_modules'}
        offenders = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and os.path.join(dirpath, d) != collected]
            for filename in filenames:
                if not filename.endswith(('.html', '.py', '.js', '.txt')) or filename == os.path.basename(__file__):
                    continue
                full = os.path.join(dirpath, filename)
                with open(full, encoding='utf-8', errors='ignore') as f:
                    if RETIRED_PATTERN.search(f.read()):
                        offenders.append(os.path.relpath(full, root))
        self.assertEqual(offenders, [])

    def test_pattern_ignores_m2m_drag_admin(self):
        self.assertIsNone(RETIRED_PATTERN.search("'js/m2m_drag_admin.js'"))
        self.assertIsNotNone(RETIRED_PATTERN.search("'js/drag_admin.js'"))
        self.assertIsNotNone(RETIRED_PATTERN.search("'js/jquery-1.7.1.min.js'"))

    def test_all_admin_media_files_resolve(self):
        """Every JS/CSS file listed in any app's admin Media (admins, inlines, form widgets) is findable."""
        checked = 0
        missing = []
        for name, media in _all_admin_media():
            for path in _media_paths(media):
                if path.startswith(('http://', 'https://', '//', '/')):
                    continue
                checked += 1
                if not finders.find(path):
                    missing.append('%s: %s' % (name, path))
                if RETIRED_PATTERN.search(path):
                    missing.append('%s: retired %s' % (name, path))
        self.assertGreater(checked, 0, 'No admin Media files were found to check')
        self.assertEqual(missing, [])
