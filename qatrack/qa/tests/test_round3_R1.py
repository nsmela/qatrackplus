"""Leaving "New reference value" blank keeps the current reference (round 3, R1)."""
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.utils import get_internal_user


class TestBlankReferenceKeepsCurrent(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        get_internal_user()
        self.unit = qa_utils.create_unit(name='Machine A')
        self.test = qa_utils.create_test(name='Output')
        self.tol_a = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.tol_b = qa_utils.create_tolerance(act_low=-5, tol_low=-4, tol_high=4, act_high=5)
        self.pct_tol = qa_utils.create_tolerance(tol_type=qa_models.PERCENT)
        self.ref = qa_utils.create_reference(value=100)
        self.uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.test, ref=self.ref, tol=self.tol_a)

    def _post(self, uti, **data):
        url = reverse('admin:qa_unittestinfo_change', args=[uti.pk])
        payload = {
            'unit': uti.unit_id, 'test': uti.test_id, 'active': 'on', 'reference_value': '', 'comment': '',
            'tolerance': '',
        }
        payload.update(data)
        return self.client.post(url, payload)

    def test_blank_keeps_reference(self):
        refs_before = qa_models.Reference.objects.count()
        resp = self._post(self.uti, tolerance=self.tol_b.pk)
        self.assertEqual(resp.status_code, 302)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference_id, self.ref.pk)
        self.assertEqual(self.uti.reference.value, 100)
        self.assertEqual(self.uti.tolerance_id, self.tol_b.pk)
        self.assertEqual(qa_models.Reference.objects.count(), refs_before)

    def test_blank_with_percent_tolerance_validates_against_kept_reference(self):
        resp = self._post(self.uti, tolerance=self.pct_tol.pk)
        self.assertEqual(resp.status_code, 302)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference_id, self.ref.pk)
        self.assertEqual(self.uti.tolerance_id, self.pct_tol.pk)

    def test_blank_with_percent_tolerance_and_no_reference_fails(self):
        empty = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(name='Empty'))
        resp = self._post(empty, tolerance=self.pct_tol.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('reference_value', resp.context['adminform'].form.errors)
        empty.refresh_from_db()
        self.assertIsNone(empty.tolerance_id)

    def test_blank_with_percent_tolerance_and_zero_reference_fails(self):
        self.ref.value = 0
        self.ref.save()
        resp = self._post(self.uti, tolerance=self.pct_tol.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('reference_value', resp.context['adminform'].form.errors)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.tolerance_id, self.tol_a.pk)

    def test_blank_wraparound_checks_kept_reference(self):
        wrap = qa_utils.create_test(name='Gantry', test_type=qa_models.WRAPAROUND)
        wrap.wrap_low, wrap.wrap_high = 0, 360
        wrap.save()
        uti = qa_utils.create_unit_test_info(
            unit=self.unit, test=wrap, ref=qa_utils.create_reference(value=500), tol=self.tol_a,
        )
        resp = self._post(uti, tolerance=self.tol_b.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('reference_value', resp.context['adminform'].form.errors)

    def test_blank_boolean_keeps_reference(self):
        bool_test = qa_utils.create_test(name='Door', test_type=qa_models.BOOLEAN)
        bool_ref = qa_utils.create_reference(value=1, ref_type=qa_models.BOOLEAN)
        uti = qa_utils.create_unit_test_info(unit=self.unit, test=bool_test, ref=bool_ref)
        resp = self._post(uti, comment='Just a note')
        self.assertEqual(resp.status_code, 302)
        uti.refresh_from_db()
        self.assertEqual(uti.reference_id, bool_ref.pk)

    def test_changed_value_still_saves(self):
        resp = self._post(self.uti, reference_value='105', tolerance=self.tol_a.pk)
        self.assertEqual(resp.status_code, 302)
        self.uti.refresh_from_db()
        self.assertNotEqual(self.uti.reference_id, self.ref.pk)
        self.assertEqual(self.uti.reference.value, 105)

    def test_history_flags_for_blank_save(self):
        self._post(self.uti, tolerance=self.tol_b.pk, comment='Wider tolerance')
        change = qa_models.UnitTestInfoChange.objects.get(unit_test_info=self.uti)
        self.assertFalse(change.reference_changed)
        self.assertTrue(change.tolerance_changed)
        self.assertEqual(change.reference_id, self.ref.pk)

    def test_history_flags_for_changed_value(self):
        self._post(self.uti, reference_value='105', tolerance=self.tol_a.pk)
        change = qa_models.UnitTestInfoChange.objects.get(unit_test_info=self.uti)
        self.assertTrue(change.reference_changed)
        self.assertFalse(change.tolerance_changed)

    def test_help_text_says_blank_keeps(self):
        resp = self.client.get(reverse('admin:qa_unittestinfo_change', args=[self.uti.pk]))
        self.assertContains(resp, 'Leave this blank to keep the current reference.')

    # --- builder's Reference and Tolerance dialog keeps its own rules ---

    def _dialog_post(self, **data):
        return self.client.post(reverse('admin:qa_testlist_machine_ref_tol', args=[self.uti.pk]), data)

    def test_dialog_unchanged_value_keeps_reference(self):
        resp = self._dialog_post(reference_value='100', tolerance=self.tol_b.pk)
        self.assertEqual(resp.status_code, 200)
        self.uti.refresh_from_db()
        self.assertEqual(self.uti.reference_id, self.ref.pk)

    def test_dialog_emptied_value_clears_reference(self):
        resp = self._dialog_post(reference_value='', tolerance=self.tol_b.pk)
        self.assertEqual(resp.status_code, 200)
        self.uti.refresh_from_db()
        self.assertIsNone(self.uti.reference_id)
