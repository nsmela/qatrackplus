"""The admin home page and the per-app admin pages list the apps/models.

The home page's model list was removed upstream ("Removed main column in
admin", 26580c2a) because the nav sidebar lists the same apps. That left the
home page with no navigation where Django hides the sidebar (below 768px wide)
or when the user collapses it, and left /admin/<app>/ pages completely empty
(app_index.html extends index.html). The list is back; on the home page it is
hidden only while the nav sidebar is open on a wide window.
"""
import re

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user


def _content_main(html):
    match = re.search(r'<div id="content-main"([^>]*)>(.*?)</div>\s*<div id="content-related"', html, flags=re.S)
    if match is None:
        # app pages have no Recent Actions column
        match = re.search(r'<div id="content-main"([^>]*)>(.*)', html, flags=re.S)
    assert match is not None, "no #content-main on the page"
    return match.group(1), match.group(2)


class TestAdminIndexAppList(TestCase):

    def setUp(self):
        create_user(pwd="password")
        self.client.login(username="user", password="password")

    def test_index_lists_apps(self):
        resp = self.client.get(reverse("admin:index"))
        assert resp.status_code == 200
        attrs, body = _content_main(resp.content.decode())
        assert reverse("admin:app_list", args=("qa",)) in body
        assert reverse("admin:qa_testlist_changelist") in body
        assert reverse("admin:qa_testlist_add") in body
        # Home page only: hidden while the (equivalent) nav sidebar is open.
        assert 'class="qa-home-app-list"' in attrs

    def test_index_hides_list_only_beside_open_sidebar(self):
        html = self.client.get(reverse("admin:index")).content.decode()
        css = re.search(r"@media \(min-width: 768px\)\s*\{\s*\.main\.shifted \.qa-home-app-list\s*\{([^}]*)\}", html)
        assert css is not None
        assert "display: none" in css.group(1)

    def test_app_index_lists_models(self):
        resp = self.client.get(reverse("admin:app_list", args=("qa",)))
        assert resp.status_code == 200
        html = resp.content.decode()
        attrs, body = _content_main(html)
        assert reverse("admin:qa_testlist_changelist") in body
        assert reverse("admin:qa_test_changelist") in body
        # Always shown on app pages, and full width (no Recent Actions column).
        assert "qa-home-app-list" not in attrs
        assert re.search(r'id="content"\s+class="colM"', html)
        # Only this app's models are listed in the content.
        assert reverse("admin:auth_user_changelist") not in body

    def test_staff_without_permissions_is_told_so(self):
        create_user(is_superuser=False, uname="noperms", pwd="password")
        self.client.logout()
        self.client.login(username="noperms", password="password")
        resp = self.client.get(reverse("admin:index"))
        assert resp.status_code == 200
        assert "have permission to view or edit anything" in resp.content.decode()
