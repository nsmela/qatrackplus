"""QC admin step 2A: Test Instance Statuses, Tolerances, Auto Review Rules and Rule Sets.

Checks the cards and features these pages add on top of the shared QC card layout
(test_qc_admin_design.py), that saving and validation still work as before, and that
view-only users get read-only pages.
"""

import json
import re

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models
from qatrack.qa.tests import utils as qa_utils


def login_viewer(client, *codenames):
    viewer = create_user(uname='viewer', pwd='pwd', is_staff=True, is_superuser=False)
    for codename in codenames:
        viewer.user_permissions.add(Permission.objects.get(codename=codename))
    client.logout()
    client.login(username='viewer', password='pwd')
    return viewer


class TestStatusLabelHelper(TestCase):

    def test_label_has_border_colour_and_name(self):
        html = qa_admin.qc_status_label("Approved", "rgba(0,166,90,1)")
        self.assertIn('class="qcs-label service-event-status-label"', html)
        self.assertIn('style="border-color: rgba(0,166,90,1)"', html)
        self.assertIn('>Approved<', html)

    def test_invalid_colour_is_left_out(self):
        html = qa_admin.qc_status_label("<b>X</b>", 'red;" onmouseover="alert(1)')
        self.assertIn('border-color: transparent', html)
        self.assertNotIn('onmouseover', html)
        self.assertIn('&lt;b&gt;X&lt;/b&gt;', html)


class TestStatusAdmin(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.status = qa_utils.create_status(name="Approved", slug="approved")
        self.status.colour = "rgba(0,166,90,1)"
        self.status.save()
        self.url = reverse('admin:qa_testinstancestatus_change', args=(self.status.pk,))

    def post_data(self, **kwargs):
        data = {
            'name': 'Approved',
            'slug': 'approved',
            'description': '',
            'is_default': 'on',
            'requires_review': 'on',
            'valid': 'on',
            'export_by_default': 'on',
            'colour': 'rgba(0,166,90,1)',
            '_save': 'Save',
        }
        data.update(kwargs)
        return data

    def test_cards_and_fields(self):
        html = self.client.get(self.url).content.decode()
        for card in ('qc-card-details', 'qc-card-behaviour', 'qc-card-colour'):
            self.assertIn('id="%s"' % card, html)
        behaviour = html.split('id="qc-card-behaviour"')[1].split('id="qc-card-colour"')[0]
        for field in ('is_default', 'requires_review', 'valid', 'export_by_default'):
            self.assertIn('for="id_%s"' % field, behaviour)
        colour = html.split('id="qc-card-colour"')[1]
        self.assertIn('name="colour"', colour)
        self.assertIn('fa-paint-brush', html)

    def test_colour_picker_still_loaded(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('colorpicker/js/bootstrap-colorpicker.min.js', html)
        self.assertIn('qatrack_core/js/admin_colourpicker.js', html)
        self.assertIn('field-colour #colour_form', html)

    def test_label_preview_is_drawn_and_scripted(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Label Preview', html)
        self.assertRegex(
            html, r'class="qcs-label service-event-status-label qcs-label-preview" '
                  r'style="border-color: rgba\(0,166,90,1\)">Approved<'
        )
        self.assertIn('document.getElementById("id_colour")', html)
        self.assertIn('changeColor', html)

    def test_add_page_preview_has_placeholder(self):
        html = self.client.get(reverse('admin:qa_testinstancestatus_add')).content.decode()
        self.assertIn('qcs-label-preview qcs-label-empty', html)
        self.assertIn('Status name', html)

    def test_save_still_works(self):
        resp = self.client.post(self.url, self.post_data(name='Approved by physics', export_by_default=''))
        self.assertEqual(resp.status_code, 302)
        self.status.refresh_from_db()
        self.assertEqual(self.status.name, 'Approved by physics')
        self.assertFalse(self.status.export_by_default)

    def test_bad_colour_error_renders_in_colour_card(self):
        resp = self.client.post(self.url, self.post_data(colour='not a colour'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        colour = html.split('id="qc-card-colour"')[1]
        self.assertIn('qc-has-error', colour)
        self.assertIn('Enter a valid color.', colour)
        # The invalid colour isn't put in the preview's style
        self.assertNotIn('border-color: not a colour', html)

    def test_list_shows_status_label(self):
        html = self.client.get(reverse('admin:qa_testinstancestatus_changelist')).content.decode()
        self.assertIn('<th scope="col" class="column-get_colour">', html)
        self.assertIn('style="border-color: rgba(0,166,90,1)">Approved</span>', html)
        self.assertIn('#content-main .qcs-label', html)
        self.assertNotIn('width: 20px; height:20px', html)

    def test_view_only(self):
        login_viewer(self.client, 'view_testinstancestatus')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Test Instance Status', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('name="colour"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertIn('qcs-label-preview', html)


class TestToleranceAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tol = qa_utils.create_tolerance(act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        self.url = reverse('admin:qa_tolerance_change', args=(self.tol.pk,))
        self.add_url = reverse('admin:qa_tolerance_add')

    def data(self, **kwargs):
        data = {
            'type': 'absolute',
            'act_low': '-3', 'tol_low': '-1.5', 'tol_high': '1.5', 'act_high': '3',
            'mc_pass_choices': '', 'mc_tol_choices': '',
            '_save': 'Save',
        }
        data.update(kwargs)
        return data

    def test_add_page_asks_for_a_type_first(self):
        """With no type chosen, the script hides both value cards and shows a hint under Type."""
        html = self.client.get(self.add_url).content.decode()
        self.assertIn('Choose a type to set its limits or choices.', html)
        self.assertIn('qct-type-hint', html)

    def test_cards(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="qc-card-type"', html)
        self.assertIn('id="qc-card-limits"', html)
        self.assertIn('id="qc-card-multiple-choice-values"', html)
        limits = html.split('id="qc-card-limits"')[1].split('id="qc-card-multiple-choice-values"')[0]
        for field in ('act_low', 'tol_low', 'tol_high', 'act_high'):
            self.assertIn('name="%s"' % field, limits)
        # Boolean Warning Only stays in the form (as before) but is hidden
        self.assertIn('name="bool_warning_only"', html)
        self.assertIn('.qc-field.field-bool_warning_only { display: none; }', html)
        # The old script that looked for .form-row isn't loaded; the inline script replaces it
        self.assertNotIn('js/tolerance_admin.js', html)
        self.assertIn('id="qct-config"', html)

    def test_limits_preview_zones(self):
        html = self.client.get(self.url).content.decode()
        strip = html.split('id="qct-limits-strip"')[1].split('</div>')[0]
        zones = re.findall(r'qct-zone qct-zone-(\w+)', strip)
        self.assertEqual(zones, ['action', 'tolerance', 'ok', 'tolerance', 'action'])
        values = re.findall(r'<span class="qct-limit-value">([^<]+)</span>', strip)
        self.assertEqual(values, ['−2', '−1', '1', '2'])
        self.assertIn('Limits are differences from the reference value', html)

    def test_zones_with_blank_limits(self):
        tol = models.Tolerance(type=models.PERCENT, act_low=None, tol_low=None, tol_high=1, act_high=2)
        zones = qa_admin.tolerance_limit_zones(tol)
        self.assertEqual(zones, [models.OK, ('tol_high', 1), models.TOLERANCE, ('act_high', 2), models.ACTION])
        tol = models.Tolerance(type=models.ABSOLUTE, act_low=-2, tol_low=None, tol_high=None, act_high=2)
        self.assertEqual(
            qa_admin.tolerance_limit_zones(tol),
            [models.ACTION, ('act_low', -2), models.OK, ('act_high', 2), models.ACTION],
        )
        self.assertEqual(qa_admin.tolerance_limit_zones(models.Tolerance(type=models.ABSOLUTE)), [])

    def test_out_of_order_limits_warn_and_still_fail_on_server(self):
        before = models.Tolerance.objects.count()
        resp = self.client.post(self.add_url, self.data(tol_low='2', tol_high='1'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(models.Tolerance.objects.count(), before)
        html = resp.content.decode()
        # The server's error, inside the Limits card
        limits = html.split('id="qc-card-limits"')[1].split('id="qc-card-multiple-choice-values"')[0]
        self.assertIn('qc-has-error', limits)
        self.assertIn('Tolerance High must be at least Tolerance Low.', limits)
        # And the preview's warning, shown, with unknown zones
        warning = html.split('id="qct-limits-warning"')[1].split('</p>')[0]
        self.assertNotIn('hidden', warning.split('>', 2)[1])
        self.assertIn('Tolerance High must be at least Tolerance Low.', warning)
        self.assertIn('qct-zone-unknown', limits)

    def test_choices_preview(self):
        tol = qa_utils.create_tolerance(tol_type=models.MULTIPLE_CHOICE, mc_pass_choices='a,b', mc_tol_choices='c,A')
        html = self.client.get(reverse('admin:qa_tolerance_change', args=(tol.pk,))).content.decode()
        ok = html.split('id="qct-choices-ok"')[1].split('</dd>')[0]
        self.assertEqual(re.findall(r'class="qct-chip">([^<]+)<', ok), ['a', 'b'])
        tol_part = html.split('id="qct-choices-tol"')[1].split('</dd>')[0]
        self.assertEqual(re.findall(r'class="qct-chip">([^<]+)<', tol_part), ['c', 'A'])
        self.assertIn('Any other choice', html)
        self.assertIn('In both lists: A. These count as OK.', html)
        self.assertIn('data-qct-type="multchoice"', html)

    def test_add_and_change_still_save(self):
        resp = self.client.post(self.add_url, self.data())
        self.assertEqual(resp.status_code, 302)
        tol = models.Tolerance.objects.order_by('id').last()
        self.assertEqual((tol.act_low, tol.tol_low, tol.tol_high, tol.act_high), (-3, -1.5, 1.5, 3))
        self.assertEqual(tol.created_by, self.user)
        self.assertFalse(tol.bool_warning_only)
        resp = self.client.post(reverse('admin:qa_tolerance_change', args=(tol.pk,)), self.data(act_high='4'))
        self.assertEqual(resp.status_code, 302)
        tol.refresh_from_db()
        self.assertEqual(tol.act_high, 4)

    def test_multiple_choice_error_renders_in_its_card(self):
        resp = self.client.post(self.add_url, self.data(type='multchoice', act_low='', tol_low='', tol_high='',
                                                        act_high='', mc_pass_choices=''))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        choices = html.split('id="qc-card-multiple-choice-values"')[1]
        self.assertIn('qc-has-error', choices)
        self.assertIn('You must give at least 1 passing choice', choices)

    def test_used_in_card(self):
        unit = qa_utils.create_unit(name="Linac 1")
        qa_utils.create_unit_test_info(unit=unit, tol=self.tol)
        qa_utils.create_unit_test_info(unit=unit, tol=self.tol)
        hidden = qa_utils.create_test(name="hidden test")
        hidden.hidden = True
        hidden.save()
        qa_utils.create_unit_test_info(unit=unit, test=hidden, tol=self.tol)
        qa_utils.create_unit_test_info(tol=None)

        html = self.client.get(self.url).content.decode()
        card = html.split('id="qct-used-card"')[1]
        self.assertIn('Used In', card)
        self.assertIn('2 tests on machines use this tolerance.', card)
        link = '%s?tolerance__id__exact=%d' % (reverse('admin:qa_unittestinfo_changelist'), self.tol.pk)
        self.assertIn('href="%s"' % link, card)
        self.assertIn('href="%s&amp;unit__id__exact=%d"' % (link, unit.pk), card)
        self.assertIn('Linac 1', card)

        # The link's filter is one the Unit Test Info list accepts, and gives the same tests
        resp = self.client.get(link)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['cl'].result_count, 2)
        resp = self.client.get('%s&unit__id__exact=%d' % (link, unit.pk))
        self.assertEqual(resp.context['cl'].result_count, 2)

    def test_used_in_card_when_unused(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('No test on any machine uses this tolerance yet.', html)
        self.assertNotIn('id="qct-used-card"', self.client.get(self.add_url).content.decode())

    def test_view_only(self):
        login_viewer(self.client, 'view_tolerance')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Tolerance', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('name="act_low"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        # Still gets the preview, and the Used In count without a link it can't open
        self.assertIn('id="qct-limits-strip"', html)
        self.assertIn('id="qct-used-card"', html)
        self.assertNotIn('tolerance__id__exact', html)


class TestAutoReviewAdmin(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.approved = qa_utils.create_status(name="Approved", slug="approved")
        self.approved.colour = "rgba(0,166,90,1)"
        self.approved.save()
        self.unreviewed = qa_utils.create_status(name="Unreviewed", slug="unreviewed", is_default=False)
        self.rule = models.AutoReviewRule.objects.create(pass_fail=models.OK, status=self.approved)
        self.url = reverse('admin:qa_autoreviewrule_changelist')

    def test_list_has_editable_selects_and_label(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="form-0-pass_fail"', html)
        self.assertIn('name="form-0-status"', html)
        self.assertIn('class="field-status_label"', html)
        self.assertIn('style="border-color: rgba(0,166,90,1)">Approved</span>', html)
        statuses = json.loads(html.split('id="qca-statuses" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(statuses[str(self.approved.pk)], {'name': 'Approved', 'colour': 'rgba(0,166,90,1)'})
        self.assertIn('Auto Review Rule', html)

    def test_list_editable_save(self):
        data = {
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(self.rule.pk),
            'form-0-pass_fail': models.TOLERANCE,
            'form-0-status': str(self.unreviewed.pk),
            '_save': 'Save',
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.pass_fail, models.TOLERANCE)
        self.assertEqual(self.rule.status, self.unreviewed)


class TestAutoReviewRuleSetAdmin(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.approved = qa_utils.create_status(name="Approved", slug="approved")
        self.unreviewed = qa_utils.create_status(name="Unreviewed", slug="unreviewed", is_default=False)
        self.ok_rule = models.AutoReviewRule.objects.create(pass_fail=models.OK, status=self.approved)
        self.tol_rule = models.AutoReviewRule.objects.create(pass_fail=models.TOLERANCE, status=self.unreviewed)
        self.act_rule = models.AutoReviewRule.objects.create(pass_fail=models.ACTION, status=self.unreviewed)
        self.ruleset = models.AutoReviewRuleSet.objects.create(name="Default", is_default=True)
        self.ruleset.rules.set([self.ok_rule, self.tol_rule])
        self.url = reverse('admin:qa_autoreviewruleset_change', args=(self.ruleset.pk,))
        self.add_url = reverse('admin:qa_autoreviewruleset_add')

    def test_rules_are_a_grouped_checkbox_list(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('selectfilter', html)
        self.assertNotIn('SelectFilter2.js', html)
        rules = html.split('class="qca-rules"')[1]
        groups = re.findall(r'data-qca-result="(\w+)"', rules)
        self.assertEqual(groups, [models.OK, models.TOLERANCE, models.ACTION])
        self.assertEqual(rules.count('type="checkbox" name="rules"'), 3)
        self.assertRegex(rules, r'value="%d"[^>]*checked' % self.ok_rule.pk)
        self.assertRegex(rules, r'value="%d"[^>]*checked' % self.tol_rule.pk)
        self.assertNotRegex(rules, r'value="%d"[^>]*checked' % self.act_rule.pk)
        self.assertIn('>Approved</span>', rules)
        self.assertIn('Only one rule for each result is used.', rules)

    def test_save_keeps_the_same_data(self):
        resp = self.client.post(self.url, {
            'name': 'Default', 'is_default': 'on', 'rules': [self.ok_rule.pk, self.act_rule.pk], '_save': 'Save',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(set(self.ruleset.rules.all()), {self.ok_rule, self.act_rule})

    def test_rules_still_required(self):
        resp = self.client.post(self.url, {'name': 'Default', 'is_default': 'on', '_save': 'Save'})
        self.assertEqual(resp.status_code, 200)
        rules = resp.content.decode().split('id="qc-card-rules"')[1]
        self.assertIn('qc-has-error', rules)
        self.assertIn('This field is required.', rules)

    def test_must_be_one_default_error_still_renders(self):
        resp = self.client.post(self.add_url, {
            'name': 'Second', 'is_default': 'on', 'rules': [self.ok_rule.pk], '_save': 'Save',
        })
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        details = html.split('id="qc-card-details"')[1].split('id="qc-card-rules"')[0]
        self.assertIn('There must be one default auto review rule set.', details)
        self.assertIn('qc-has-error', details)
        self.assertEqual(models.AutoReviewRuleSet.objects.count(), 1)

    def test_used_in_card_links_to_tests(self):
        test = qa_utils.create_test(name="Output")
        test.autoreviewruleset = self.ruleset
        test.save()
        other = models.AutoReviewRuleSet.objects.create(name="Other")
        other_test = qa_utils.create_test(name="Not this one")
        other_test.autoreviewruleset = other
        other_test.save()

        html = self.client.get(self.url).content.decode()
        card = html.split('id="qca-used-card"')[1]
        self.assertIn('1 test uses this rule set.', card)
        self.assertIn('href="%s"' % reverse('admin:qa_test_change', args=(test.pk,)), card)
        self.assertNotIn('Not this one', card)
        link = '%s?autoreviewruleset__id__exact=%d' % (reverse('admin:qa_test_changelist'), self.ruleset.pk)
        self.assertIn('href="%s"' % link, card)
        resp = self.client.get(link)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['cl'].result_count, 1)

    def test_used_in_card_caps_the_list(self):
        qa_admin.AutoReviewRuleSetAdmin.USED_IN_LIMIT, limit = 2, qa_admin.AutoReviewRuleSetAdmin.USED_IN_LIMIT
        try:
            for i in range(3):
                t = qa_utils.create_test(name="t%d" % i)
                t.autoreviewruleset = self.ruleset
                t.save()
            html = self.client.get(self.url).content.decode()
        finally:
            qa_admin.AutoReviewRuleSetAdmin.USED_IN_LIMIT = limit
        card = html.split('id="qca-used-card"')[1]
        self.assertIn('Showing the first 2 of 3.', card)
        self.assertIn('Show them all in Tests', card)

    def test_list_shows_rules_as_labels(self):
        html = self.client.get(reverse('admin:qa_autoreviewruleset_changelist')).content.decode()
        self.assertIn('class="qca-rule"', html)
        self.assertIn('class="qca-result" style="border-color: #00a65a">OK</span>', html)
        self.assertIn('>Approved</span>', html)
        # OK before Tolerance
        self.assertLess(html.index('>OK</span>'), html.index('>Tolerance</span>'))

    def test_view_only(self):
        login_viewer(self.client, 'view_autoreviewruleset')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('View Auto Review Rule Set', html)
        self.assertIn('class="qc-readonly"', html)
        self.assertNotIn('name="rules"', html)
        self.assertNotIn('id="qc-save-btn"', html)
        self.assertIn('id="qca-used-card"', html)
