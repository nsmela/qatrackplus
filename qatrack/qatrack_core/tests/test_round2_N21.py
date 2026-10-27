"""The project-wide admin change form (templates/admin/change_form.html) follows Django 4.2's.

It keeps QATrack's own breadcrumbs ("QC", "Websites") and the wider two-column
picker, but takes the parts of Django's template that other code relies on:
the app/model body classes, the translatable "Add <name>" breadcrumb, object
tools from ``{% change_form_object_tools %}`` (so per-model overrides apply),
and the hidden popup / to_field inputs that related-object popups need.
"""
import copy
import os
import re
import tempfile

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from qatrack.accounts.tests.utils import create_user
from qatrack.parts import models as p_models
from qatrack.qa.tests import utils as qa_utils


def body_classes(html):
    match = re.search(r'<body[^>]*class="([^"]*)"', html)
    assert match, 'no class attribute on <body>'
    return match.group(1).split()


def breadcrumbs(html):
    match = re.search(r'<div class="breadcrumbs">(.*?)</div>', html, re.S)
    assert match, 'no breadcrumbs'
    return ' '.join(re.sub(r'<[^>]+>', ' ', match.group(1)).split())


class TestProjectChangeForm(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)

    def get(self, url):
        resp = self.client.get(url)
        assert resp.status_code == 200
        return resp.content.decode()

    def test_change_page_body_classes(self):
        cat = qa_utils.create_category()
        html = self.get(reverse('admin:qa_category_change', args=[cat.pk]))
        classes = body_classes(html)
        for cls in ('app-qa', 'model-category', 'change-form'):
            assert cls in classes
        # the old "<app>-<model>" class clashed with qa.css's .qa-category rules
        assert 'qa-category' not in classes

    def test_add_page_body_classes_and_breadcrumb(self):
        html = self.get(reverse('admin:auth_group_add'))
        classes = body_classes(html)
        for cls in ('app-auth', 'model-group', 'change-form'):
            assert cls in classes
        assert breadcrumbs(html).endswith('Add group')

    def test_add_breadcrumb_keeps_qc_label(self):
        html = self.get(reverse('admin:qa_category_add'))
        crumbs = breadcrumbs(html)
        assert 'QC' in crumbs
        assert crumbs.lower().endswith('add category')

    def test_change_page_has_history_link(self):
        group = Group.objects.create(name='Physics')
        html = self.get(reverse('admin:auth_group_change', args=[group.pk]))
        history = reverse('admin:auth_group_history', args=[group.pk])
        assert re.search(r'<ul class="object-tools">.*?href="%s"[^>]*class="historylink"' % re.escape(history), html, re.S)

    def test_change_page_has_view_on_site_link(self):
        supplier = p_models.Supplier.objects.create(name='Acme')
        html = self.get(reverse('admin:parts_supplier_change', args=[supplier.pk]))
        ct = ContentType.objects.get_for_model(p_models.Supplier)
        url = reverse('admin:view_on_site', args=[ct.pk, supplier.pk])
        assert 'href="%s" class="viewsitelink"' % url in html

    def test_add_page_has_no_object_tools(self):
        html = self.get(reverse('admin:auth_group_add'))
        assert 'class="object-tools"' not in html

    def test_popup_keeps_popup_and_to_field_inputs(self):
        html = self.get(reverse('admin:auth_group_add') + '?_popup=1&_to_field=id')
        assert '<input type="hidden" name="_popup" value="1">' in html
        assert '<input type="hidden" name="_to_field" value="id">' in html
        # popups don't show breadcrumbs or object tools
        assert 'class="breadcrumbs"' not in html

    def test_popup_change_page_has_no_object_tools(self):
        group = Group.objects.create(name='Physics')
        html = self.get(reverse('admin:auth_group_change', args=[group.pk]) + '?_popup=1')
        assert 'class="object-tools"' not in html

    def test_no_to_field_input_without_to_field(self):
        html = self.get(reverse('admin:auth_group_add'))
        assert 'name="_to_field"' not in html

    def test_popup_add_saves_and_closes(self):
        """The hidden inputs carry through a save, so the popup response closes the window"""
        resp = self.client.post(
            reverse('admin:auth_group_add') + '?_popup=1&_to_field=id',
            {'name': 'From popup', '_popup': '1', '_to_field': 'id'},
        )
        assert resp.status_code == 200
        assert 'admin/js/popup_response.js' in resp.content.decode()
        assert Group.objects.filter(name='From popup').exists()

    def test_per_model_object_tools_override_applies(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'admin', 'auth', 'group')
        os.makedirs(path)
        with open(os.path.join(path, 'change_form_object_tools.html'), 'w') as f:
            f.write('<li><a href="#" class="n21-custom-tool">Custom</a></li>')
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]['DIRS'] = [tmp] + list(templates[0].get('DIRS', []))
        group = Group.objects.create(name='Physics')
        with override_settings(TEMPLATES=templates):
            html = self.get(reverse('admin:auth_group_change', args=[group.pk]))
        assert 'n21-custom-tool' in html
        assert 'class="historylink"' not in html


class TestTestListChangeFormStillWorks(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.force_login(self.user)

    def test_change_page(self):
        tl = qa_utils.create_test_list('N21 list')
        resp = self.client.get(reverse('admin:qa_testlist_change', args=[tl.pk]))
        assert resp.status_code == 200
        html = resp.content.decode()
        classes = body_classes(html)
        for cls in ('app-qa', 'model-testlist', 'change-form'):
            assert cls in classes
        assert 'id="testlist_form"' in html
        assert 'id="tl-dialogs-outside-form"' in html
        # the builder puts its own actions in the title row instead of object tools
        assert 'class="object-tools"' not in html

    def test_add_page(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        assert resp.status_code == 200
        assert 'id="testlist_form"' in resp.content.decode()
