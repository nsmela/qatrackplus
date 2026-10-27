from django.test import TestCase
from django.urls import reverse

from qatrack.parts import models as p_models
from qatrack.parts.templatetags.part_tags import part_list_in_storage
from qatrack.qa.tests import utils as qa_utils
from qatrack.service_log.tests import utils as sl_utils


class TestRoomAdminPages(TestCase):
    """The Room admin renders blank Storage inline rows (unsaved instances);
    these must not trip Django's "needs a primary key" related-manager check."""

    def setUp(self):
        self.user = qa_utils.create_user(is_superuser=True)
        self.client.force_login(self.user)
        self.site = sl_utils.create_site()
        self.add_url = reverse('admin:parts_room_add')

    def test_add_page_loads(self):
        resp = self.client.get(self.add_url)
        self.assertEqual(resp.status_code, 200)

    def test_add_room_with_storage_inline(self):
        resp = self.client.get(self.add_url)
        prefix = resp.context['inline_admin_formsets'][0].formset.prefix
        data = {
            'name': 'Room N13',
            'site': self.site.pk,
            '%s-TOTAL_FORMS' % prefix: '1',
            '%s-INITIAL_FORMS' % prefix: '0',
            '%s-MIN_NUM_FORMS' % prefix: '0',
            '%s-MAX_NUM_FORMS' % prefix: '1000',
            '%s-0-location' % prefix: 'Shelf A',
            '%s-0-description' % prefix: 'Top shelf',
        }
        resp = self.client.post(self.add_url, data)
        self.assertEqual(resp.status_code, 302)
        room = p_models.Room.objects.get(name='Room N13', site=self.site)
        locations = set(p_models.Storage.objects.filter(room=room).values_list('location', flat=True))
        # Room.save creates the generic (no location) storage; the inline adds Shelf A.
        self.assertEqual(locations, {None, 'Shelf A'})

    def test_change_page_loads_and_lists_parts(self):
        room = sl_utils.create_room(site=self.site)
        storage = sl_utils.create_storage(room=room, location='Bin 1')
        part = sl_utils.create_part(name='Widget N13')
        sl_utils.create_part_storage_collection(part=part, storage=storage, quantity=2)

        resp = self.client.get(reverse('admin:parts_room_change', args=[room.pk]))
        self.assertEqual(resp.status_code, 200)
        # Saved storage still lists its parts.
        self.assertContains(resp, 'Widget N13')


class TestPartListInStorageTag(TestCase):

    def test_unsaved_storage_returns_empty(self):
        self.assertEqual(part_list_in_storage(p_models.Storage()), '')

    def test_none_returns_empty(self):
        self.assertEqual(part_list_in_storage(None), '')
