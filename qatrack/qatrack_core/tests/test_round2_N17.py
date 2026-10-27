"""Double-submit guards: the main-site `preventDoubleSubmit` helper in base.js
and the admin-wide guard in admin/base_site.html."""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user

BASE_JS = Path(settings.PROJECT_ROOT) / "qatrack_core" / "static" / "qatrack_core" / "js" / "base.js"


def _prevent_double_submit_source():
    src = BASE_JS.read_text(encoding="utf-8")
    start = src.index("$.fn.preventDoubleSubmit")
    end = src.index("return $(this);", start)
    return src[start:end]


class TestPreventDoubleSubmitSource(TestCase):

    def test_label_is_translated(self):
        """The busy label goes through Django's JS catalogue (loaded by
        site_base.html), with an English fallback if the catalogue is missing."""
        src = _prevent_double_submit_source()
        assert 'gettext("Submitting…")' in src
        assert "window.gettext ||" in src
        assert "Submitting..." not in src

    def test_disabled_class_has_no_stray_dot(self):
        src = _prevent_double_submit_source()
        assert '.addClass("disabled")' in src
        assert 'addClass(".disabled")' not in src

    def test_site_base_loads_js_catalogue_before_scripts(self):
        """gettext() in base.js only works because the catalogue loads first."""
        template = (Path(settings.PROJECT_ROOT) / "templates" / "site_base.html").read_text(encoding="utf-8")
        catalogue = template.index("{% url 'javascript-catalog' %}")
        assert catalogue < template.index("require.min.js")


class TestAdminSubmitGuard(TestCase):

    def setUp(self):
        create_user(pwd="password")
        self.client.login(username="user", password="password")

    def _guard_source(self):
        resp = self.client.get(reverse("admin:auth_group_add"))
        assert resp.status_code == 200
        html = resp.content.decode()
        start = html.index("var submittingLabel")
        end = html.index("override Django strftime", start)
        return html[start:end]

    def test_label_is_translated_by_template(self):
        assert 'var submittingLabel = "Submitting…";' in self._guard_source()

    def test_guard_runs_after_form_handlers_and_skips_cancelled_submits(self):
        """Delegated to the document so form-level handlers run first; a submit
        another handler cancelled must not mark the form as submitted."""
        src = self._guard_source()
        assert re.search(r'django\.jQuery\(document\)\.on\("submit",\s*"form"', src)
        assert 'django.jQuery("form").submit(' not in src
        cancelled_check = src.index("e.isDefaultPrevented()")
        mark = src.index("this.beenSubmitted = true")
        assert cancelled_check < mark
        assert "nativeEvent.defaultPrevented" in src
