
import pytest
from django.db import transaction
from django.test import TransactionTestCase
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as e_c

from qatrack.accounts.tests.utils import create_user
from qatrack.faults.tests import utils as fault_utils
from qatrack.qatrack_core.tests.live import SeleniumTests


class BaseFaultsTests(SeleniumTests, TransactionTestCase):

    def setUp(self):
        with transaction.atomic():
            self.password = 'password'
            self.user = create_user(pwd=self.password, is_superuser=True)

    def login(self):
        self.open("/accounts/login/")
        self.send_keys("id_username", self.user.username)
        self.send_keys("id_password", self.password)
        self.driver.find_element(By.CSS_SELECTOR, 'button').click()
        self.wait.until(e_c.presence_of_element_located((By.CSS_SELECTOR, "head > title")))


@pytest.mark.selenium
class TestFaultsInlineEdit(BaseFaultsTests):

    def setUp(self):
        super().setUp()
        with transaction.atomic():
            self.fault = fault_utils.create_fault(user=self.user)
            self.url = reverse('fault_details', kwargs={'pk': self.fault.pk})

    def test_inline_edit_occurrence(self):
        self.login()
        self.open(self.url)
        
        # Click the edit button for occurrence
        edit_btn = self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-occurrence button[hx-get]")
        ))
        edit_btn.click()
        
        # Wait for form to load
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-occurrence form")
        ))
        
        # Ensure 'Save' and 'Cancel' buttons are there
        self.driver.find_element(By.CSS_SELECTOR, "#fault-section-occurrence form button[type='submit']")
        cancel_btn = self.driver.find_element(By.CSS_SELECTOR, "#fault-section-occurrence form button[hx-get]")
        
        # Click cancel
        cancel_btn.click()
        
        # Wait for form to disappear and edit button to be back
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-occurrence button[hx-get]")
        ))

    def test_inline_edit_fault_types(self):
        self.login()
        self.open(self.url)
        
        edit_btn = self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-fault-types button[hx-get]")
        ))
        edit_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-fault-types form")
        ))
        
        cancel_btn = self.driver.find_element(By.CSS_SELECTOR, "#fault-section-fault-types form button[hx-get]")
        cancel_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-fault-types button[hx-get]")
        ))

    def test_inline_edit_related_ses(self):
        self.login()
        self.open(self.url)
        
        edit_btn = self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-related-ses button[hx-get]")
        ))
        edit_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-related-ses form")
        ))
        
        cancel_btn = self.driver.find_element(By.CSS_SELECTOR, "#fault-section-related-ses form button[hx-get]")
        cancel_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-related-ses button[hx-get]")
        ))

    def test_inline_edit_attachments(self):
        self.login()
        self.open(self.url)
        
        edit_btn = self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-attachments button[hx-get]")
        ))
        edit_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-attachments form")
        ))
        
        cancel_btn = self.driver.find_element(By.CSS_SELECTOR, "#fault-section-attachments form button[hx-get]")
        cancel_btn.click()
        
        self.wait.until(e_c.presence_of_element_located(
            (By.CSS_SELECTOR, "#fault-section-attachments button[hx-get]")
        ))
