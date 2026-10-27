import re
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django_auth_adfs.backend import AdfsAuthCodeBackend

from qatrack.accounts import models
from qatrack.accounts.admin import AdminFilter
from qatrack.accounts.backends import ActiveDirectoryGroupMembershipSSLBackend as ADBack
from qatrack.accounts.backends import (
    QATrackAccountBackend,
    QATrackAdfsAuthCodeBackend,
)
from qatrack.qa.tests import utils


class TestCleanUsername:

    def test_no_clean(self):
        ldap = pytest.importorskip("ldap")  # noqa:F841,F811
        backend = ADBack()
        assert backend.clean_username("foo") == "foo"

    @override_settings(AD_CLEAN_USERNAME=lambda x: x.lower())
    def test_clean(self):
        ldap = pytest.importorskip("ldap")  # noqa:F841,F811
        backend = ADBack()
        assert backend.clean_username("Foo") == "foo"

    @override_settings(AD_CLEAN_USERNAME=None, AD_CLEAN_USERNAME_STRING="Foo/")
    def test_replace(self):
        ldap = pytest.importorskip("ldap")  # noqa:F841,F811
        backend = ADBack()
        assert backend.clean_username("Foo/bar") == "bar"

    @override_settings(ACCOUNTS_CLEAN_USERNAME=lambda u: u.lower())
    def test_accounts_clean(self):
        backend = QATrackAccountBackend()
        assert backend.clean_username("UserName") == "username"


class TestAdminFilter(TestCase):

    def test_lookups(self):
        assert AdminFilter.lookups(None, None, None) == (('yes', 'Yes'), ('no', 'No'))

    def test_queryset_yes(self):
        utils.create_user(uname="admin", is_staff=True, is_superuser=True)
        utils.create_user(uname="reg", is_staff=False, is_superuser=False)
        af = AdminFilter(None, [], None, None)
        af.value = lambda: 'yes'
        assert af.queryset(None, User.objects.all()).count() == 1

    def test_queryset_no(self):
        utils.create_user(uname="admin", is_staff=True, is_superuser=True)
        utils.create_user(uname="reg", is_staff=False, is_superuser=False)
        af = AdminFilter(None, [], None, None)
        af.value = lambda: 'no'
        assert af.queryset(None, User.objects.all()).count() == 1 + 1  # count Internal User


class TestADFSBackend(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("user")
        self.group1 = Group.objects.create(name="group1")
        self.group2 = Group.objects.create(name="group2")
        from django_auth_adfs.config import settings as adfs_settings
        adfs_settings.MIRROR_GROUPS = False

    def test_update_user_groups(self):

        be = QATrackAdfsAuthCodeBackend()
        claims = {'group': [self.group1.name, self.group2.name]}

        be.update_user_groups(self.user, claims)
        assert list(sorted(self.user.groups.values_list("pk", flat=True))) == list(
            sorted([self.group1.pk, self.group2.pk]),
        )

    def test_update_user_groups_with_mirror(self):

        claims = {'group': ['mirrored', self.group1.name, self.group2.name]}

        be = QATrackAdfsAuthCodeBackend()
        from django_auth_adfs.config import settings as adfs_settings
        adfs_settings.MIRROR_GROUPS = True
        be.update_user_groups(self.user, claims)
        g = Group.objects.get(name="mirrored")
        assert sorted(self.user.groups.values_list("pk", flat=True)) == sorted([self.group1.pk, self.group2.pk, g.pk])

    def test_update_user_groups_extra_no_mirror(self):

        be = QATrackAdfsAuthCodeBackend()
        claims = {'group': [self.group1.name, self.group2.name, 'donotcreate']}
        be.update_user_groups(self.user, claims)
        assert sorted(self.user.groups.values_list("pk", flat=True)) == sorted([self.group1.pk, self.group2.pk])

    def test_update_user_groups_existing_group(self):

        self.user.groups.add(self.group1)
        be = QATrackAdfsAuthCodeBackend()
        claims = {'group': [self.group2.name]}
        be.update_user_groups(self.user, claims)
        assert list(self.user.groups.order_by("name")) == [self.group1, self.group2]

    def test_update_with_map(self):

        claims = {'group': ['ad group 1']}
        m1 = models.ActiveDirectoryGroupMap.objects.create(ad_group='ad group 1')
        m1.groups.add(self.group1)
        m1.groups.add(self.group2)
        be = QATrackAdfsAuthCodeBackend()
        be.update_user_groups(self.user, claims)
        expected = list(sorted([self.group1.pk, self.group2.pk]))
        assert list(sorted(self.user.groups.values_list("pk", flat=True))) == expected

    def test_update_with_default_map(self):

        claims = {'group': ['ad group 1']}
        m1 = models.ActiveDirectoryGroupMap.objects.create(ad_group='ad group 1')
        m1.groups.add(self.group1)

        models.DefaultGroup.objects.create(group=self.group2)

        be = QATrackAdfsAuthCodeBackend()
        be.update_user_groups(self.user, claims)
        expected = list(sorted([self.group1.pk, self.group2.pk]))
        assert list(sorted(self.user.groups.values_list("pk", flat=True))) == expected


class TestADFSCreateUser(TestCase):

    def setUp(self):
        from django_auth_adfs.config import settings as adfs_settings
        adfs_settings.MIRROR_GROUPS = False
        self.backend = QATrackAdfsAuthCodeBackend()

    def claims(self, **over):
        c = {
            "winaccountname": "jdoe",
            "given_name": "Jane", "family_name": "Doe",
            "email": "jdoe@example.com",
            "group": ["Physicists"],
        }
        c.update(over)
        return c

    def test_no_qualifying_groups_lets_anyone_in(self):
        # No account_qualifier groups defined -> gate is skipped
        user = self.backend.create_user(self.claims())
        assert user.username == "jdoe"

    def test_qualifying_group_match_allowed(self):
        models.ActiveDirectoryGroupMap.objects.create(
            ad_group="Physicists", account_qualifier=True,
        )
        user = self.backend.create_user(self.claims(group=["Physicists"]))
        assert user.username == "jdoe"

    def test_qualifying_group_mismatch_denied(self):
        models.ActiveDirectoryGroupMap.objects.create(
            ad_group="Admins", account_qualifier=True,
        )
        with self.assertRaises(PermissionDenied):
            self.backend.create_user(self.claims(group=["Physicists"]))

    @override_settings(ACCOUNTS_CLEAN_USERNAME=lambda u: u.lower())
    def test_username_cleaned_on_create(self):
        user = self.backend.create_user(self.claims(winaccountname="JDoe"))
        assert user.username == "jdoe"

    def test_claim_mapping_populates_user_attributes(self):
        # CLAIM_MAPPING (first_name/last_name/email) is applied by the parent
        user = self.backend.create_user(self.claims())
        self.backend.update_user_attributes(user, self.claims())
        assert user.first_name == "Jane"
        assert user.last_name == "Doe"
        assert user.email == "jdoe@example.com"

    def test_authenticate_returns_none_on_permission_denied(self):
        # QATrack+ overrides authenticate to swallow PermissionDenied -> None
        with mock.patch.object(AdfsAuthCodeBackend, "authenticate", side_effect=PermissionDenied):
            assert self.backend.authenticate(authorization_code="x") is None


REQUIREJS_CONFIG = 'requirejs/js/requirejs-config.js'


def requirejs_paths():
    """Map each RequireJS module name to the static path it is configured with."""
    with open(finders.find(REQUIREJS_CONFIG)) as f:
        config = f.read()
    return {
        name.strip("'\""): path
        for name, path in re.findall(r"""([\w.'"/-]+):\s*siteConfig\.STATIC_URL\s*\+\s*'([^']+)'""", config)
    }


def missing_static_files(html):
    """Return the static files referenced by ``html`` (directly, or via require([...])) that don't exist."""
    paths = requirejs_paths()
    static_url = settings.STATIC_URL
    wanted = set()
    for attr_url in re.findall(r"""(?:src|href)=["']([^"']+)["']""", html):
        if attr_url.startswith(static_url):
            wanted.add(attr_url[len(static_url):].split('?')[0])
    for module_list in re.findall(r"require\(\s*\[([^\]]*)\]", html):
        for module in re.findall(r"""['"]([^'"]+)['"]""", module_list):
            if module.startswith(static_url):
                wanted.add(module[len(static_url):].split('?')[0])
            elif module in paths and not paths[module].endswith('/'):
                wanted.add(paths[module] + '.js')
            elif module not in paths:
                wanted.add('<unconfigured requirejs module %s>' % module)
    return sorted(p for p in wanted if not finders.find(p))


class TestPasswordPagesStaticFiles(TestCase):
    """The password pages used to require zxcvbn/password_strength, which 404'd (no package provides them)."""

    def setUp(self):
        self.user = utils.create_user(is_superuser=True, uname='pwuser', pwd='pwd')
        self.client.login(username='pwuser', password='pwd')

    def test_admin_password_change_references_existing_static_files(self):
        resp = self.client.get(reverse('admin:password_change'))
        assert resp.status_code == 200
        assert 'registration/password_change_form.html' in [t.name for t in resp.templates]
        html = resp.content.decode()
        assert 'zxcvbn' not in html
        assert missing_static_files(html) == []

    def test_account_password_change_references_existing_static_files(self):
        resp = self.client.get(reverse('account-change-password'))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'zxcvbn' not in html
        assert missing_static_files(html) == []

    def test_password_templates_only_require_existing_modules(self):
        # registration_form.html is only reachable with ACCOUNTS_SELF_REGISTER, so check the template sources too
        for name in (
            'registration/password_change_form.html',
            'registration/password_reset_confirm.html',
            'registration/registration_form.html',
        ):
            source = get_template(name).template.source
            assert missing_static_files(source) == [], name

    def test_requirejs_config_has_no_zxcvbn_modules(self):
        assert 'zxcvbn' not in requirejs_paths()
        assert 'password_strength' not in requirejs_paths()

    def test_change_password_still_works(self):
        resp = self.client.post(reverse('account-change-password'), {
            'old_password': 'pwd',
            'new_password1': 'a-Much-Longer-pass-42',
            'new_password2': 'a-Much-Longer-pass-42',
        })
        assert resp.status_code == 302
        self.user.refresh_from_db()
        assert self.user.check_password('a-Much-Longer-pass-42')
