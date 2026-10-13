"""The shared harness for QATrack+'s browser (Selenium) tests.

Every browser test inherits from `SeleniumTests` (the driver and its helpers)
or, more usually, from `SeleniumTestCase` (which adds a user and a way to log
in). Both carry the `selenium` pytest marker, so::

    uv run pytest -m selenium            # only the browser tests
    uv run pytest -m "not selenium"      # everything else

How the browser is started is controlled by a handful of settings. Each can
be set in `qatrack/local_test_settings.py`, or as an environment variable of
the same name, which wins - handy for CI and for a one-off headless run::

    SELENIUM_HEADLESS=1 SELENIUM_BROWSER=chromium uv run pytest -m selenium

    SELENIUM_BROWSER                 'chromium' or 'firefox' (the default)
    SELENIUM_HEADLESS                run the browser without a window
    SELENIUM_VIRTUAL_DISPLAY         run inside xvfb (Linux only; implies headless)
    SELENIUM_CHROMIUM_DRIVER_PATH    path to chromedriver
    SELENIUM_CHROMIUM_BINARY_PATH    path to the Chromium/Chrome binary itself
    SELENIUM_FIREFOX_DRIVER_PATH     path to geckodriver
    SELENIUM_FIREFOX_BINARY_PATH     path to the Firefox binary itself
    SELENIUM_TIMEOUT                 seconds to wait for a condition (default 10)
    SELENIUM_IMPLICIT_WAIT           seconds find_element keeps looking (default 2)
    SELENIUM_ARTIFACTS_DIR           where failure screenshots go
                                     (default 'selenium-screenshots')

When a test fails, a screenshot, the page's HTML and the browser's console
log are written to SELENIUM_ARTIFACTS_DIR, named after the test. A browser
test that fails with nothing but "TimeoutException" is close to undebuggable
otherwise - the screenshot usually shows the reason at a glance.
"""

import os
import re
import shutil
import time
from contextlib import contextmanager
from functools import wraps

import pytest
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import WSGIServer
from django.test import TransactionTestCase
from django.test.testcases import LiveServerThread
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command
from selenium.webdriver.remote.errorhandler import ErrorHandler
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as e_c
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.wait import WebDriverWait

from qatrack.accounts.tests.utils import create_user

TRUTHY = ('1', 'true', 'yes', 'on')


def selenium_setting(name, default=None):
    """Look a SELENIUM_* setting up in the environment first, then in Django's settings.

    The environment wins so that a single run can be switched to headless (or
    to another browser) without editing a settings file.
    """
    if name in os.environ:
        value = os.environ[name]
        if isinstance(default, bool):
            return value.strip().lower() in TRUTHY
        if isinstance(default, int | float) and not isinstance(default, bool):
            return type(default)(value)
        return value

    value = getattr(settings, name, default)
    # settings.py ships SELENIUM_BROWSER = '' and empty driver paths; treat
    # "set but empty" the same as "not set" so the default still applies.
    if value in ('', None):
        return default
    return value


# From http://stackoverflow.com/a/20559494
def retry_if_exception(ex, max_retries, sleep_time=None, reraise=True):
    """Retry the wrapped function when it raises `ex`, up to `max_retries` times.

    Only `ex` is retried. Anything else - an AssertionError, a KeyboardInterrupt -
    is a real answer and is raised straight away.
    """

    def outer(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            assert max_retries > 0
            x = max_retries
            while x:
                try:
                    return func(*args, **kwargs)
                except ex:
                    x -= 1
                    if x == 0 and reraise:
                        raise
                if sleep_time is not None:
                    time.sleep(sleep_time)

        return wrapper

    return outer


@retry_if_exception(WebDriverException, 5, sleep_time=1)
def WebElement_click(self):
    """
    Monkey patches the element click command to work around issue with
    later versions of webdrivers that won't click on an element if it
    is not in view. The element is scrolled to the middle of the window:
    scrolled to the top it sits under the fixed navigation bar, and the
    click lands on the bar instead ("element click intercepted").
    """
    self.parent.execute_script("arguments[0].scrollIntoView({block: 'center'});", self)
    return self._execute(Command.CLICK_ELEMENT)


orig_send_keys = WebElement.send_keys


@retry_if_exception(WebDriverException, 5, sleep_time=1)  # noqa: E302
def WebElement_send_keys(self, *keys):
    """Monky patch send_keys to ensure element is in view"""
    self.parent.execute_script("arguments[0].scrollIntoView({block: 'center'});", self)
    return orig_send_keys(self, *keys)


# Guarded so that importing this module twice (or alongside anything else that
# patches WebElement) cannot wrap the retries around themselves.
if not getattr(WebElement, '_qatrack_patched', False):
    WebElement.click = WebElement_click
    WebElement.send_keys = WebElement_send_keys
    WebElement._qatrack_patched = True


class SerialWSGIServer(WSGIServer):
    """Django's development WSGI server, answering one request at a time.

    Accepts (and ignores) `connections_override` so LiveServerThread can create
    it exactly as it creates the threaded server. LiveServerThread.run() has
    already handed the test's database connections to the server thread.
    """

    def __init__(self, *args, connections_override=None, **kwargs):
        super().__init__(*args, **kwargs)


class SerialLiveServerThread(LiveServerThread):
    """A live server that handles requests one after another.

    With SQLite the tests and every request thread of Django's threaded live
    server share one in-memory connection. Many QATrack+ pages fire two or
    more ajax requests at once (choosing a unit on the service event form,
    loading the groups page), and requests running together on that one
    connection fail at random with a 500 or 401 ("bad parameter or other API
    misuse"). Answering them in turn removes the race and changes nothing
    the page can observe. A non-threaded server also sends
    "Connection: close", so the browser's keep-alive connections cannot hold
    it up.
    """

    server_class = SerialWSGIServer


orig_check_response = ErrorHandler.check_response


def ErrorHandler_check_response(self, response):
    """Report Chrome's "node does not belong to the document" as the stale element it is.

    When a page is replaced while WebDriver is looking at one of its elements,
    chromedriver sometimes answers with this generic "unknown error" instead of
    a StaleElementReferenceException. Selenium's own staleness_of() and
    every `ignored_exceptions=(StaleElementReferenceException,)` then miss it,
    and a test that was simply waiting for the next page fails at random.
    """
    try:
        return orig_check_response(self, response)
    except StaleElementReferenceException:
        raise
    except WebDriverException as e:
        if 'does not belong to the document' in (e.msg or ''):
            raise StaleElementReferenceException(e.msg, e.screen, e.stacktrace) from e
        raise


if not getattr(ErrorHandler, '_qatrack_patched', False):
    ErrorHandler.check_response = ErrorHandler_check_response
    ErrorHandler._qatrack_patched = True


def _safe_filename(name):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', name).strip('_')[:180]


@pytest.mark.selenium
class SeleniumTests(StaticLiveServerTestCase):
    """A live server, one browser per test class, and helpers for driving it."""

    server_thread_class = SerialLiveServerThread

    @classmethod
    def setUpClass(cls):
        use_virtual_display = selenium_setting('SELENIUM_VIRTUAL_DISPLAY', False)
        # A virtual display has always implied headless here; SELENIUM_HEADLESS
        # asks for the browser's own headless mode with no xvfb needed, which
        # is the only one of the two that works on Windows and macOS.
        headless = selenium_setting('SELENIUM_HEADLESS', False) or use_virtual_display
        browser_setting = selenium_setting('SELENIUM_BROWSER', 'firefox')
        cls.timeout = selenium_setting('SELENIUM_TIMEOUT', 10)
        implicit_wait = selenium_setting('SELENIUM_IMPLICIT_WAIT', 2)

        cls.display = None
        cls.driver = None

        if use_virtual_display:
            # Make sure xvfb is installed
            from pyvirtualdisplay import Display
            cls.display = Display(visible=0, size=(1920, 1080))
            cls.display.start()

        try:
            if browser_setting in ('chromium', 'chrome'):
                cls.driver = cls._start_chromium(headless)
            else:
                cls.driver = cls._start_firefox(headless)

            orig_find_element = cls.driver.find_element

            @retry_if_exception(WebDriverException, 2, sleep_time=1)
            def WebElement_find_element(*args, **kwargs):
                """Monky patch find element to allow retries"""
                return orig_find_element(*args, **kwargs)

            cls.driver.find_element = WebElement_find_element

            # Three different waits, on purpose:
            #  - page loads get the longest, because the first request to a
            #    fresh live server compiles every template it touches;
            #  - explicit waits (self.wait.until) get `timeout`;
            #  - the implicit wait stays short, because it is also how long
            #    every find_elements() that correctly finds *nothing* takes.
            cls.driver.set_page_load_timeout(cls.timeout * 3)
            cls.driver.set_script_timeout(cls.timeout * 3)
            cls.driver.implicitly_wait(implicit_wait)

            cls.driver.set_window_position(0, 0)
            cls.driver.set_window_size(1920, 1080)
            cls.wait = WebDriverWait(cls.driver, cls.timeout)

            super().setUpClass()
        except BaseException:
            # Without this a failure here leaves a browser (and an Xvfb)
            # running for every class that fails to start.
            cls._stop_browser()
            raise

    @classmethod
    def _start_chromium(cls, headless):
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService

        chrome_options = ChromeOptions()
        binary_path = selenium_setting('SELENIUM_CHROMIUM_BINARY_PATH', '')
        if binary_path:
            chrome_options.binary_location = binary_path
        if headless:
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--window-size=1920,1080')
        # Lets a failing test report what the page logged to its console.
        chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        # Keep Chrome's password manager out of the way. The test users all log
        # in with "password", and newer Chrome answers a known-leaked password
        # with a "change your password" bubble that takes keyboard focus from
        # the page, so later typing and clicks go nowhere.
        chrome_options.add_experimental_option('prefs', {
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False,
            'profile.password_manager_leak_detection': False,
        })
        chrome_options.add_argument('--disable-features=PasswordLeakDetection')

        driver_path = selenium_setting('SELENIUM_CHROMIUM_DRIVER_PATH', '')
        if driver_path:
            service = ChromeService(executable_path=driver_path)
            return webdriver.Chrome(service=service, options=chrome_options)
        return webdriver.Chrome(options=chrome_options)

    @classmethod
    def _start_firefox(cls, headless):
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        from selenium.webdriver.firefox.service import Service as FirefoxService

        ff_options = FirefoxOptions()
        binary_path = selenium_setting('SELENIUM_FIREFOX_BINARY_PATH', '')
        if binary_path:
            ff_options.binary_location = binary_path
        if headless:
            ff_options.add_argument('--headless')
            ff_options.add_argument('--width=1920')
            ff_options.add_argument('--height=1080')

        # Fall back to a geckodriver on the PATH, and failing that let
        # Selenium find (or fetch) one itself.
        driver_path = selenium_setting('SELENIUM_FIREFOX_DRIVER_PATH', '') or shutil.which('geckodriver')
        if driver_path:
            service = FirefoxService(executable_path=driver_path)
            return webdriver.Firefox(service=service, options=ff_options)
        return webdriver.Firefox(options=ff_options)

    @classmethod
    def _stop_browser(cls):
        driver = getattr(cls, 'driver', None)
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass
            cls.driver = None
        display = getattr(cls, 'display', None)
        if display is not None:
            display.stop()
            cls.display = None

    @classmethod
    def maximize(cls):

        if selenium_setting('SELENIUM_VIRTUAL_DISPLAY', False):
            for i in range(5):
                try:
                    cls.driver.maximize_window()
                    return
                except WebDriverException:
                    time.sleep(1)

        cls.driver.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls._stop_browser()
        super().tearDownClass()

    def tearDown(self):
        if self._test_failed():
            self.save_failure_artifacts()

        # One browser serves the whole class, so leave nothing behind for the
        # next test: no session cookie, no half-loaded page, no open dialog.
        try:
            self.driver.delete_all_cookies()
            self.driver.get("about:blank")
        except WebDriverException:
            pass
        super().tearDown()

    def _test_failed(self):
        """True if the test method (or setUp) has already failed. Works under pytest and unittest.

        `self._outcome.success` cannot be used for this: unittest resets it to
        True when tearDown starts. The result object still knows, though.
        """
        outcome = getattr(self, '_outcome', None)
        result = getattr(outcome, 'result', None)
        if result is None:
            return False

        # pytest's unittest integration keeps the exceptions on the result.
        # A skip is recorded the same way, and is not a failure.
        excinfo = getattr(result, '_excinfo', None)
        if excinfo:
            return any(not e.errisinstance(pytest.skip.Exception) for e in excinfo)

        # Plain unittest (manage.py test).
        recorded = list(getattr(result, 'errors', [])) + list(getattr(result, 'failures', []))
        return any(test is self for test, _ in recorded)

    def save_failure_artifacts(self):
        """Write a screenshot, the page source and the console log for the current page.

        Never raises: this runs while a test is already failing, and an error
        here would hide the one that matters.
        """
        try:
            directory = selenium_setting('SELENIUM_ARTIFACTS_DIR', 'selenium-screenshots')
            os.makedirs(directory, exist_ok=True)
            base = os.path.join(directory, _safe_filename(self.id()))

            self.driver.save_screenshot(base + '.png')

            with open(base + '.html', 'w', encoding='utf-8') as f:
                f.write('<!-- %s -->\n' % self.driver.current_url)
                f.write(self.driver.page_source)

            log = self.browser_log()
            if log:
                with open(base + '.console.log', 'w', encoding='utf-8') as f:
                    for entry in log:
                        f.write('%(level)s %(message)s\n' % entry)
        except Exception:  # noqa: BLE001
            pass

    def browser_log(self):
        """What the page has written to the browser console since this was last called.

        Chromium only - Firefox does not expose its console over WebDriver, so
        this returns an empty list there.
        """
        try:
            return self.driver.get_log('browser')
        except (WebDriverException, ValueError):
            return []

    def javascript_errors(self):
        """Console entries at SEVERE level: uncaught exceptions and failed requests."""
        return [entry for entry in self.browser_log() if entry.get('level') == 'SEVERE']

    @contextmanager
    def wait_for_page_load(self, timeout=None):
        old_page = self.driver.find_element(By.TAG_NAME, 'html')
        yield
        WebDriverWait(self.driver, timeout or self.timeout).until(staleness_of(old_page))

    @retry_if_exception(Exception, 2, sleep_time=1)
    def open(self, url):
        with self.wait_for_page_load():
            self.driver.execute_script("window.location.href='%s%s'" % (self.live_server_url, url))

    def wait_for_success(self):
        self.wait.until(
            e_c.presence_of_element_located((By.XPATH, '//ul[@class = "messagelist"]/li[@class = "success"]'))
        )

    def wait_for_ajax(self, timeout=None):
        """Wait until jQuery has no requests in flight.

        Most of QATrack+'s pages talk to the server through jQuery, so this is
        the honest replacement for `time.sleep()` after a click that triggers
        a request.
        """
        WebDriverWait(self.driver, timeout or self.timeout).until(
            lambda d: d.execute_script("return typeof jQuery === 'undefined' || jQuery.active === 0")
        )

    def wait_for_element(self, css_sel, timeout=None):
        """Wait for an element matching the CSS selector to exist, and return it."""
        return WebDriverWait(self.driver, timeout or self.timeout).until(
            e_c.presence_of_element_located((By.CSS_SELECTOR, css_sel))
        )

    def wait_for_visible(self, css_sel, timeout=None):
        """Wait for an element matching the CSS selector to be displayed, and return it."""
        return WebDriverWait(self.driver, timeout or self.timeout).until(
            e_c.visibility_of_element_located((By.CSS_SELECTOR, css_sel))
        )

    def wait_for_invisible(self, css_sel, timeout=None):
        """Wait for every element matching the CSS selector to be hidden or gone."""
        return WebDriverWait(self.driver, timeout or self.timeout).until(
            e_c.invisibility_of_element_located((By.CSS_SELECTOR, css_sel))
        )

    def wait_for_text(self, css_sel, text, timeout=None):
        """Wait for `text` to appear inside the element matching the CSS selector."""
        return WebDriverWait(self.driver, timeout or self.timeout).until(
            e_c.text_to_be_present_in_element((By.CSS_SELECTOR, css_sel), text)
        )

    def wait_until(self, condition, timeout=None, message=''):
        """Wait until `condition()` returns something truthy, and return it.

        `condition` takes no arguments, so it can check the database as easily
        as the page::

            self.wait_until(lambda: models.Fault.objects.count() == 1)
        """
        return WebDriverWait(self.driver, timeout or self.timeout).until(lambda d: condition(), message)

    def scroll_into_view(self, el_id):
        self.wait.until(e_c.presence_of_element_located((By.ID, el_id)))
        actions = ActionChains(self.driver)
        element = self.driver.find_element(By.ID, el_id)
        actions.move_to_element(element)
        time.sleep(1)
        try:
            actions.perform()
            self.driver.find_element(By.CSS_SELECTOR, "body").click()
            self.driver.execute_script("window.scrollTo(0, -200);")
        except:  # noqa: E722
            pass

    def scroll_into_view_css(self, css_sel):
        self.wait.until(e_c.presence_of_element_located((By.CSS_SELECTOR, css_sel)))
        actions = ActionChains(self.driver)
        element = self.driver.find_element(By.CSS_SELECTOR, css_sel)
        actions.move_to_element(element)
        time.sleep(1)
        try:
            actions.perform()
            self.driver.execute_script("window.scrollTo(0, -200);")
        except:  # noqa: E722
            pass

    def select_by_index(self, el_id, index):
        """Set force_select2= True when selecting a 0 index for a select2 element"""

        self.scroll_into_view(el_id)
        try:
            # select2?
            sel2 = self.driver.find_element(By.ID, "select2-%s-container" % el_id)
            sel2.click()
            time.sleep(0.1)
            els = self.driver.find_elements(By.CLASS_NAME, "select2-results__option")
            els[index].click()
        except:  # noqa: E722
            select_el = self.driver.find_element(By.ID, el_id)
            select = Select(select_el)
            try:
                select.select_by_index(index)
            except WebDriverException:
                val = select.options[index].get_attribute("value")
                self.driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_el, val)

    def select_by_text(self, el_id, text):

        self.scroll_into_view(el_id)
        try:
            select_el = self.driver.find_element(By.ID, el_id)
            select = Select(select_el)
            try:
                select.select_by_visible_text(text)
            except WebDriverException:
                found = False
                for opt in select.options:
                    if opt.text == text:
                        self.driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_el, opt.get_attribute("value"))
                        found = True
                        break
                if not found:
                    raise Exception("Option with text '%s' not found" % text)
        except WebDriverException:

            sel2 = self.driver.find_element(By.ID, "select2-%s-container" % el_id)
            sel2.click()

            els = self.driver.find_elements(By.CLASS_NAME, "select2-results__option")
            for el in els:
                if el.text == text:
                    el.click()
                    break

    def select_by_value(self, el_id, val):

        self.scroll_into_view(el_id)
        try:
            select_el = self.driver.find_element(By.ID, el_id)
            select = Select(select_el)
            try:
                select.select_by_value(val)
            except WebDriverException:
                found = False
                for opt in select.options:
                    if opt.get_attribute("value") == val:
                        self.driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_el, val)
                        found = True
                        break
                if not found:
                    raise Exception("Option with value '%s' not found" % val)
        except WebDriverException:

            sel2 = self.driver.find_element(By.ID, "select2-%s-container" % el_id)
            sel2.click()

            els = self.driver.find_elements(By.CLASS_NAME, "select2-results__option")
            for el in els:
                if el.get_attribute('id').endswith(val):
                    el.click()
                    break

    def send_keys(self, el_id, text):
        for i in range(3):
            try:
                self.scroll_into_view(el_id)
                self.driver.find_element(By.ID, el_id).send_keys(text)
                break
            except:  # noqa: E722
                if i == 2:
                    raise
                else:
                    time.sleep(1)

    def click(self, el_id, scroll=True):
        if scroll:
            self.scroll_into_view(el_id)
        element = self.driver.find_element(By.ID, el_id)
        try:
            element.click()
        except:  # noqa: E722
            self.driver.execute_script("arguments[0].click();", element)

    def click_by_css_selector(self, css_sel):
        self.scroll_into_view_css(css_sel)
        element = self.driver.find_element(By.CSS_SELECTOR, css_sel)
        try:
            element.click()
        except:  # noqa: E722
            self.driver.execute_script("arguments[0].click();", element)

    def click_by_link_text(self, link_text):
        for i in range(3):
            try:
                self.wait.until(e_c.presence_of_element_located((By.LINK_TEXT, link_text)))
                self.driver.find_element(By.LINK_TEXT, link_text).click()
                break
            except:  # noqa: E722
                if i == 2:
                    raise
                else:
                    time.sleep(1)


class SeleniumTestCase(SeleniumTests, TransactionTestCase):
    """`SeleniumTests` plus a superuser and the means to log in as them.

    This is the class to inherit from for a new browser test. It is a
    TransactionTestCase because the live server runs in another thread and
    must see what the test wrote: the database is flushed after every test,
    so each test starts empty and creates what it needs in setUp.
    """

    def setUp(self):
        super().setUp()
        self.password = 'password'
        self.user = create_user(pwd=self.password)

    def login(self, user=None, password=None):
        """Log in through the site's login page as `user` (default: self.user)."""
        user = user or self.user
        self.open("/accounts/login/")
        self.send_keys("id_username", user.username)
        self.send_keys("id_password", password or self.password)
        self.driver.find_element(By.CSS_SELECTOR, 'button').click()

        # Wait for proof that the login POST was handled and the redirect has
        # rendered. The logout link is inside {% if user.is_authenticated %}
        # in site_base.html, so its presence means both.
        #
        # This used to wait for "head > title", which every page has -
        # including the login page still on screen. It was satisfied
        # immediately, before the POST had even been sent, so a slow round
        # trip left the test unauthenticated. It then failed later, somewhere
        # else, as a timeout waiting for an element that only exists when
        # logged in - which looks like an unrelated flake.
        self.wait.until(
            e_c.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="logout"]'))
        )

    def load_main(self):
        self.login()
        self.open("")

    def load_admin(self):
        """Log in and land on the admin index."""
        self.open("/admin/")
        self.send_keys("id_username", self.user.username)
        self.send_keys("id_password", self.password)
        self.driver.find_element(By.CSS_SELECTOR, 'button').click()

        # #user-tools is only rendered by the admin for a logged in staff
        # user, so - like the logout link in login() above - it proves the
        # login was handled. "head > title" proved nothing: the login page
        # has one too.
        self.wait.until(e_c.presence_of_element_located((By.ID, 'user-tools')))
