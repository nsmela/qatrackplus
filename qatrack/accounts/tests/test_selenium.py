"""Browser tests for logging in and out, password changes and the Groups & Permissions page.

Every page in QATrack+ sits behind the login, so if any of these break, nobody
gets to the QC at all - or worse, a clinic's permission changes silently fail
to save.
"""

from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import Group, Permission, User
from django.contrib.sessions.models import Session
from django.urls import reverse
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qatrack_core.tests.live import SeleniumTestCase


def get_perm(code):
    """Return the Permission for a dotted 'app_label.codename' string."""
    app_label, codename = code.split('.')
    return Permission.objects.get(codename=codename, content_type__app_label=app_label)


class AccountsSeleniumTestCase(SeleniumTestCase):
    """Helpers shared by the tests below."""

    def path(self):
        """The path (and query string) the browser is showing, without the live server's host."""
        parsed = urlparse(self.driver.current_url)
        return parsed.path + ('?' + parsed.query if parsed.query else '')

    def wait_for_path(self, path):
        self.wait_until(lambda: urlparse(self.driver.current_url).path == path, message='never reached %s' % path)

    def submit_login_form(self, username, password):
        """Fill in and submit the login form already on screen."""
        self.wait_for_element('#id_username')
        self.driver.find_element(By.ID, 'id_username').send_keys(username)
        self.driver.find_element(By.ID, 'id_password').send_keys(password)
        with self.wait_for_page_load():
            self.driver.find_element(By.CSS_SELECTOR, '#qatrack-wrapper button[type=submit]').click()

    def click_element(self, element):
        """Click like a user would, with the element in the middle of the window.

        The harness's patched WebElement.click scrolls the element to the very
        top of the window, where the fixed navbar covers it, so near-the-top
        controls such as the Add Group button get "click intercepted".
        """
        self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', element)
        ActionChains(self.driver).move_to_element(element).click().perform()

    def logout_through_sidebar(self):
        """Log out the way a user does: hover the gear menu, then click Logout."""
        btn = self.wait_for_visible('#control-sidebar-btn')
        ActionChains(self.driver).move_to_element(btn).perform()
        logout = self.wait_for_visible('aside.control-sidebar a[href="%s"]' % reverse('auth_logout'))
        with self.wait_for_page_load():
            ActionChains(self.driver).move_to_element(logout).click().perform()


class TestLoginLogout(AccountsSeleniumTestCase):

    def test_wrong_password_shows_error_and_stays_on_login_page(self):
        """A wrong password must be refused visibly, not quietly let through or dropped on another page."""
        self.open(reverse('login'))
        self.submit_login_form(self.user.username, 'not-the-password')

        error = self.wait_for_visible('#qatrack-wrapper .alert-danger')
        assert 'correct username and password' in error.text
        assert urlparse(self.driver.current_url).path == reverse('login')
        # Nothing on the page that only a logged in user gets, and no session.
        assert self.driver.find_elements(By.CSS_SELECTOR, 'a[href="%s"]' % reverse('auth_logout')) == []
        assert self.driver.get_cookie('sessionid') is None
        assert Session.objects.count() == 0

    def test_protected_page_redirects_to_login_and_back(self):
        """Logged out, a deep link goes to the login page with ?next=, and logging in returns to it.

        The query string has two parameters on purpose: if the middleware did
        not URL-encode `next`, the second one would be lost on the way.
        """
        target = reverse('all_lists') + '?a=1&b=2'
        self.open(target)

        self.wait_for_path(reverse('login'))
        next_values = parse_qs(urlparse(self.driver.current_url).query).get('next')
        assert next_values == [target]

        self.submit_login_form(self.user.username, self.password)

        self.wait_for_element('a[href="%s"]' % reverse('auth_logout'))
        assert self.path() == target
        assert Session.objects.count() == 1

    def test_logout_link_logs_out_and_protects_pages_again(self):
        """The Logout link must end the session; a protected page must then ask for a login again."""
        self.login()
        self.open(reverse('home'))
        assert Session.objects.count() == 1

        self.logout_through_sidebar()

        self.wait_for_path(reverse('login'))
        self.wait_for_element('#id_username')
        assert Session.objects.count() == 0
        assert self.driver.find_elements(By.CSS_SELECTOR, 'a[href="%s"]' % reverse('auth_logout')) == []

        protected = reverse('all_lists')
        self.open(protected)
        self.wait_for_path(reverse('login'))
        assert parse_qs(urlparse(self.driver.current_url).query).get('next') == [protected]


class TestPasswordChange(AccountsSeleniumTestCase):

    def test_change_password_then_log_in_with_new_one(self):
        """After changing a password the old one must stop working and the new one must log in."""
        new_password = 'Gentle-Maple-Syrup-42'

        self.login()
        self.open(reverse('account-change-password'))
        self.wait_for_element('#id_old_password').send_keys(self.password)
        self.driver.find_element(By.ID, 'id_new_password1').send_keys(new_password)
        self.driver.find_element(By.ID, 'id_new_password2').send_keys(new_password)
        with self.wait_for_page_load():
            self.driver.find_element(By.CSS_SELECTOR, '.box-body form button[type=submit]').click()

        self.wait_for_path(reverse('password_change_done'))
        self.user.refresh_from_db()
        assert self.user.check_password(new_password)
        assert not self.user.check_password(self.password)

        self.logout_through_sidebar()
        self.wait_for_path(reverse('login'))

        # The old password is refused...
        self.submit_login_form(self.user.username, self.password)
        self.wait_for_visible('#qatrack-wrapper .alert-danger')

        # ...and the new one works.
        self.driver.find_element(By.ID, 'id_username').clear()
        self.submit_login_form(self.user.username, new_password)
        self.wait_for_element('a[href="%s"]' % reverse('auth_logout'))
        assert Session.objects.count() == 1


class TestGroupsPage(AccountsSeleniumTestCase):
    """The Vue app at Admin Options > Groups & Permissions."""

    TOGGLE_PERM = 'qa.can_choose_frequency'
    TOGGLE_PERM_NAME = 'Choose QC by frequency or category'

    def setUp(self):
        super().setUp()
        # create_group gives each group qa.add_testlistinstance.
        self.alpha = create_group(name='Alpha Physicists')
        self.alpha.permissions.add(get_perm(self.TOGGLE_PERM))
        self.beta = create_group(name='Beta Therapists')
        self.other = create_user(is_superuser=False, is_staff=False, uname='therapist', pwd='password')

    def perm_item(self, perm_name):
        """The <li> for a permission, found by its displayed name."""
        for li in self.driver.find_elements(By.CSS_SELECTOR, '#app li.indent'):
            if li.find_element(By.CSS_SELECTOR, 'strong').text.strip() == perm_name:
                return li
        raise AssertionError('permission %r is not listed' % perm_name)

    def perm_is_shown_active(self, perm_name):
        icon = self.perm_item(perm_name).find_element(By.CSS_SELECTOR, 'a.toggle i')
        return 'fa-check-circle' in icon.get_attribute('class')

    def open_groups_page(self, group_name):
        """Open the page and wait until `group_name` is selected and its permissions have arrived."""
        self.login()
        self.open(reverse('groups-app'))
        self.wait_for_element('#groups option')
        if self.driver.execute_script('return document.getElementById("groups").value;') != group_name:
            self.select_by_text('groups', group_name)
        self.wait_for_group_loaded(group_name)

    def permission_headings(self):
        """The text of the labels above each permission category (and the 'Group' label, harmlessly)."""
        return [el.text.strip() for el in self.driver.find_elements(By.CSS_SELECTOR, '#app label[for=groups]')]

    def wait_for_group_loaded(self, group_name):
        """Wait until the page says it is showing `group_name` and that group's details have arrived.

        The heading changes as soon as a group is picked, but its permissions
        come from a separate request; toggling before that lands would act on
        the previous group. The Vue app keeps the loaded group in `groupData`.
        """
        self.wait_until(
            lambda: 'Performing Permissions for %s' % group_name in self.permission_headings(),
            message='heading never named %s' % group_name,
        )
        self.wait_until(
            lambda: self.driver.execute_script(
                'var d = document.getElementById("app").__vue__.groupData; return d && d.name;'
            ) == group_name,
            message='details for %s never loaded' % group_name,
        )

    def test_selecting_group_loads_its_permissions(self):
        """Switching groups must show that group's permissions, not the previous group's."""
        self.open_groups_page('Alpha Physicists')
        self.wait_until(lambda: self.perm_is_shown_active(self.TOGGLE_PERM_NAME))
        assert self.perm_is_shown_active('Can add test list instance')

        self.select_by_text('groups', 'Beta Therapists')
        self.wait_for_group_loaded('Beta Therapists')
        self.wait_until(lambda: not self.perm_is_shown_active(self.TOGGLE_PERM_NAME))
        assert self.perm_is_shown_active('Can add test list instance')
        assert not self.perm_is_shown_active('Can change groups')

    def test_toggling_permission_saves_and_untoggling_removes_it(self):
        """Clicking a permission must add it to the group in the database; clicking again must remove it."""
        perm = get_perm(self.TOGGLE_PERM)
        self.open_groups_page('Beta Therapists')
        assert not self.perm_is_shown_active(self.TOGGLE_PERM_NAME)

        self.click_element(self.perm_item(self.TOGGLE_PERM_NAME).find_element(By.CSS_SELECTOR, 'a.toggle'))
        # The tick only appears once the server has answered the PUT.
        self.wait_until(lambda: self.perm_is_shown_active(self.TOGGLE_PERM_NAME), message='tick never shown')
        self.wait_for_ajax()
        assert set(self.beta.permissions.values_list('codename', flat=True)) == {
            'add_testlistinstance', 'can_choose_frequency'
        }
        # Only the chosen group changed.
        assert self.alpha.permissions.filter(pk=perm.pk).exists()

        self.click_element(self.perm_item(self.TOGGLE_PERM_NAME).find_element(By.CSS_SELECTOR, 'a.toggle'))
        self.wait_until(lambda: not self.perm_is_shown_active(self.TOGGLE_PERM_NAME), message='cross never shown')
        self.wait_for_ajax()
        assert set(self.beta.permissions.values_list('codename', flat=True)) == {'add_testlistinstance'}
        assert self.alpha.permissions.filter(pk=perm.pk).exists()

    def user_row(self, username):
        for row in self.driver.find_elements(By.CSS_SELECTOR, '#user-table tbody tr'):
            if row.find_element(By.CSS_SELECTOR, 'td').text.strip() == username:
                return row
        raise AssertionError('user %r is not in the membership table' % username)

    def user_row_selected(self, username):
        return 'info' in self.user_row(username).get_attribute('class')

    def save_group_dialog(self):
        """Click the dialog's save button and wait until the server has answered and the page has caught up."""
        self.click_element(self.driver.find_element(By.CSS_SELECTOR, '#new-group-modal .modal-footer .btn-primary'))
        self.wait_for_text('#group-add-msg', 'Saved group!')
        self.wait_for_invisible('#new-group-modal')

    def test_add_group_through_modal(self):
        """The Add Group dialog must create the group with the chosen members, and select it afterwards."""
        self.open_groups_page('Alpha Physicists')

        self.click_element(self.driver.find_element(By.CSS_SELECTOR, '#app a[title="Add New Group"]'))
        self.wait_for_visible('#new-group-modal')
        self.wait_for_text('#new-group-modal .modal-title', 'Add New Group')
        self.wait_for_element('#user-table tbody tr')

        self.driver.find_element(By.ID, 'new-group-name').send_keys('Gamma Dosimetrists')
        self.click_element(self.user_row('therapist'))
        self.wait_until(lambda: self.user_row_selected('therapist'), message='row never highlighted')
        self.save_group_dialog()

        # The new group is now the selected one.
        self.wait_for_group_loaded('Gamma Dosimetrists')
        self.wait_for_ajax()
        assert self.driver.execute_script('return document.getElementById("groups").value;') == 'Gamma Dosimetrists'
        group = Group.objects.get(name='Gamma Dosimetrists')
        assert list(group.user_set.values_list('username', flat=True)) == ['therapist']
        assert Group.objects.count() == 3

    def test_add_user_to_existing_group(self):
        """Edit Group must add the clicked user to the group without dropping anyone already in it."""
        self.beta.user_set.add(self.user)
        self.open_groups_page('Beta Therapists')

        self.click_element(self.driver.find_element(By.CSS_SELECTOR, '#app a[title="Edit Group Name & Members"]'))
        self.wait_for_visible('#new-group-modal')
        self.wait_for_text('#new-group-modal .modal-title', 'Edit Group')
        self.wait_for_element('#user-table tbody tr')
        # Existing members come pre-selected; others do not.
        self.wait_until(lambda: self.user_row_selected('user'), message='existing member not pre-selected')
        assert not self.user_row_selected('therapist')
        assert self.driver.find_element(By.ID, 'new-group-name').get_attribute('value') == 'Beta Therapists'

        self.click_element(self.user_row('therapist'))
        self.wait_until(lambda: self.user_row_selected('therapist'), message='row never highlighted')
        self.save_group_dialog()
        self.wait_for_ajax()

        assert set(self.beta.user_set.values_list('username', flat=True)) == {'user', 'therapist'}
        assert set(User.objects.get(username='therapist').groups.values_list('name', flat=True)) == {
            'Beta Therapists'
        }
