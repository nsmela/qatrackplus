"""Browser tests for the parts pages: creating, editing and listing parts.

The storage table on the part form only works with JavaScript (parts/js/p_part.js).
Choosing a room fetches that room's locations by ajax, a new location can be typed
straight into the location box (a select2 "tag"), and whichever location ends up
chosen is copied into a hidden `storage_field` input. That hidden field is the one
the server actually reads. The Django test client tests in test_views.py have to
fill it in by hand, so only a browser can show that a real person's choices reach
the database. The cost box is masked as money ("$1,234.50") in the browser too.

Every test waits for the page the server answers with (and for jQuery to go quiet)
before it reads the database, because the live server and the test share one
in-memory SQLite connection.
"""

import os
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from selenium.webdriver.common.by import By

from qatrack.attachments.models import Attachment
from qatrack.parts import models as p_models
from qatrack.qatrack_core.tests.live import SeleniumTestCase
from qatrack.service_log.tests import utils as sl_utils


class PartsSeleniumTestCase(SeleniumTestCase):
    """Common data and helpers for the parts browser tests.

    One site with two rooms. The Store Room has two named shelves and the Bunker
    has one bin; each room also has the "no specific location" storage that every
    new room gets. Two suppliers and two part categories exist too.
    """

    def setUp(self):
        super().setUp()
        # sl_utils.create_site gives the site a slug; without one the page shown
        # after login fails to render.
        self.site = sl_utils.create_site(name='Main Campus')
        self.store_room = p_models.Room.objects.create(site=self.site, name='Store Room')
        self.bunker = p_models.Room.objects.create(site=self.site, name='Bunker')
        self.shelf_a = p_models.Storage.objects.create(room=self.store_room, location='Shelf A')
        self.shelf_b = p_models.Storage.objects.create(room=self.store_room, location='Shelf B')
        self.bin_9 = p_models.Storage.objects.create(room=self.bunker, location='Bin 9')

        self.acme = p_models.Supplier.objects.create(name='Acme Linac Supply')
        self.beta = p_models.Supplier.objects.create(name='Beta Medical')

        self.linac_parts = p_models.PartCategory.objects.create(name='Linac Parts')
        self.couch_parts = p_models.PartCategory.objects.create(name='Couch Parts')

    def create_part(self, name='Gantry bearing', part_number='GB-100', **kwargs):
        return p_models.Part.objects.create(name=name, part_number=part_number, **kwargs)

    # -- select2 -----------------------------------------------------------------------------------

    def select2_type_new(self, el_id, text):
        """Type `text` into a select2 that accepts new entries ("tags") and pick the new entry."""
        self.open_select2(el_id)
        search = self.wait_for_visible('.select2-container--open .select2-search__field')
        search.send_keys(text)
        option = self.wait.until(lambda d: self._open_select2_option('%s (new)' % text))
        self.click_element(option)
        self.wait_for_invisible('.select2-container--open .select2-results')

    def open_new_form(self):
        self.login()
        self.open(reverse('part_new'))
        self.wait_for_visible('#id_storage-0-room + .select2')
        self.wait_for_ajax()

    def open_edit_form(self, part):
        self.login()
        self.open(reverse('part_edit', kwargs={'pk': part.pk}))
        self.wait_for_visible('#id_storage-0-room + .select2')
        self.wait_for_ajax()

    def fill_required_fields(self, name='Gantry bearing', part_number='GB-100'):
        self.type_into('id_name', name)
        self.type_into('id_part_number', part_number)

    def choose_room(self, row, room_text):
        """Choose a room in storage row `row` and wait for its locations to be loaded by ajax."""
        self.select2_choose('id_storage-%d-room' % row, room_text)
        self.wait_for_ajax()
        self.wait.until(
            lambda d: '<no specific location>' in self.option_texts('id_storage-%d-location' % row)
        )

    def save_part(self, button='submit'):
        """Click a submit button and wait for the parts list the server redirects to."""
        self.click_css('input[type=submit][name=%s]' % button)
        self.wait_for_element('#listable-table-parts_list')
        self.wait_for_ajax()

    def success_message(self):
        return self.wait_for_visible('.alert-success').text


class TestPartStorage(PartsSeleniumTestCase):

    def wait_for_shelf_a_reloaded(self):
        """Wait until storage row 0 shows the Store Room's locations with Shelf A chosen."""
        self.wait.until(lambda d: 'Shelf B' in self.option_texts('id_storage-0-location'))
        assert self.option_texts('id_storage-0-location') == ['<no specific location>', 'Shelf A', 'Shelf B']
        assert self.value_of('id_storage-0-location') == str(self.shelf_a.pk)
        assert self.value_of('id_storage-0-storage_field') == str(self.shelf_a.pk)

    def test_choosing_a_room_offers_only_that_rooms_locations(self):
        """Choosing a room must load that room's locations, and only those, into the location box.

        If the ajax reload broke, a part could only ever be stored "nowhere in
        particular", or worse, in a shelf belonging to another room.
        """
        self.open_new_form()
        assert self.value_of('id_storage-0-location') is None

        self.choose_room(0, 'Store Room (Main Campus)')
        assert self.option_texts('id_storage-0-location') == ['<no specific location>', 'Shelf A', 'Shelf B']

        self.choose_room(0, 'Bunker (Main Campus)')
        self.wait.until(lambda d: 'Bin 9' in self.option_texts('id_storage-0-location'))
        assert self.option_texts('id_storage-0-location') == ['<no specific location>', 'Bin 9']
        assert self.javascript_errors() == []

    def test_new_part_is_stored_in_the_chosen_location_and_quantity(self):
        """The room, location and quantity chosen in a storage row must be saved against the new part."""
        self.open_new_form()
        self.fill_required_fields()
        self.choose_room(0, 'Store Room (Main Campus)')
        self.select2_choose('id_storage-0-location', 'Shelf B')
        assert self.value_of('id_storage-0-storage_field') == str(self.shelf_b.pk)
        self.type_into('id_storage-0-quantity', '4')

        self.save_part()

        assert 'New part GB-100 - Gantry bearing added' in self.success_message()
        part = p_models.Part.objects.get()
        psc = p_models.PartStorageCollection.objects.get()
        assert (psc.part, psc.storage, psc.quantity) == (part, self.shelf_b, 4)
        assert part.quantity_current == 4

    def test_room_without_a_location_stores_part_in_the_room_itself(self):
        """Choosing only a room must store the part in that room's "no specific location" storage."""
        self.open_new_form()
        self.fill_required_fields()
        self.choose_room(0, 'Bunker (Main Campus)')
        self.type_into('id_storage-0-quantity', '2')

        self.save_part()

        psc = p_models.PartStorageCollection.objects.get()
        assert psc.storage.room == self.bunker
        assert psc.storage.location is None
        assert psc.quantity == 2

    def test_typed_new_location_creates_that_storage(self):
        """A location typed into the location box must be created as new storage in the chosen room."""
        self.open_new_form()
        self.fill_required_fields()
        self.choose_room(0, 'Store Room (Main Campus)')
        self.select2_type_new('id_storage-0-location', 'Top Drawer')
        assert self.value_of('id_storage-0-storage_field') == '__new__Top Drawer'
        self.type_into('id_storage-0-quantity', '3')

        self.save_part()

        storage = p_models.Storage.objects.get(location='Top Drawer')
        assert storage.room == self.store_room
        psc = p_models.PartStorageCollection.objects.get()
        assert (psc.storage, psc.quantity) == (storage, 3)

    def submit_with_new_location_but_no_part_number(self, location):
        """Fill a storage row with a typed new location, leave the part number out, and submit.

        Returns once the form has come back with its "Please correct the errors"
        message. The browser log is emptied first, so later checks only see
        errors from the page that came back.
        """
        self.open_new_form()
        self.type_into('id_name', 'Gantry bearing')
        self.choose_room(0, 'Store Room (Main Campus)')
        self.select2_type_new('id_storage-0-location', location)
        self.type_into('id_storage-0-quantity', '3')
        self.browser_log()
        self.click_css('input[type=submit][name=submit]')
        self.wait_for_text('.alert-error', 'Please correct the errors below.')

    def wait_for_location_reload_or_error(self):
        """Wait until row 0's locations are reloaded or the page reports a script error; return the errors."""
        errors = []

        def settled():
            errors.extend(self.javascript_errors())
            return errors or '<no specific location>' in self.option_texts('id_storage-0-location')

        self.wait_until(settled)
        return errors

    def test_typed_new_location_is_kept_through_a_validation_error(self):
        """A new location typed before a validation error must still be chosen, and saved, once it is fixed.

        Otherwise someone correcting a typo elsewhere on the form would silently
        lose the shelf they had typed in.
        """
        self.submit_with_new_location_but_no_part_number('Drawer')

        assert self.wait_for_location_reload_or_error() == []
        # The room's other locations stay on offer alongside the new one.
        assert self.option_texts('id_storage-0-location') == ['<no specific location>', 'Shelf A', 'Shelf B', 'Drawer']
        assert self.value_of('id_storage-0-location') == '__new__Drawer'
        assert p_models.Part.objects.count() == 0

        self.type_into('id_part_number', 'GB-100')
        self.save_part()

        storage = p_models.Storage.objects.get(location='Drawer')
        assert storage.room == self.store_room
        psc = p_models.PartStorageCollection.objects.get()
        assert (psc.storage, psc.quantity) == (storage, 3)

    def test_typed_new_location_with_a_space_is_kept_through_a_validation_error(self):
        """A new location whose name has a space must survive a validation error like any other.

        Most real shelf names ("Top Drawer", "Cabinet 3") have spaces.
        """
        self.submit_with_new_location_but_no_part_number('Top Drawer')

        assert self.wait_for_location_reload_or_error() == []
        assert self.option_texts('id_storage-0-location') == [
            '<no specific location>', 'Shelf A', 'Shelf B', 'Top Drawer'
        ]
        assert self.value_of('id_storage-0-location') == '__new__Top Drawer'

    def test_two_storage_rows_are_both_saved_and_summed(self):
        """Two storage rows must each be saved, and the part's quantity must be their sum."""
        self.open_new_form()
        self.fill_required_fields()
        self.choose_room(0, 'Store Room (Main Campus)')
        self.select2_choose('id_storage-0-location', 'Shelf A')
        self.type_into('id_storage-0-quantity', '2')
        self.choose_room(1, 'Bunker (Main Campus)')
        self.select2_choose('id_storage-1-location', 'Bin 9')
        self.type_into('id_storage-1-quantity', '5')

        self.save_part()

        part = p_models.Part.objects.get()
        stored = {psc.storage: psc.quantity for psc in p_models.PartStorageCollection.objects.all()}
        assert stored == {self.shelf_a: 2, self.bin_9: 5}
        assert part.quantity_current == 7

    def test_changing_quantity_on_edit_updates_storage_and_total(self):
        """Changing the quantity in an existing storage row must update that row and the part's total."""
        part = self.create_part()
        p_models.PartStorageCollection.objects.create(part=part, storage=self.shelf_a, quantity=5)

        self.open_edit_form(part)
        # The server renders the row with a single unlabelled option; the page then
        # reloads the room's locations by ajax and must keep Shelf A chosen.
        self.wait_for_shelf_a_reloaded()
        self.type_into('id_storage-0-quantity', '1', clear=True)

        self.save_part()

        assert 'Part GB-100 - Gantry bearing updated' in self.success_message()
        psc = p_models.PartStorageCollection.objects.get()
        assert (psc.storage, psc.quantity) == (self.shelf_a, 1)
        part.refresh_from_db()
        assert part.quantity_current == 1

    def test_ticking_delete_on_a_storage_row_removes_it(self):
        """Ticking delete on a storage row must remove only that row and lower the part's total."""
        part = self.create_part()
        p_models.PartStorageCollection.objects.create(part=part, storage=self.shelf_a, quantity=5)
        p_models.PartStorageCollection.objects.create(part=part, storage=self.bin_9, quantity=2)

        self.open_edit_form(part)
        # Rows are ordered by quantity, largest first, so row 0 is Shelf A.
        self.wait_for_shelf_a_reloaded()
        self.click_css('#id_storage-0-DELETE')

        self.save_part()

        psc = p_models.PartStorageCollection.objects.get()
        assert (psc.storage, psc.quantity) == (self.bin_9, 2)
        part.refresh_from_db()
        assert part.quantity_current == 2


class TestPartSuppliers(PartsSeleniumTestCase):

    def test_supplier_and_its_part_number_are_saved(self):
        """A supplier chosen in the suppliers table must be saved with its own part number."""
        self.open_new_form()
        self.fill_required_fields()
        self.select2_choose('id_supplier-0-supplier', 'Beta Medical')
        self.type_into('id_supplier-0-part_number', 'BM-77')

        self.save_part()

        psc = p_models.PartSupplierCollection.objects.get()
        assert (psc.part, psc.supplier, psc.part_number) == (p_models.Part.objects.get(), self.beta, 'BM-77')

    def test_ticking_delete_on_a_supplier_removes_it(self):
        """Ticking delete on a supplier row must remove that supplier from the part, and only that one."""
        part = self.create_part()
        p_models.PartSupplierCollection.objects.create(part=part, supplier=self.acme, part_number='AC-1')
        kept = p_models.PartSupplierCollection.objects.create(part=part, supplier=self.beta, part_number='BM-2')

        self.open_edit_form(part)
        assert self.value_of('id_supplier-0-supplier') == str(self.acme.pk)
        self.click_css('#id_supplier-0-DELETE')

        self.save_part()

        assert list(p_models.PartSupplierCollection.objects.all()) == [kept]


class TestPartDetailsFields(PartsSeleniumTestCase):

    def test_cost_typed_into_the_money_mask_is_saved_exactly(self):
        """Typing 1234.5 into the masked cost box must save $1234.50, not a value mangled by the mask."""
        self.open_new_form()
        self.fill_required_fields()
        self.type_into('id_cost', '1234.5')
        # The mask has formatted the number as money, so the server really does
        # receive "$" and "," and has to strip them.
        self.wait.until(lambda d: self.value_of('id_cost').startswith('$1,234'))

        self.save_part()

        assert p_models.Part.objects.get().cost == Decimal('1234.50')

    def test_saving_an_existing_part_keeps_its_cost(self):
        """Saving a part without touching the cost must not change it as the mask reformats it."""
        part = self.create_part(cost=Decimal('1234.50'))

        self.open_edit_form(part)
        self.wait.until(lambda d: self.value_of('id_cost').startswith('$1,234'))
        self.save_part()

        part.refresh_from_db()
        assert part.cost == Decimal('1234.50')

    def test_category_is_chosen_from_the_select2_box(self):
        """The category picked in the category select2 must be saved on the part."""
        self.open_new_form()
        self.fill_required_fields()
        self.select2_choose('id_part_category', 'Couch Parts')

        self.save_part()

        assert p_models.Part.objects.get().part_category == self.couch_parts

    def test_add_another_saves_the_part_and_shows_a_blank_form(self):
        """"Add Part and enter another" must save the part and return an empty form for the next one."""
        self.open_new_form()
        self.fill_required_fields()
        self.click_css('input[type=submit][name=submit_add_another]')
        self.wait.until(lambda d: 'New part GB-100 - Gantry bearing added' in self.success_message())
        self.wait_for_visible('#id_storage-0-room + .select2')
        self.wait_for_ajax()

        assert self.driver.current_url.endswith(reverse('part_new'))
        assert self.value_of('id_name') == ''
        assert self.value_of('id_part_number') == ''
        assert p_models.Part.objects.get().name == 'Gantry bearing'


class TestPartAttachments(PartsSeleniumTestCase):

    def setUp(self):
        super().setUp()
        # Keep uploaded files out of the repository's media directory.
        self.media_root = self.use_temporary_media_root()

    def test_uploaded_attachment_is_saved_with_the_part(self):
        """A file chosen in the attachments box must be stored against the part."""
        path = os.path.join(self.media_root, 'bearing_drawing.txt')
        with open(path, 'w') as f:
            f.write('drawing of the bearing')

        self.open_new_form()
        self.fill_required_fields()
        # The real file input is hidden behind a styled "Browse" label; show it
        # so WebDriver can hand it a file, as the operating system dialog would.
        file_input = self.driver.find_element(By.ID, 'id_part_attachments')
        self.driver.execute_script("arguments[0].style.display = 'block';", file_input)
        file_input.send_keys(path)
        self.wait_for_text('#part-attachment-names', 'bearing_drawing.txt')

        self.save_part()

        attachment = Attachment.objects.get()
        assert attachment.part == p_models.Part.objects.get()
        assert attachment.label == 'bearing_drawing.txt'
        assert attachment.created_by == self.user
        with attachment.attachment.open('r') as f:
            assert f.read() == 'drawing of the bearing'

    def test_ticking_delete_on_edit_removes_the_attachment(self):
        """Ticking an attachment's delete box on edit must remove that attachment, and only that one."""
        part = self.create_part()
        doomed = Attachment.objects.create(
            attachment=SimpleUploadedFile('old.txt', b'old'), label='old.txt', part=part, created_by=self.user,
        )
        kept = Attachment.objects.create(
            attachment=SimpleUploadedFile('keep.txt', b'keep'), label='keep.txt', part=part, created_by=self.user,
        )

        self.open_edit_form(part)
        self.click_css('#attach-%d-DELETE' % doomed.pk)
        assert self.value_of('id_part_attachments_delete_ids') == str(doomed.pk)
        self.save_part()

        assert list(Attachment.objects.all()) == [kept]

    def test_attachments_of_other_records_are_never_deleted(self):
        """Only this record's own attachments can be deleted, whatever ids the browser sends.

        The delete ids travel in a hidden field. If this fails, an edited request can
        delete anyone's attachments, from any record.
        """
        part = self.create_part()
        other_part = self.create_part(part_number='OTHER-1', name='Other part')
        other = Attachment.objects.create(
            attachment=SimpleUploadedFile('other.txt', b'other'), label='other.txt', part=other_part,
            created_by=self.user,
        )

        self.open_edit_form(part)
        self.driver.execute_script(
            "document.getElementById('id_part_attachments_delete_ids').value = arguments[0];", str(other.pk)
        )
        self.save_part()

        assert list(Attachment.objects.all()) == [other]


class TestPartLists(PartsSeleniumTestCase):

    # listable names each table after the page's URL name.
    table = '#listable-table-parts_list tbody'

    def setUp(self):
        super().setUp()
        self.bearing = self.create_part(name='Gantry bearing', part_number='GB-100', quantity_min=3)
        p_models.PartStorageCollection.objects.create(part=self.bearing, storage=self.shelf_a, quantity=1)
        self.fuse = self.create_part(name='Couch fuse', part_number='CF-200', quantity_min=1)
        p_models.PartStorageCollection.objects.create(part=self.fuse, storage=self.bin_9, quantity=6)
        p_models.PartSupplierCollection.objects.create(part=self.fuse, supplier=self.beta, part_number='BM-9')

    def table_text(self):
        return self.driver.find_element(By.CSS_SELECTOR, self.table).text

    def open_list(self, url_name='parts_list'):
        self.table = '#listable-table-%s tbody' % url_name
        self.login()
        self.open(reverse(url_name))
        self.wait_for_element(self.table)
        self.wait_for_ajax()

    def header_cell(self, title):
        """The filter cell under the column titled `title`."""
        headers = self.driver.find_elements(By.CSS_SELECTOR, '#listable-table-parts_list thead tr:first-child th')
        titles = [h.text.strip() for h in headers]
        idx = titles.index(title) + 1
        return '#listable-table-parts_list thead tr:nth-child(2) th:nth-child(%d)' % idx

    def test_filtering_by_name_narrows_the_parts_list(self):
        """Typing in the Name filter must list only the parts whose name matches."""
        self.open_list()
        self.wait_for_text(self.table, 'GB-100')
        self.wait_for_text(self.table, 'CF-200')

        self.click_css(self.header_cell('Name') + ' input')
        self.driver.switch_to.active_element.send_keys('fuse')
        self.wait.until(lambda d: 'GB-100' not in self.table_text())
        self.wait_for_ajax()

        assert 'CF-200' in self.table_text()

    def test_low_inventory_list_shows_only_parts_below_their_minimum(self):
        """The low inventory list must show parts with fewer in storage than their minimum, and no others."""
        self.open_list('low_inventory_parts_list')
        self.wait_for_text(self.table, 'GB-100')

        assert 'CF-200' not in self.table_text()
        assert 'Low Inventory Parts' in self.page_text()

    def test_locations_column_shows_where_each_part_is_stored(self):
        """The Locations column must read "site/room/location" with a count, not raw HTML markup.

        This is the column people scan to find a part on the shelf.
        """
        self.open_list()
        self.wait_for_text(self.table, 'Main Campus/Store Room/Shelf A')

        text = self.table_text()
        assert '<div' not in text
        assert '<span' not in text
        badges = self.driver.find_elements(By.CSS_SELECTOR, self.table + ' span.badge')
        assert sorted(b.text for b in badges) == ['1', '6']

    def test_part_details_page_shows_storage_and_suppliers(self):
        """The details page must show where a part is stored, how many, and who supplies it."""
        self.login()
        self.open(reverse('part_details', kwargs={'pk': self.fuse.pk}))
        self.wait_for_text('.content', 'Part %d Details' % self.fuse.pk)

        text = self.page_text()
        assert 'Couch fuse' in text
        assert 'Bin 9' in text
        assert 'BM-9' in text
        self.click_by_link_text('Beta Medical')
        self.wait_for_text('.content', 'Supplier Details: Beta Medical')

    def test_supplier_details_lists_only_that_suppliers_parts(self):
        """A supplier's page must list the parts that supplier provides, and no others."""
        self.login()
        self.open(reverse('suppliers_list'))
        self.wait_for_text('#listable-table-suppliers_list tbody', 'Beta Medical')
        assert 'Acme Linac Supply' in self.driver.find_element(By.CSS_SELECTOR, '#listable-table-suppliers_list').text

        self.open(reverse('supplier_details', kwargs={'pk': self.beta.pk}))
        table = '#listable-table-supplier_details tbody'
        self.wait_for_text(table, 'CF-200')
        self.wait_for_ajax()
        assert 'GB-100' not in self.driver.find_element(By.CSS_SELECTOR, table).text

