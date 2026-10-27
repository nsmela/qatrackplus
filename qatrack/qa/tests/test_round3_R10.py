from django.template import loader
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa.tests import utils as qa_utils

CARD_IDS = ['tl-details-card', 'tl-attachments-card', 'tl-parents-card', 'tl-tests-card']


def card_order(content):
    """The builder card ids in the order they appear on the page (ids that aren't there are left out)."""
    found = [(content.index('id="%s"' % cid), cid) for cid in CARD_IDS if 'id="%s"' % cid in content]
    return [cid for _, cid in sorted(found)]


class TestParentsCardOrder(TestCase):
    """R10: the edit page reads Details, Attachments, Parent Test List Memberships, Tests & Sublists."""

    def setUp(self):
        create_user(is_superuser=True, uname='super', pwd='pwd')
        self.client.login(username='super', password='pwd')
        self.tl = qa_utils.create_test_list(name='R10 list')
        qa_utils.create_test_list_membership(test_list=self.tl, test=qa_utils.create_test(name='R10 test'))
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def test_change_page_order_without_parent(self):
        content = self.client.get(self.url).content.decode()
        self.assertEqual(card_order(content), CARD_IDS)
        self.assertEqual(content.count('id="tl-parents-card"'), 1)
        self.assertIn('class="tl-parents-card tl-parents-empty-card"', content)
        self.assertIn("This test list isn't used as a sublist in any other test list.", content)

    def test_change_page_order_with_parent(self):
        parent = qa_utils.create_test_list(name='R10 parent')
        qa_utils.create_sublist(parent_test_list=parent, child_test_list=self.tl)
        content = self.client.get(self.url).content.decode()
        self.assertEqual(card_order(content), CARD_IDS)
        self.assertEqual(content.count('id="tl-parents-card"'), 1)
        self.assertNotIn('class="tl-parents-card tl-parents-empty-card"', content)
        # the parent link sits inside the parents card, before the Tests & Sublists card
        link = 'href="%s"' % reverse('admin:qa_testlist_change', args=(parent.pk,))
        self.assertLess(content.index('id="tl-parents-card"'), content.index(link))
        self.assertLess(content.index(link), content.index('id="tl-tests-card"'))

    def test_change_page_order_in_machine_mode(self):
        unit = qa_utils.create_unit()
        qa_utils.create_unit_test_collection(unit=unit, test_collection=self.tl)
        content = self.client.get(self.url + '?unit=%d' % unit.pk).content.decode()
        self.assertEqual(card_order(content), CARD_IDS)

    def test_add_page_order(self):
        content = self.client.get(reverse('admin:qa_testlist_add')).content.decode()
        # the add page has no Parent Test List Memberships card
        self.assertEqual(card_order(content), ['tl-details-card', 'tl-attachments-card', 'tl-tests-card'])

    def test_preview_still_hides_parents_card(self):
        source = loader.get_template('admin/qa/testlist/testlist_assets.html').template.source
        start = source.index('function initViewTabs()')
        self.assertIn('document.getElementById("tl-parents-card")', source[start:start + 800])
