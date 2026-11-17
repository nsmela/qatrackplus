"""Checks on the local_settings.py templates a native install copies from deploy/.

A site's settings start as a copy of one of these files, so a mistake here is
copied onto every new install and lingers there long after it is fixed in the
template. The files are read with ``ast`` so that commented-out examples are
ignored and only real assignments count, the same approach as
``test_test_settings_templates.py``.
"""

import ast
import pathlib

from django.test import SimpleTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY_DIR = REPO_ROOT / 'deploy'

LINUX_TEMPLATES = [DEPLOY_DIR / name / 'local_settings.py' for name in ('mysql', 'postgres', 'sqlite')]
WINDOWS_TEMPLATE = DEPLOY_DIR / 'win' / 'local_settings.py'


def _assignments(path):
    """{name: ast value node} for every top-level `NAME = ...` in the file."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
    return found


def _rel(path):
    return path.relative_to(REPO_ROOT).as_posix()


class TestDeploySettingsTemplates(SimpleTestCase):

    def test_templates_were_found_at_all(self):
        """Guard the guard: a move must not leave this file vacuous."""
        missing = [_rel(p) for p in LINUX_TEMPLATES + [WINDOWS_TEMPLATE] if not p.exists()]
        assert not missing, 'settings templates not found: %r' % missing

    def test_linux_templates_trust_only_https_origins(self):
        """#784: a plain-HTTP site needs no entry, so the templates shouldn't suggest one.

        Behind Nginx the Host header is passed through, and Django accepts an Origin
        that matches the request's own scheme and host. An http:// entry is only
        needed behind a proxy that rewrites Host, which the comment in each template
        explains. Windows is different on purpose and is not checked here.
        """
        offenders = []
        for path in LINUX_TEMPLATES:
            value = _assignments(path).get('CSRF_TRUSTED_ORIGINS')
            if value is None:
                offenders.append((_rel(path), 'CSRF_TRUSTED_ORIGINS not set'))
                continue
            origins = ast.literal_eval(value)
            offenders.extend((_rel(path), o) for o in origins if not o.startswith('https://'))
        assert not offenders, 'these templates trust non-https origins: %r' % offenders

    def test_no_obsolete_settings(self):
        """#849: settings nothing reads, or that only repeat a deprecated default.

        EMAIL_NOTIFICATION_USER/PWD were replaced by EMAIL_HOST_USER/PASSWORD (see the
        end of settings.py), and CONSTANT_PRECISION is deprecated in favour of
        DEFAULT_NUMBER_FORMAT and only ever repeated the default of 8.
        """
        obsolete = {'EMAIL_NOTIFICATION_USER', 'EMAIL_NOTIFICATION_PWD', 'CONSTANT_PRECISION', 'TEMPLATE_DBG'}
        offenders = []
        for path in LINUX_TEMPLATES + [WINDOWS_TEMPLATE]:
            offenders.extend((_rel(path), name) for name in sorted(obsolete & set(_assignments(path))))
        assert not offenders, 'these templates still set obsolete settings: %r' % offenders

    def test_languages_not_overridden(self):
        """#849: an override in a template drops any language added to settings.py later.

        The Windows template's copy had already lost Français (Canada).
        """
        offenders = [_rel(p) for p in LINUX_TEMPLATES + [WINDOWS_TEMPLATE] if 'LANGUAGES' in _assignments(p)]
        assert not offenders, 'these templates override LANGUAGES: %r' % offenders

    def test_dev_and_test_templates_do_not_set_template_dbg(self):
        """Nothing reads TEMPLATE_DBG; Django's template debugging follows DEBUG."""
        templates = sorted((DEPLOY_DIR / 'dev').glob('local_*settings*.py'))
        assert templates, 'no deploy/dev settings templates found'
        offenders = [_rel(p) for p in templates if 'TEMPLATE_DBG' in _assignments(p)]
        assert not offenders, 'these templates set TEMPLATE_DBG: %r' % offenders
