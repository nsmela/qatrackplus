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
