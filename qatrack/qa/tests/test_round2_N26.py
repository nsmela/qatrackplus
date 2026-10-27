"""Round 2, N26: log messages in perform.py stay in English.

Logs are read by admins and developers, so they should not change language
with the person submitting the form. The message shown to that person on
screen should still be translated.
"""
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.utils import translation

from qatrack.qa import models
from qatrack.qa.tests import utils
from qatrack.qa.views.perform import EditTestListInstance


class TestZeroReferenceLogIsEnglish(TestCase):

    def setUp(self):
        self.user = utils.create_user()
        ref = utils.create_reference(value=0)
        tol = utils.create_tolerance(tol_type=models.PERCENT)
        self.uti = utils.create_unit_test_info(ref=ref, tol=tol)
        self.ti = utils.create_test_instance(unit_test_info=self.uti, value=1.)
        self.ti.reference = ref
        self.ti.tolerance = tol
        self.ti.save(calculate_pass_fail=False)

        request = RequestFactory().post('/')
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)

        self.view = EditTestListInstance()
        self.view.request = request
        self.view.object = self.ti.test_list_instance
        self.view.status = self.ti.status
        self.view.user_set_status = True
        self.view.has_tli_comment = False

    def test_log_english_user_message_translated(self):
        with translation.override('fr'):
            with self.assertLogs('qatrack', level='ERROR') as logs:
                self.view.update_test_instance(self.ti)
            user_messages = [str(m) for m in self.view.request._messages]

        self.assertEqual(
            logs.records[0].getMessage(),
            'Tried to calculate percent diff with a zero reference value. UTI=%d' % self.uti.pk,
        )
        # The on-screen message is still translated for the person using the form.
        self.assertEqual(len(user_messages), 1)
        self.assertIn('Veuillez appeler la radiophysique', user_messages[0])

        self.ti.refresh_from_db()
        self.assertTrue(self.ti.skipped)
        self.assertIsNone(self.ti.value)
