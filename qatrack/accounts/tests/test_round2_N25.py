"""
The password change / reset confirmation pages used to say "Password
Succesfully Changed" (and "Successfuly" in the reset page heading). These tests
make sure the corrected English shows up, and that the translations still
apply now that the msgids in the .po/.mo catalogues have been corrected too.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import translation

CORRECT = 'Password Successfully Changed'
TYPOS = ('Succesfully', 'Successfuly', 'succesfully')

FRENCH = 'Mot de passe modifié avec succès'


class TestPasswordDonePagesSpelling(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('n25user', 'n25@example.com', 'n25password')

    def _change_done(self, **extra):
        self.client.force_login(self.user)
        return self.client.get(reverse('password_change_done'), **extra)

    def _reset_complete(self, **extra):
        return self.client.get(reverse('password_reset_complete'), **extra)

    def assert_no_typos(self, content):
        for typo in TYPOS:
            assert typo not in content

    def test_password_change_done_english(self):
        resp = self._change_done()
        assert resp.status_code == 200
        content = resp.content.decode()
        # once in the <title>, once in the box header
        assert content.count(CORRECT) >= 2
        self.assert_no_typos(content)

    def test_password_reset_complete_english(self):
        resp = self._reset_complete()
        assert resp.status_code == 200
        content = resp.content.decode()
        # once in the <title>, once in the <h1>
        assert content.count(CORRECT) >= 2
        self.assert_no_typos(content)

    @override_settings(LANGUAGE_CODE='fr')
    def test_password_change_done_french(self):
        with translation.override('fr'):
            resp = self._change_done(HTTP_ACCEPT_LANGUAGE='fr')
        content = resp.content.decode()
        assert content.count(FRENCH) >= 2
        assert CORRECT not in content
        self.assert_no_typos(content)

    @override_settings(LANGUAGE_CODE='fr')
    def test_password_reset_complete_french(self):
        with translation.override('fr'):
            resp = self._reset_complete(HTTP_ACCEPT_LANGUAGE='fr')
        content = resp.content.decode()
        assert content.count(FRENCH) >= 2
        assert CORRECT not in content
        self.assert_no_typos(content)


class TestCorrectedMsgidsTranslated(TestCase):
    """The compiled catalogues must know the corrected msgids, in every language."""

    def test_password_changed_translated(self):
        expected = {
            'fr': FRENCH,
            'fr-ca': FRENCH,
            'es': 'Contraseña cambiada con éxito',
        }
        for lang, text in expected.items():
            with translation.override(lang):
                assert translation.gettext(CORRECT) == text, lang

    def test_submit_error_message_translated(self):
        msg = 'Data was not submitted successfully. Please resolve the errors below and try again.'
        for lang in ('fr', 'fr-ca', 'es'):
            with translation.override(lang):
                assert translation.gettext(msg) != msg, lang
