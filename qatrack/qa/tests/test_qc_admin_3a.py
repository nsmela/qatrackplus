"""The Test List Cycle admin pages (step 3A of the QC admin design update).

The change page shows the cycle's days as a builder-style "Test Lists in This Cycle"
card (admin/qa/testlistcycle/change_form.html) whose rows are the membership inline
formset's own forms, an Add Test List search picker (TestListCycleAdmin's
search_test_lists_view and add_row_view), the shared Attachments card and a Used In
card. The list shows days, a test list summary and the number of assignments.
"""

import re

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.text import slugify

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils

PREFIX = "testlistcyclemembership_set"
REMOVE_BTN = 'class="tl-action-icon tl-delete-test-btn qcy-remove-btn"'


def cycle_post_data(name, slug, rows, initial=0, attachments_prefix=None, **extra):
    """POST data for the cycle change form. ``rows`` are dicts of membership fields."""
    data = {
        "name": name,
        "slug": slug,
        "description": "",
        "javascript": "",
        "drop_down_label": "Choose Day",
        "day_option_text": "day",
        "%s-TOTAL_FORMS" % PREFIX: str(len(rows)),
        "%s-INITIAL_FORMS" % PREFIX: str(initial),
        "%s-MIN_NUM_FORMS" % PREFIX: "0",
        "%s-MAX_NUM_FORMS" % PREFIX: "1000",
        "_save": "Save",
    }
    for i, row in enumerate(rows):
        for key, value in row.items():
            data["%s-%d-%s" % (PREFIX, i, key)] = value
    data.update(extra)
    return data


class CycleAdminTestCase(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl1 = qa_utils.create_test_list(name="Morning Output")
        self.tl2 = qa_utils.create_test_list(name="Imaging")
        self.tl3 = qa_utils.create_test_list(name="Mechanical")
        for i in range(2):
            qa_utils.create_test_list_membership(test_list=self.tl1, test=qa_utils.create_test(), order=i)
        qa_utils.create_test_list_membership(test_list=self.tl2, test=qa_utils.create_test(), order=0)

    def attachment_management(self, response_or_html):
        """The attachments inline's management form fields from a rendered change page."""
        html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode()
        data = {}
        for name in ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS"):
            m = re.search(r'name="([^"]*attachment[^"]*-%s)"[^>]*value="(\d+)"' % name, html)
            if m is None:
                m = re.search(r'value="(\d+)"[^>]*name="([^"]*attachment[^"]*-%s)"' % name, html)
                if m:
                    data[m.group(2)] = m.group(1)
                continue
            data[m.group(1)] = m.group(2)
        return data

    def add_page_attachment_data(self):
        return self.attachment_management(self.client.get(reverse("admin:qa_testlistcycle_add")))


class TestCycleChangeForm(CycleAdminTestCase):

    def test_add_page_draws_cards(self):
        resp = self.client.get(reverse("admin:qa_testlistcycle_add"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Add Test List Cycle", html)
        self.assertIn('id="qcy-lists-card"', html)
        self.assertIn("Test Lists in This Cycle", html)
        self.assertIn('id="qcy-add-list-btn"', html)
        self.assertIn('id="qcy-search-modal"', html)
        self.assertIn('id="id_%s-TOTAL_FORMS"' % PREFIX, html)
        # Details card: the shared fieldset card, with the slug still prepopulated from the name
        self.assertIn('class="tl-details-card qc-card', html)
        self.assertIn('id="id_description"', html)
        self.assertIn('id="id_javascript"', html)
        self.assertIn('id="id_drop_down_label"', html)
        self.assertIn('id="id_day_option_text"', html)
        self.assertIn('id="django-admin-prepopulated-fields-constants"', html)
        self.assertIn('&quot;dependency_ids&quot;: [&quot;#id_name&quot;]', html)
        # ace (admin_description_editor.js) still loads, and spans the card
        self.assertIn("admin_description_editor.js", html)
        self.assertIn("ace/ace.js", html)
        self.assertIn("#content-main #description-editor", html)
        # the old drag script is replaced by the card's own
        self.assertNotIn("m2m_drag_admin.js", html)
        # No Used In card before the cycle exists
        self.assertNotIn('id="qcy-used-card"', html)
        # The shared attachments card
        self.assertIn('attachments-editor-container', html)

    def test_add_cycle_with_three_lists(self):
        rows = [
            {"test_list": str(self.tl1.pk), "order": "0"},
            {"test_list": str(self.tl2.pk), "order": "1"},
            {"test_list": str(self.tl3.pk), "order": "2"},
        ]
        data = cycle_post_data("Weekly Cycle", "weekly-cycle", rows, **self.add_page_attachment_data())
        resp = self.client.post(reverse("admin:qa_testlistcycle_add"), data)
        self.assertEqual(resp.status_code, 302, resp.content.decode()[:3000] if resp.status_code != 302 else "")
        cycle = models.TestListCycle.objects.get(slug="weekly-cycle")
        self.assertEqual(
            list(cycle.testlistcyclemembership_set.values_list("test_list", "order")),
            [(self.tl1.pk, 0), (self.tl2.pk, 1), (self.tl3.pk, 2)],
        )
        self.assertEqual(cycle.created_by, self.user)

    def make_cycle(self):
        return qa_utils.create_cycle(test_lists=[self.tl1, self.tl2, self.tl3], name="Daily Cycle")

    def change_rows(self, cycle):
        return [
            {"id": str(m.pk), "cycle": str(cycle.pk), "test_list": str(m.test_list_id), "order": str(m.order)}
            for m in cycle.testlistcyclemembership_set.order_by("order")
        ]

    def test_change_page_draws_rows_in_day_order(self):
        cycle = self.make_cycle()
        resp = self.client.get(reverse("admin:qa_testlistcycle_change", args=(cycle.pk,)))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(html.count('class="tl-member-item qcy-row'), 3)
        # Day 1..3, in order, each with the test list's name, number of tests and a link to it
        positions = [html.index('data-test-list-id="%d"' % tl.pk) for tl in (self.tl1, self.tl2, self.tl3)]
        self.assertEqual(positions, sorted(positions))
        for day in (1, 2, 3):
            self.assertIn('<span class="qcy-day">Day %d</span>' % day, html)
        self.assertIn("2 tests", html)
        self.assertIn("1 test<", html)
        self.assertIn("0 tests", html)
        self.assertIn(reverse("admin:qa_testlist_change", args=(self.tl1.pk,)), html)
        # the formset's inputs are hidden, rendered on the server
        self.assertIn('type="hidden" name="%s-0-test_list" value="%d"' % (PREFIX, self.tl1.pk), html)
        self.assertIn('class="qcy-order-input"', html)
        self.assertIn('name="%s-0-DELETE"' % PREFIX, html)
        self.assertIn('class="fa fa-bars tl-drag-handle"', html)
        self.assertIn(REMOVE_BTN, html)
        self.assertNotIn("dynamic_raw_id", html)
        # header counts
        self.assertIn("3 days", html)

    def test_reorder_via_posted_order(self):
        cycle = self.make_cycle()
        rows = self.change_rows(cycle)
        rows[0]["order"], rows[2]["order"] = "2", "0"
        url = reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))
        page = self.client.get(url)
        data = cycle_post_data(
            "Daily Cycle", slugify(cycle.name), rows, initial=3, **self.attachment_management(page),
        )
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            list(cycle.testlistcyclemembership_set.order_by("order").values_list("test_list", flat=True)),
            [self.tl3.pk, self.tl2.pk, self.tl1.pk],
        )
        self.assertEqual(cycle.get_list(0), (0, self.tl3))

    def test_remove_one(self):
        cycle = self.make_cycle()
        rows = self.change_rows(cycle)
        rows[1]["DELETE"] = "on"
        rows[2]["order"] = "1"
        url = reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))
        page = self.client.get(url)
        data = cycle_post_data(
            "Daily Cycle", slugify(cycle.name), rows, initial=3, **self.attachment_management(page),
        )
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            list(cycle.testlistcyclemembership_set.values_list("test_list", "order")),
            [(self.tl1.pk, 0), (self.tl3.pk, 1)],
        )

    def test_new_row_removed_before_saving_is_dropped(self):
        cycle = qa_utils.create_cycle(test_lists=[self.tl1], name="Short Cycle")
        rows = self.change_rows(cycle) + [{"test_list": str(self.tl2.pk), "order": "", "DELETE": "on"}]
        url = reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))
        page = self.client.get(url)
        data = cycle_post_data("Short Cycle", slugify(cycle.name), rows, initial=1, **self.attachment_management(page))
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(list(cycle.test_lists.all()), [self.tl1])

    def test_validation_errors_render_in_the_cards(self):
        cycle = self.make_cycle()
        rows = self.change_rows(cycle)
        # the user removed day 2 and dragged day 3 first; then the save fails on the name
        rows[1]["DELETE"] = "on"
        rows[2]["order"], rows[0]["order"] = "0", "1"
        rows.append({"test_list": "999999", "order": "2"})
        url = reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))
        page = self.client.get(url)
        data = cycle_post_data("", slugify(cycle.name), rows, initial=3, **self.attachment_management(page))
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("errornote", html)
        self.assertIn("qc-has-error", html)
        # the rows come back the way the user left them: Mechanical first, Imaging still removed
        self.assertLess(html.index('data-test-list-id="%d"' % self.tl3.pk), html.index('data-test-list-id="%d"' % self.tl1.pk))
        removed = re.search(r'<tr[^>]*data-test-list-id="%d"[^>]*>' % self.tl2.pk, html, re.S).group(0)
        self.assertIn("hidden", removed)
        self.assertRegex(html, r'name="%s-1-DELETE"[^>]*checked' % PREFIX)
        # the bad row says what's wrong, inside the card
        self.assertIn("Test list not found", html)
        card = html[html.index('id="qcy-lists-card"'):html.index('id="qcy-empty-msg"')]
        self.assertIn('class="errorlist', card)
        # nothing was saved
        self.assertEqual(cycle.testlistcyclemembership_set.count(), 3)
        cycle.refresh_from_db()
        self.assertEqual(cycle.name, "Daily Cycle")

    def test_used_in_card_lists_assignments(self):
        cycle = self.make_cycle()
        unit = qa_utils.create_unit(name="Linac 1")
        freq = qa_utils.create_frequency(name="Daily", slug="daily")
        utc = qa_utils.create_unit_test_collection(unit=unit, frequency=freq, test_collection=cycle)
        # an assignment of a test list, not this cycle
        qa_utils.create_unit_test_collection(unit=qa_utils.create_unit(name="Linac 2"), test_collection=self.tl1)
        html = self.client.get(reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))).content.decode()
        self.assertIn('id="qcy-used-card"', html)
        used = html[html.index('id="qcy-used-card"'):]
        self.assertIn("Linac 1", used)
        self.assertIn("Daily", used)
        self.assertNotIn("Linac 2", used)
        self.assertIn(reverse("admin:qa_unittestcollection_change", args=(utc.pk,)), used)
        self.assertIn(">Active<", used)
        self.assertIn("1 assignment", html)

    def test_used_in_card_when_not_assigned(self):
        cycle = self.make_cycle()
        html = self.client.get(reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))).content.decode()
        self.assertIn("This cycle isn't assigned to any machine yet.", html)

    def test_view_only_user_gets_read_only_page(self):
        cycle = self.make_cycle()
        viewer = create_user(uname="viewer", pwd="pwd", is_staff=True, is_superuser=False)
        for codename in ("view_testlistcycle", "view_testlistcyclemembership"):
            viewer.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.logout()
        self.client.login(username="viewer", password="pwd")
        resp = self.client.get(reverse("admin:qa_testlistcycle_change", args=(cycle.pk,)))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("View Test List Cycle", html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        # the days are listed, without drag handles, remove buttons, the picker or links it can't open
        self.assertEqual(html.count('class="tl-member-item qcy-row'), 3)
        self.assertIn('<span class="qcy-day">Day 1</span>', html)
        self.assertIn("Morning Output", html)
        self.assertNotIn('class="fa fa-bars tl-drag-handle"', html)
        self.assertNotIn(REMOVE_BTN, html)
        self.assertNotIn('id="qcy-add-list-btn"', html)
        self.assertNotIn('id="qcy-search-modal"', html)
        self.assertNotIn(reverse("admin:qa_testlist_change", args=(self.tl1.pk,)), html)
        self.assertIn("Test Lists in This Cycle", html)

    def test_saved_rows_locked_without_delete_permission(self):
        cycle = self.make_cycle()
        editor = create_user(uname="editor", pwd="pwd", is_staff=True, is_superuser=False)
        for codename in ("change_testlistcycle", "view_testlistcycle", "add_testlistcyclemembership",
                         "change_testlistcyclemembership", "view_testlistcyclemembership"):
            editor.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.logout()
        self.client.login(username="editor", password="pwd")
        html = self.client.get(reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))).content.decode()
        self.assertNotIn(REMOVE_BTN, html)
        self.assertIn("tl-remove-locked", html)
        self.assertIn('id="qcy-add-list-btn"', html)


class TestCyclePicker(CycleAdminTestCase):

    def test_search_lists_results(self):
        url = reverse("admin:qa_testlistcycle_search_lists")
        resp = self.client.get(url, {"q": "", "in_cycle": "%d" % self.tl2.pk})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for tl in (self.tl1, self.tl2, self.tl3):
            self.assertIn('data-test-list-id="%d"' % tl.pk, html)
        # already in the cycle: listed, but can't be added again
        item = re.search(
            r'<div class="tl-search-item qcy-search-item[^"]*"\s+data-test-list-id="%d">.*?</div>\s*</div>\s*</div>'
            % self.tl2.pk, html, re.S,
        ).group(0)
        self.assertIn("tl-search-item-blocked", item)
        self.assertIn("Already in this cycle", item)
        self.assertIn("disabled", item)
        self.assertIn('class="tl-btn-select-sublist qcy-btn-pick" data-test-list-id="%d"' % self.tl1.pk, html)
        self.assertIn("2 tests", html)

    def test_search_filters_by_name(self):
        html = self.client.get(reverse("admin:qa_testlistcycle_search_lists"), {"q": "imag"}).content.decode()
        self.assertIn("Imaging", html)
        self.assertNotIn("Morning Output", html)
        html = self.client.get(reverse("admin:qa_testlistcycle_search_lists"), {"q": "zzz"}).content.decode()
        self.assertIn("No test lists found matching", html)

    def test_add_row_renders_a_formset_row(self):
        cycle = qa_utils.create_cycle(test_lists=[self.tl1], name="Short Cycle")
        url = reverse("admin:qa_testlistcycle_add_row")
        resp = self.client.get(url, {"test_list": self.tl2.pk, "index": 1, "cycle": cycle.pk})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="qcy-row-%s-1"' % PREFIX, html)
        self.assertIn('name="%s-1-test_list" value="%d"' % (PREFIX, self.tl2.pk), html)
        self.assertIn('name="%s-1-order" value="1"' % PREFIX, html)
        self.assertIn('name="%s-1-id"' % PREFIX, html)
        self.assertIn('name="%s-1-cycle" value="%d"' % (PREFIX, cycle.pk), html)
        self.assertIn('name="%s-1-DELETE"' % PREFIX, html)
        self.assertIn("Imaging", html)
        self.assertIn("1 test<", html)
        self.assertIn(REMOVE_BTN, html)

    def test_added_row_saves(self):
        """A row from add_row_view, posted with the page's rows, saves as a new day."""
        cycle = qa_utils.create_cycle(test_lists=[self.tl1], name="Short Cycle")
        row_html = self.client.get(
            reverse("admin:qa_testlistcycle_add_row"), {"test_list": self.tl3.pk, "index": 1, "cycle": cycle.pk},
        ).content.decode()
        new_row = {}
        for tag in re.findall(r'<input[^>]*>', row_html):
            name = re.search(r'name="%s-1-(\w+)"' % PREFIX, tag)
            value = re.search(r'value="([^"]*)"', tag)
            if name and name.group(1) != "DELETE":
                new_row[name.group(1)] = value.group(1) if value else ""
        self.assertEqual(new_row["test_list"], str(self.tl3.pk))
        rows = [
            {"id": str(m.pk), "cycle": str(cycle.pk), "test_list": str(m.test_list_id), "order": str(m.order)}
            for m in cycle.testlistcyclemembership_set.all()
        ] + [new_row]
        url = reverse("admin:qa_testlistcycle_change", args=(cycle.pk,))
        page = self.client.get(url)
        data = cycle_post_data("Short Cycle", slugify(cycle.name), rows, initial=1, **self.attachment_management(page))
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            list(cycle.testlistcyclemembership_set.values_list("test_list", "order")),
            [(self.tl1.pk, 0), (self.tl3.pk, 1)],
        )

    def test_add_row_on_add_page_and_unknown_list(self):
        url = reverse("admin:qa_testlistcycle_add_row")
        resp = self.client.get(url, {"test_list": self.tl1.pk, "index": 0})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<input type="hidden" name="%s-0-cycle" id="id_%s-0-cycle">' % (PREFIX, PREFIX), resp.content.decode())
        self.assertEqual(self.client.get(url, {"test_list": 999999, "index": 0}).status_code, 404)

    def test_picker_needs_permission(self):
        viewer = create_user(uname="viewer", pwd="pwd", is_staff=True, is_superuser=False)
        viewer.user_permissions.add(Permission.objects.get(codename="view_testlistcycle"))
        self.client.logout()
        self.client.login(username="viewer", password="pwd")
        self.assertEqual(self.client.get(reverse("admin:qa_testlistcycle_search_lists")).status_code, 403)
        resp = self.client.get(reverse("admin:qa_testlistcycle_add_row"), {"test_list": self.tl1.pk, "index": 0})
        self.assertEqual(resp.status_code, 403)
        # and not for anyone who isn't staff
        self.client.logout()
        resp = self.client.get(reverse("admin:qa_testlistcycle_search_lists"))
        self.assertEqual(resp.status_code, 302)


class TestCycleChangeList(CycleAdminTestCase):

    def test_list_columns(self):
        lists = [qa_utils.create_test_list(name="List %d" % i) for i in range(5)]
        cycle = qa_utils.create_cycle(test_lists=lists, name="Big Cycle")
        qa_utils.create_unit_test_collection(test_collection=cycle)
        qa_utils.create_unit_test_collection(test_collection=cycle)
        qa_utils.create_cycle(name="Empty Cycle")
        html = self.client.get(reverse("admin:qa_testlistcycle_changelist")).content.decode()
        self.assertIn("column-day_count", html)
        self.assertIn("column-test_lists_summary", html)
        self.assertIn("column-assignment_count", html)
        self.assertIn("List 0, List 1, List 2 and 2 more", html)
        self.assertIn('<td class="field-day_count">5</td>', html)
        self.assertIn('<td class="field-assignment_count">2</td>', html)
        self.assertIn("No test lists yet", html)

    def test_list_query_count_does_not_grow_with_cycles(self):
        def cycle_queries():
            # the cycle list's own queries (the admin header's QC counts are left out)
            self.client.get(reverse("admin:qa_testlistcycle_changelist"))
            with CaptureQueriesContext(connection) as ctx:
                resp = self.client.get(reverse("admin:qa_testlistcycle_changelist"))
            self.assertEqual(resp.status_code, 200)
            return [
                q["sql"] for q in ctx.captured_queries
                if '"qa_testlist' in q["sql"] and '"qa_testlistinstance"' not in q["sql"]
            ]

        cycle = qa_utils.create_cycle(test_lists=[self.tl1, self.tl2], name="Cycle A")
        qa_utils.create_unit_test_collection(test_collection=cycle)
        few = cycle_queries()
        for i in range(5):
            cycle = qa_utils.create_cycle(test_lists=[self.tl1, self.tl2, self.tl3], name="Cycle %d" % i)
            qa_utils.create_unit_test_collection(test_collection=cycle)
        many = cycle_queries()
        self.assertEqual(len(many), len(few), many)
        self.assertLessEqual(len(many), 4)
