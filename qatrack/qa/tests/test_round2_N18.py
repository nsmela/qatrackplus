"""reference_changed is only recorded when the reference value really changes (round 2, N18)."""
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.utils import get_internal_user


class TestReferenceChangedFlag(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        get_internal_user()
        self.unit = qa_utils.create_unit(name='Machine A')
        self.num_test = qa_utils.create_test(name='Output')
        self.abs_tol = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.abs_tol2 = qa_utils.create_tolerance(act_low=-5, tol_low=-4, tol_high=4, act_high=5)
        self.old_ref = qa_utils.create_reference(value=100)
        self.uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.num_test, ref=self.old_ref, tol=self.abs_tol)
        self.empty_test = qa_utils.create_test(name='Empty')
        self.empty_uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.empty_test)

    # --- UnitTestInfo admin page ---

    def _admin_save(self, uti, data):
        request = RequestFactory().get('/')
        request.user = self.user
        model_admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, AdminSite())
        form = model_admin.get_form(request)(instance=uti, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        model_admin.save_model(request, model_admin.save_form(request, form, True), form, True)
        return qa_models.UnitTestInfoChange.objects.filter(unit_test_info=uti).latest('changed')

    def test_admin_unchanged_reference_not_flagged(self):
        change = self._admin_save(self.uti, {'reference_value': '100', 'tolerance': self.abs_tol2.pk})
        self.assertFalse(change.reference_changed)
        self.assertTrue(change.tolerance_changed)

    def test_admin_changed_reference_flagged(self):
        change = self._admin_save(self.uti, {'reference_value': '101', 'tolerance': self.abs_tol.pk})
        self.assertTrue(change.reference_changed)
        self.assertFalse(change.tolerance_changed)

    def test_admin_new_reference_flagged(self):
        change = self._admin_save(self.empty_uti, {'reference_value': '5', 'tolerance': ''})
        self.assertIsNone(change.reference)
        self.assertTrue(change.reference_changed)
        self.assertFalse(change.tolerance_changed)

    def test_admin_blank_reference_keeps_it(self):
        change = self._admin_save(self.uti, {'reference_value': '', 'tolerance': self.abs_tol.pk, 'comment': 'Clear'})
        self.uti.refresh_from_db()
        # a blank reference value now keeps the current reference (round 3, R1)
        self.assertEqual(self.uti.reference_id, self.old_ref.pk)
        self.assertFalse(change.reference_changed)

    # --- builder's machine Reference and Tolerance endpoint ---

    def _machine_post(self, uti, data):
        resp = self.client.post(reverse('admin:qa_testlist_machine_ref_tol', args=[uti.pk]), data)
        self.assertEqual(resp.status_code, 200)
        return qa_models.UnitTestInfoChange.objects.filter(unit_test_info=uti).latest('changed')

    def test_machine_same_value_typed_differently_not_flagged(self):
        # "100.0" differs from the shown "100", so the form saves a new Reference,
        # but its value is the same
        change = self._machine_post(self.uti, {'reference_value': '100.0', 'tolerance': self.abs_tol2.pk})
        self.uti.refresh_from_db()
        self.assertNotEqual(self.uti.reference_id, self.old_ref.pk)
        self.assertFalse(change.reference_changed)
        self.assertTrue(change.tolerance_changed)

    def test_machine_changed_reference_flagged(self):
        change = self._machine_post(self.uti, {'reference_value': '42', 'tolerance': self.abs_tol.pk})
        self.assertTrue(change.reference_changed)
        self.assertFalse(change.tolerance_changed)

    def test_machine_new_reference_flagged(self):
        change = self._machine_post(self.empty_uti, {'reference_value': '7', 'tolerance': ''})
        self.assertTrue(change.reference_changed)

    # --- helper ---

    def test_reference_value_changed_helper(self):
        bool_test = qa_utils.create_test(name='Door', test_type=qa_models.BOOLEAN)
        num_one = qa_models.Reference(value=1, type=qa_models.NUMERICAL)
        bool_one = qa_models.Reference(value=1, type=qa_models.BOOLEAN)
        f = qa_admin.reference_value_changed
        self.assertFalse(f(None, None))
        self.assertTrue(f(None, num_one))
        self.assertTrue(f(num_one, None))
        self.assertFalse(f(num_one, qa_models.Reference(value=1.0, type=qa_models.NUMERICAL)))
        # the form leaves the submitted string on a just-saved Reference
        self.assertFalse(f(num_one, qa_models.Reference(value='1', type=qa_models.NUMERICAL)))
        self.assertFalse(f(bool_one, qa_models.Reference(value=True, type=qa_models.BOOLEAN)))
        self.assertTrue(f(num_one, qa_models.Reference(value=2, type=qa_models.NUMERICAL)))
        self.assertTrue(f(num_one, bool_one, self.num_test))
        # older Yes/No references were stored as numerical; re-saving as Boolean isn't a change
        self.assertFalse(f(num_one, bool_one, bool_test))

    # --- history display still handles older, spuriously flagged rows ---

    def test_history_ignores_legacy_flag_on_same_value(self):
        new_ref = qa_utils.create_reference(value=100)
        self.uti.reference = new_ref
        self.uti.save()
        qa_models.UnitTestInfoChange.objects.create(
            unit_test_info=self.uti, reference=self.old_ref, reference_changed=True,
            tolerance=self.abs_tol, tolerance_changed=False, changed_by=self.user, comment='legacy',
        )
        model_admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, AdminSite())
        html = model_admin.history(self.uti)
        self.assertNotIn('uti-history-before', html)
        self.assertEqual(html.count('No change'), 2 + 1)  # two cells plus the help text
