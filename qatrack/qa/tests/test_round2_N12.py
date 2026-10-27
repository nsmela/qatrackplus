from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils


class TestUnitTestCollectionAdminWithoutAssignedTo(TestCase):
    """Assignments whose group was deleted (assigned_to is SET_NULL) must not break the list page"""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)
        self.url = reverse('admin:qa_unittestcollection_changelist')

    def make_unassigned_utc(self):
        group = Group.objects.create(name='Doomed group')
        utc = qa_utils.create_unit_test_collection(assigned_to=group)
        # deleting the group is how real installs end up with no assigned_to
        group.delete()
        utc.refresh_from_db()
        assert utc.assigned_to_id is None
        return utc

    def test_column_returns_none_when_unassigned(self):
        utc = self.make_unassigned_utc()
        assert qa_admin.assigned_to_name(utc) is None

    def test_column_returns_group_name_when_assigned(self):
        group = Group.objects.create(name='Physics')
        utc = qa_utils.create_unit_test_collection(assigned_to=group)
        assert qa_admin.assigned_to_name(utc) == 'Physics'

    def test_changelist_renders_with_unassigned_utc(self):
        self.make_unassigned_utc()
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert 'Not assigned' in resp.content.decode()

    def test_changelist_orders_by_assigned_to_with_unassigned_utc(self):
        self.make_unassigned_utc()
        qa_utils.create_unit_test_collection(assigned_to=Group.objects.create(name='Physics'))
        cols = qa_admin.UnitTestCollectionAdmin.list_display
        idx = cols.index(qa_admin.assigned_to_name)
        for order in (str(idx), '-%d' % idx):
            resp = self.client.get(self.url, {'o': order})
            assert resp.status_code == 200
        assert qa_models.UnitTestCollection.objects.filter(assigned_to=None).count() == 1
