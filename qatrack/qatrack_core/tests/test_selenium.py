"""Browser tests for behaviour every QATrack+ page shares.

The session ping on the Perform QC page, which menus a user is shown, the
language switcher, Ajax comments, the homepage boxes and the error page.
These live in site_base.html and qatrack_core's JavaScript, so a mistake in
them shows up everywhere at once.
"""

from urllib.parse import urlparse

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse
from django_comments.models import Comment
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log.tests import utils as sl_utils


def get_perm(code):
    """Return the Permission for a dotted 'app_label.codename' string."""
    app_label, codename = code.split('.')
    return Permission.objects.get(codename=codename, content_type__app_label=app_label)


def create_limited_user(uname='therapist', perms=()):
    """A non-staff, non-superuser account. create_user always grants qa.add_testlistinstance."""
    user = create_user(is_superuser=False, is_staff=False, uname=uname, pwd='password')
    for code in perms:
        user.user_permissions.add(get_perm(code))
    return user


class CoreSeleniumTestCase(SeleniumTestCase):

    def menu_links(self):
        """Every href in the top navigation bar and the gear (control) sidebar, as rendered."""
        return set(self.driver.execute_script(
            'return Array.from(document.querySelectorAll(".main-header a[href], aside.control-sidebar a[href]"))'
            '.map(function(a){ return a.getAttribute("href"); });'
        ))

    def logout_href(self):
        return 'a[href="%s"]' % reverse('auth_logout')


class TestSessionPing(CoreSeleniumTestCase):
    """ping.js warns a user who is filling in QC that their work can no longer be saved."""

    def setUp(self):
        super().setUp()
        unit = qa_utils.create_unit()
        test_list = qa_utils.create_test_list(name='Daily Output')
        test = qa_utils.create_test(name='output')
        qa_utils.create_test_list_membership(test_list, test)
        utc = qa_utils.create_unit_test_collection(unit=unit, test_collection=test_list)
        self.user.groups.add(utc.assigned_to)
        qa_utils.create_status(is_default=True)
        sl_utils.create_service_event_status(is_default=True)
        sl_utils.create_unit_service_area(unit)
        sl_utils.create_service_type()
        self.url = reverse('perform_qa', kwargs={'pk': utc.pk})

    def ping_log(self):
        return self.driver.execute_script('return window.pingLog;')

    def submit_disabled(self):
        return self.driver.execute_script('return document.getElementById("submit-qa").disabled;')

    @override_settings(PING_INTERVAL_S=1)
    def test_lost_session_disables_submit_after_three_failed_pings_and_recovers(self):
        """Losing the session must block Submit (after three misses, not one); logging back in must unblock it.

        If this breaks, a user can fill in a whole test list and only find out
        on Submit that they were logged out and the results are gone.
        """
        self.login()
        self.open(self.url)
        self.wait_for_element('#submit-qa')
        self.wait_until(lambda: self.driver.execute_script('return window.userIsAuthenticated === true;'))
        # qa.js keeps Submit disabled while it runs the first calculations.
        self.wait_until(lambda: not self.submit_disabled(), message='submit never enabled after page load')

        # Record, after each ping has been handled, what it said and whether
        # Submit was disabled at that moment. jQuery fires the global
        # ajaxComplete event after the request's own success/error callbacks,
        # so ping.js has already acted on the reply when this runs.
        self.driver.execute_script("""
            window.pingLog = [];
            jQuery(document).ajaxComplete(function(event, xhr, settings){
                if (settings.url === QAURLs.PING){
                    window.pingLog.push({
                        loggedIn: !!(xhr.responseJSON && xhr.responseJSON.logged_in),
                        disabled: document.getElementById('submit-qa').disabled
                    });
                }
            });
        """)
        self.wait_until(
            lambda: any(p['loggedIn'] for p in self.ping_log()), message='no ping ever reported logged in'
        )

        # Lose the session the way an expired or cleared cookie would.
        pings_before = len(self.ping_log())
        self.driver.delete_cookie('sessionid')

        self.wait_until(self.submit_disabled, message='submit was never disabled')
        popover = self.wait_for_visible('.popover')
        assert 'Server is not responding or you may have been logged out' in popover.text
        submit = self.driver.find_element(By.ID, 'submit-qa')
        assert 'btn-danger' in submit.get_attribute('class')
        assert 'Please wait until QATrack+ can reach the server' in submit.get_attribute('title')

        # A ping already on its way when the cookie went may still come back logged in; skip it.
        after = self.ping_log()[pings_before:]
        while after and after[0]['loggedIn']:
            after.pop(0)
        assert [(p['loggedIn'], p['disabled']) for p in after[:3]] == [(False, False), (False, False), (False, True)]

        # Log back in from another tab, as the warning tells the user to.
        perform_tab = self.driver.current_window_handle
        self.driver.switch_to.new_window('tab')
        self.login()
        self.driver.close()
        self.driver.switch_to.window(perform_tab)

        self.wait_until(lambda: not self.submit_disabled(), message='submit was never re-enabled')
        self.wait_for_invisible('.popover')
        submit = self.driver.find_element(By.ID, 'submit-qa')
        assert 'btn-primary' in submit.get_attribute('class')
        assert 'btn-danger' not in submit.get_attribute('class')
        # Logging in rotates the CSRF token; the form must carry the new one or Submit would be refused.
        csrf_cookie = self.driver.get_cookie('csrftoken')['value']
        form_tokens = self.driver.execute_script(
            'return Array.from(document.querySelectorAll("input[name=csrfmiddlewaretoken]"))'
            '.map(function(i){ return i.value; });'
        )
        assert form_tokens and set(form_tokens) == {csrf_cookie}


class TestNavigationGating(CoreSeleniumTestCase):
    """site_base.html shows each menu only to users with the matching permission."""

    def test_perform_only_user_sees_qc_menu_but_no_service_log_or_admin(self):
        """A therapist who may only perform QC must not be offered review, Service Log, faults or admin pages."""
        therapist = create_limited_user()
        self.login(user=therapist, password='password')
        self.open(reverse('home'))
        links = self.menu_links()

        for name in ('choose_unit', 'all_lists', 'qa_by_overdue', 'in_progress', 'account-details', 'auth_logout'):
            assert reverse(name) in links, name
        for name in ('sl_dash', 'sl_new', 'sl_list_all', 'unreviewed', 'overview', 'fault_list', 'charts',
                     'reports', 'admin:index', 'groups-app', 'unit_available_time', 'parts_list'):
            assert reverse(name) not in links, name

    def test_superuser_sees_every_menu(self):
        """A superuser must be offered every section, including the admin-only links."""
        self.login()
        self.open(reverse('home'))
        links = self.menu_links()

        for name in ('choose_unit', 'all_lists', 'unreviewed', 'overview', 'sl_dash', 'sl_new', 'sl_list_all',
                     'fault_list', 'fault_list_unreviewed', 'charts', 'reports', 'parts_list', 'admin:index',
                     'groups-app', 'unit_available_time', 'auth_logout'):
            assert reverse(name) in links, name

    def test_fault_reviewer_sees_fault_log_menu(self):
        """A user whose only fault permission is 'Can Review Faults' must still reach the unreviewed faults list."""
        reviewer = create_limited_user(uname='reviewer', perms=['faults.can_review'])
        self.login(user=reviewer, password='password')
        self.open(reverse('home'))

        assert reverse('fault_list_unreviewed') in self.menu_links()

    def test_non_staff_with_unit_availability_permission_sees_link(self):
        """A non-staff user allowed to change unit available times must be offered the Unit Available Times page."""
        scheduler = create_limited_user(uname='scheduler', perms=['units.change_unitavailabletime'])
        self.login(user=scheduler, password='password')
        self.open(reverse('home'))

        assert reverse('unit_available_time') in self.menu_links()

    def test_return_to_service_viewer_sees_rts_link(self):
        """A user who may only view Return To Service QC must be offered the RTS QC list."""
        viewer = create_limited_user(uname='rtsviewer', perms=['service_log.view_returntoserviceqa'])
        self.login(user=viewer, password='password')
        self.open(reverse('home'))

        assert reverse('rtsqa_list_all') in self.menu_links()

    def test_parts_viewer_sees_parts_list(self):
        """A user who may only view parts must be offered the parts list."""
        viewer = create_limited_user(uname='partsviewer', perms=['parts.view_part'])
        self.login(user=viewer, password='password')
        self.open(reverse('home'))

        assert reverse('parts_list') in self.menu_links()


class TestHomepageBoxes(CoreSeleniumTestCase):
    """homepage.html shows the Perform, Review and Service Log boxes by permission."""

    def box_titles(self):
        return [el.text.strip() for el in self.driver.find_elements(By.CSS_SELECTOR, '.content .box .box-title')]

    def test_perform_only_user_sees_only_perform_box(self):
        """A user who may only perform QC must not be shown the Review or Service Log boxes."""
        therapist = create_limited_user()
        self.login(user=therapist, password='password')
        self.open(reverse('home'))
        self.wait_for_text('.page-header h1', 'Welcome to QATrack+')

        assert self.box_titles() == ['Perform QC']

    def test_reviewer_sees_review_and_service_log_boxes(self):
        """'Can review tests' must add the Review QC and Service Log boxes, with the review links in them."""
        physicist = create_limited_user(uname='physicist', perms=['qa.can_review'])
        self.login(user=physicist, password='password')
        self.open(reverse('home'))
        self.wait_for_text('.page-header h1', 'Welcome to QATrack+')

        assert self.box_titles() == ['Perform QC', 'Review QC', 'Service Log']
        content_links = self.driver.execute_script(
            'return Array.from(document.querySelectorAll(".content a.list-group-item"))'
            '.map(function(a){ return a.getAttribute("href"); });'
        )
        assert reverse('unreviewed') in content_links
        assert reverse('choose_review_unit') in content_links
        # Seeing the Service Log box does not grant service log permissions.
        assert reverse('sl_new') not in content_links


class TestLanguageSwitcher(CoreSeleniumTestCase):

    def choose_language(self, code):
        """Pick a language from the globe menu, the way a user does (hover, then click)."""
        dropdown = self.wait_for_visible('#lang-dropdown')
        ActionChains(self.driver).move_to_element(dropdown).perform()
        option = self.wait_for_visible('#lang-dropdown a[data-lang="%s"]' % code.upper())
        with self.wait_for_page_load():
            ActionChains(self.driver).move_to_element(option).click().perform()

    def test_switch_to_french_and_back(self):
        """Choosing Français must translate the page and stick across pages; choosing English must undo it."""
        self.login()
        self.open(reverse('home'))
        self.wait_for_text('.page-header h1', 'Welcome to QATrack+')

        self.choose_language('fr')
        self.wait_for_text('.page-header h1', 'Bienvenue sur QATrack+')
        assert self.driver.find_element(By.TAG_NAME, 'html').get_attribute('lang') == 'fr'
        assert urlparse(self.driver.current_url).path == reverse('home')

        # The choice is remembered on the next page, not just the one it was made on.
        self.open(reverse('account-details'))
        assert 'Déconnexion' in self.driver.execute_script(
            'return document.querySelector(\'aside.control-sidebar a[href="%s"]\').textContent;' % reverse('auth_logout')
        )

        self.open(reverse('home'))
        self.choose_language('en')
        self.wait_for_text('.page-header h1', 'Welcome to QATrack+')
        assert self.driver.find_element(By.TAG_NAME, 'html').get_attribute('lang') == 'en'


class TestAjaxComments(CoreSeleniumTestCase):

    def setUp(self):
        super().setUp()
        status = qa_utils.create_status(name='Unreviewed', slug='unreviewed')
        test_instance = qa_utils.create_test_instance(created_by=self.user, status=status)
        self.tli = test_instance.test_list_instance

    def test_posted_comment_is_appended_and_saved(self):
        """A comment posted on the review page must appear without a reload and be stored against the session."""
        text = 'Output checked against the backup chamber, eh.'
        self.login()
        self.open(reverse('review_test_list_instance', kwargs={'pk': self.tli.pk}))

        post = self.wait_for_element('#post-comment')
        assert not post.is_enabled()
        textarea = self.driver.find_element(By.ID, 'id_comment')
        self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', textarea)
        textarea.send_keys(text)
        self.wait_until(lambda: post.is_enabled(), message='Post Comment never enabled')
        self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', post)
        ActionChains(self.driver).move_to_element(post).click().perform()

        self.wait_for_text('#comments .box-comment .comment', text)
        self.wait_for_ajax()
        # The box is cleared, ready for another comment.
        assert textarea.get_attribute('value') == ''
        assert not post.is_enabled()

        comment = Comment.objects.get()
        assert comment.comment == text
        assert comment.user == self.user
        assert comment.object_pk == str(self.tli.pk)
        assert comment.content_type.model == 'testlistinstance'
        assert self.driver.find_element(By.ID, 'c%d' % comment.pk).is_displayed()


class TestErrorPage(CoreSeleniumTestCase):

    def test_unknown_url_shows_site_404_page(self):
        """A bad link must land on QATrack+'s own error page, with the menus still there to find a way back."""
        self.login()
        self.open('/qc/this-page-does-not-exist/')

        heading = self.wait_for_visible('.page-header h1')
        assert heading.text == 'Error 404 : Resource not found'
        assert 'can not be found' in self.driver.find_element(By.CSS_SELECTOR, '.content p.text-center').text
        assert 'Error 404' in self.driver.title
        # Still inside the site layout, logged in, with the normal menus.
        assert self.driver.find_elements(By.CSS_SELECTOR, self.logout_href())
        assert reverse('choose_unit') in self.menu_links()
