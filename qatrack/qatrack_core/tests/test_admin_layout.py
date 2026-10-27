"""Admin-wide layout overrides that keep admin pages from scrolling sideways
on narrow windows (below 1024px wide)."""
import re

from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user


def _inline_styles(html):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S))


def _rule(css, selector):
    """Return the body of the first rule whose selector is exactly `selector`."""
    match = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


class TestAdminNarrowScreenLayout(TestCase):

    def setUp(self):
        create_user(pwd="password")
        self.client.login(username="user", password="password")

    def test_selector_is_capped_at_its_form_row(self):
        """The filter_horizontal picker keeps its 980px desktop width but never
        exceeds its form row (a fixed width hid the "Chosen" column)."""
        resp = self.client.get(reverse("admin:auth_group_add"))
        assert resp.status_code == 200
        css = _inline_styles(resp.content.decode())
        selector = _rule(css, ".selector")
        assert selector is not None
        assert "max-width: 100%" in selector
        assert "min-width: 0" in selector
        columns = _rule(css, ".selector-available, .selector-chosen")
        assert columns is not None
        assert "470px" not in columns
        assert "min-width: 0" in columns
        assert "width: 470px" not in css

    def test_dashboard_reserves_room_for_recent_actions(self):
        """colMS (as in Django's index.html) keeps the Recent Actions column
        inside the window; colS let it hang off the right edge."""
        resp = self.client.get(reverse("admin:index"))
        assert resp.status_code == 200
        assert re.search(r'id="content"\s+class="colMS"', resp.content.decode())

    def test_global_overflow_rules(self):
        resp = self.client.get(reverse("admin:auth_user_changelist"))
        assert resp.status_code == 200
        css = _inline_styles(resp.content.decode())
        assert "box-sizing: border-box" in (_rule(css, "#changelist .paginator") or "")
        assert "overflow-x: auto" in (_rule(css, ".inline-group .tabular") or "")
        assert "overflow-wrap: break-word" in (_rule(css, "#content,\ndiv.breadcrumbs") or "")
        assert "min-width: 0" in (_rule(css, ".form-row .readonly") or "")
