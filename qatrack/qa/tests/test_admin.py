import json
import re
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import constants, get_messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.forms import HiddenInput, inlineformset_factory, modelform_factory
from django.http import QueryDict
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.urls import reverse

from qatrack.accounts.tests.utils import create_group, create_user
from qatrack.qa import admin as qa_admin
from qatrack.qa import models as qa_models
from qatrack.qa.tests import utils as qa_utils
from qatrack.qa.utils import get_bool_tols, get_internal_user
from qatrack.service_log.tests import utils as sl_utils


class TestSetReferencesAndTolerancesForm(TransactionTestCase):

    def setUp(self):

        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.url = reverse('admin:qa_copy_refs_and_tols')

        self.tl_1 = qa_utils.create_test_list()
        self.tl_2 = qa_utils.create_test_list()
        self.tl_3 = qa_utils.create_test_list()
        self.tl_fc_1 = qa_utils.create_test_list(name='for_cycle_1')
        self.tl_fc_2 = qa_utils.create_test_list(name='for_cycle_2')
        self.tl_fc_3 = qa_utils.create_test_list(name='for_cycle_3')
        self.tlc_1 = qa_utils.create_cycle(test_lists=[self.tl_fc_1, self.tl_fc_2, self.tl_fc_3])
        self.tlc_2 = qa_utils.create_cycle(test_lists=[self.tl_fc_1, self.tl_fc_2])

        self.u_1 = qa_utils.create_unit()
        self.u_2 = qa_utils.create_unit()

        test = qa_utils.create_test()

        self.tlm_1 = qa_utils.create_test_list_membership(test_list=self.tl_1, test=test)
        self.tlm_2 = qa_utils.create_test_list_membership(test_list=self.tl_2, test=test)

        self.utc_1 = qa_utils.create_unit_test_collection(unit=self.u_1, test_collection=self.tl_1)
        self.utc_2 = qa_utils.create_unit_test_collection(unit=self.u_2, test_collection=self.tl_2)

        self.uti_1, _ = qa_models.UnitTestInfo.objects.get_or_create(unit=self.u_1, test=test)
        self.uti_1.reference = qa_utils.create_reference()
        self.uti_1.tolerance = qa_utils.create_tolerance()
        self.uti_1.save()

        self.uti_2, _ = qa_models.UnitTestInfo.objects.get_or_create(unit=self.u_2, test=test)

    def test_source_testlist_choices(self):

        response = self.client.get(self.url)

        choices = response.context['form'].fields['source_testlist'].choices

        for tl in qa_models.TestList.objects.all():
            self.assertTrue((tl.id, tl.name) in choices)
        for tlc in qa_models.TestListCycle.objects.all():
            self.assertTrue((tlc.id, tlc.name) in choices)

    def test_save(self):

        uti_source = self.uti_1
        uti_dest = self.uti_2

        # Stage 1: Submit initial form data
        data = {
            'content_type': 'testlist',
            'source_testlist': self.tl_1.id,
            'source_unit': self.u_1.id,
            'dest_unit': self.u_2.id,
            'stage': '1'
        }

        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # Stage 2: Confirm the operation
        data.update({'confirm': 'Confirm', 'stage': '2'})

        response = self.client.post(self.url, data=data)

        # Check that the operation was successful (should redirect)
        self.assertIn(response.status_code, [200, 302])

        # Refresh from database and verify the copy worked
        uti_dest = qa_models.UnitTestInfo.objects.get(id=uti_dest.id)

        self.assertEqual(uti_source.reference, uti_dest.reference)
        self.assertEqual(uti_source.tolerance, uti_dest.tolerance)


class TestTestlistjson(TestCase):

    def setUp(self):

        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.u = qa_utils.create_unit()

        tl1 = qa_utils.create_test_list()
        tl2 = qa_utils.create_test_list()
        tl3 = qa_utils.create_test_list()

        qa_utils.create_unit_test_collection(unit=self.u, test_collection=tl1)
        qa_utils.create_unit_test_collection(unit=self.u, test_collection=tl2)
        qa_utils.create_unit_test_collection(unit=self.u, test_collection=tl3)

        tlc1 = qa_utils.create_cycle(test_lists=[tl1, tl2, tl3])

        qa_utils.create_unit_test_collection(unit=self.u, test_collection=tlc1)

        self.url_tl = reverse(
            'qa_copy_refs_and_tols_testlist_json',
            kwargs={
                'source_unit': self.u.id,
                'content_type': qa_models.TestList.__name__.lower()
            }
        )
        self.url_tlc = reverse(
            'qa_copy_refs_and_tols_testlist_json',
            kwargs={
                'source_unit': self.u.id,
                'content_type': qa_models.TestListCycle.__name__.lower()
            }
        )
        self.url_bad = reverse(
            'qa_copy_refs_and_tols_testlist_json',
            kwargs={
                'source_unit': self.u.id,
                'content_type': qa_models.Test.__name__.lower()
            }
        )

        self.tl_ct = ContentType.objects.get(model='testlist')
        self.tlc_ct = ContentType.objects.get(model='testlistcycle')

    def test_test_list(self):

        utcs = qa_models.UnitTestCollection.objects.filter(
            unit=self.u, content_type=self.tl_ct
        ).values_list(
            'object_id', flat=True
        )
        tl_to_find = list(qa_models.TestList.objects.filter(pk__in=utcs).values_list('pk', 'name'))

        response = self.client.get(self.url_tl)
        self.assertJSONEqual(json.dumps(tl_to_find), response.json())

    def test_test_list_cycle(self):

        utcs = qa_models.UnitTestCollection.objects.filter(
            unit=self.u, content_type=self.tlc_ct
        ).values_list(
            'object_id', flat=True
        )
        tlc_to_find = list(qa_models.TestListCycle.objects.filter(pk__in=utcs).values_list('pk', 'name'))

        response = self.client.get(self.url_tlc)
        self.assertJSONEqual(json.dumps(tlc_to_find), response.json())

    def test_bad_ctype(self):

        with self.assertRaises(ValidationError):
            self.client.get(self.url_bad)


class TestToleranceAdmin(TestCase):

    def setUp(self):

        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.t = qa_utils.create_tolerance()

        self.url_add = reverse(
            'admin:%s_%s_add' % (qa_models.Tolerance._meta.app_label, qa_models.Tolerance._meta.model_name)
        )
        self.url_list = reverse(
            'admin:%s_%s_changelist' % (qa_models.Tolerance._meta.app_label, qa_models.Tolerance._meta.model_name)
        )

        self.data = {
            'mc_tol_choices': '',
            'act_low': '0',
            'tol_low': '1',
            'tol_high': '2',
            'act_high': '3',
            'type': 'absolute',
            'mc_pass_choices': ''
        }

    def test_add(self):

        self.client.post(self.url_add, data=self.data)
        t = qa_models.Tolerance.objects.order_by('id').last()

        self.assertEqual(self.user, t.created_by)

    def test_unique(self):
        self.client.post(self.url_add, data=self.data)
        form = modelform_factory(qa_models.Tolerance, form=qa_admin.ToleranceForm, fields='__all__')(data=self.data)
        self.assertFalse(form.is_valid())

    def test_list(self):
        qa_utils.create_tolerance(act_high=3)
        qa_utils.create_tolerance(act_high=4)
        self.client.get(self.url_list)


class TestTestInstanceAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        qa_utils.create_test_instance()
        self.url = reverse(
            'admin:%s_%s_changelist' %
            (qa_models.TestInstance._meta.app_label, qa_models.TestInstance._meta.model_name)
        )

    def test_list_page(self):
        self.client.get(self.url)


class TestTestListInstanceAdmin(TestCase):

    def setUp(self):

        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.tli = qa_utils.create_test_list_instance()
        self.usa = sl_utils.create_unit_service_area(unit=self.tli.unit_test_collection.unit)
        self.se = sl_utils.create_service_event(
            unit_service_area=self.usa,
            add_test_list_instance_initiated_by=self.tli,
        )
        sl_utils.create_return_to_service_qa(add_test_list_instance=self.tli)

        self.url_list = reverse(
            'admin:%s_%s_changelist' %
            (qa_models.TestListInstance._meta.app_label, qa_models.TestListInstance._meta.model_name)
        )
        self.url_delete = reverse(
            'admin:%s_%s_delete' %
            (qa_models.TestListInstance._meta.app_label, qa_models.TestListInstance._meta.model_name),
            args=[self.tli.id]
        )

    def test_list_page(self):
        self.client.get(self.url_list)

    def test_delete_form(self):

        response = self.client.get(self.url_delete)
        for a in response.context:
            for b in a:
                if 'se_rtsqa_qs' in b:
                    self.assertTrue(len(b['se_rtsqa_qs']) > 0)
                    self.assertTrue(len(b['se_ib_qs']) > 0)


class TestUnitTestCollectionAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.u_1 = qa_utils.create_unit()
        self.u_2 = qa_utils.create_unit()
        self.f_1 = qa_utils.create_frequency()
        self.f_2 = qa_utils.create_frequency()
        self.tl_1 = qa_utils.create_test_list()
        self.tl_2 = qa_utils.create_test_list()
        self.t_1 = qa_utils.create_test()
        self.t_2 = qa_utils.create_test()
        qa_utils.create_test_list_membership(test_list=self.tl_1, test=self.t_1)
        qa_utils.create_test_list_membership(test_list=self.tl_1, test=self.t_2)

        self.g_1 = create_group()
        self.g_2 = create_group()

        self.tl_ct = ContentType.objects.get(model='testlist')
        self.tlc_ct = ContentType.objects.get(model='testlistcycle')
        self.utc_1 = qa_utils.create_unit_test_collection(
            unit=self.u_1, test_collection=self.tl_1, assigned_to=self.g_1, frequency=self.f_1
        )
        self.utc_2 = qa_utils.create_unit_test_collection(
            unit=self.u_2, active=False, assigned_to=self.g_2, frequency=self.f_2
        )

        self.url_list = reverse(
            'admin:%s_%s_changelist' %
            (qa_models.UnitTestCollection._meta.app_label, qa_models.UnitTestCollection._meta.model_name)
        )
        self.url_add = reverse(
            'admin:%s_%s_add' %
            (qa_models.UnitTestCollection._meta.app_label, qa_models.UnitTestCollection._meta.model_name)
        )
        self.url_change = reverse(
            'admin:%s_%s_change' %
            (qa_models.UnitTestCollection._meta.app_label, qa_models.UnitTestCollection._meta.model_name),
            args=[self.utc_1.id]
        )

    def test_list_page(self):
        self.client.get(self.url_list)

    def test_add_form(self):

        data = {
            'frequency': self.f_1.id,
            'visible_to': [self.g_1.id],
            'unit': qa_utils.create_unit().id,
            'auto_schedule': 'on',
            'active': 'on',
            'assigned_to': self.g_1.id,
            'content_type': self.tl_ct.id,
            'object_id': self.tl_1.id
        }

        utc_before = qa_models.UnitTestCollection.objects.count()
        self.client.post(self.url_add, data=data)
        utc_after = qa_models.UnitTestCollection.objects.count()
        self.assertEqual(utc_before + 1, utc_after)

    def test_readonly_values(self):

        data = {
            'frequency': self.utc_1.frequency.id,
            'visible_to': [vt.id for vt in self.utc_1.visible_to.all()],
            'unit': self.u_2.id,
            'auto_schedule': 'on',
            'active': 'on',
            'assigned_to': self.utc_1.assigned_to.id,
            'content_type': self.tlc_ct.id,
            'object_id': self.tl_2.id
        }

        form = modelform_factory(
            qa_models.UnitTestCollection, form=qa_admin.UnitTestCollectionForm, fields='__all__'
        )(data=data, instance=self.utc_1)
        self.assertFalse(form.is_valid())
        self.assertTrue('object_id' in form.errors)
        self.assertTrue('content_type' in form.errors)
        self.assertTrue('unit' in form.errors)

    def test_active_filter(self):
        fylter = qa_admin.ActiveFilter(
            None, {'activefilter': 1}, qa_models.UnitTestCollection, qa_admin.UnitTestCollectionAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.UnitTestCollection.objects.all())
        filtered_2 = qa_models.UnitTestCollection.objects.filter(active=True)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_assigned_to_filter(self):
        fylter = qa_admin.AssignedToFilter(
            None, {'assignedtoname': self.g_1.id}, qa_models.UnitTestCollection, qa_admin.UnitTestCollectionAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.UnitTestCollection.objects.all())
        filtered_2 = qa_models.UnitTestCollection.objects.filter(assigned_to=self.g_1)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_frequency_filter(self):
        fylter = qa_admin.FrequencyFilter(
            None, {'freqfilter': self.f_1.id}, qa_models.UnitTestCollection, qa_admin.UnitTestCollectionAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.UnitTestCollection.objects.all())
        filtered_2 = qa_models.UnitTestCollection.objects.filter(frequency=self.f_1)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_unit_filter(self):
        fylter = qa_admin.UnitFilter(
            None, {'unitfilter': self.u_1.id}, qa_models.UnitTestCollection, qa_admin.UnitTestCollectionAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.UnitTestCollection.objects.all())
        filtered_2 = qa_models.UnitTestCollection.objects.filter(unit=self.u_1)
        self.assertListEqual(list(filtered_2), list(filtered_1))


class TestTestAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.c_1 = qa_utils.create_category()
        self.t_1 = qa_utils.create_test()
        self.tl_1 = qa_utils.create_test_list()
        qa_utils.create_test_list_membership(test=self.t_1, test_list=self.tl_1)
        self.tli_1 = qa_utils.create_test_list_instance(test_list=self.tl_1)
        self.ti_1 = qa_utils.create_test_instance(
            test_list_instance=self.tli_1, unit_test_info=qa_utils.create_unit_test_info(test=self.t_1), value=1
        )

        self.url_add = reverse('admin:%s_%s_add' % (qa_models.Test._meta.app_label, qa_models.Test._meta.model_name))
        self.url_list = reverse(
            'admin:%s_%s_changelist' % (qa_models.Test._meta.app_label, qa_models.Test._meta.model_name)
        )
        self.url_change = reverse(
            'admin:%s_%s_change' % (qa_models.Test._meta.app_label, qa_models.Test._meta.model_name),
            args=[self.t_1.id]
        )

        self.data = {
            'procedure': '',
            'category': self.c_1.id,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 0,
            'attachment_set-TOTAL_FORMS': 0,
            'chart_visibility': 'on',
            'constant_value': '',
            'description': '',
            'slug': '',
            'type': 'simple',
            'calculation_procedure': '',
            'choices': '',
            'name': ''
        }

    def test_list(self):
        self.client.get(self.url_list)

    def test_pyplot_warning(self):

        data = self.data
        data['calculation_procedure'] = 'import pyplot\r\nresult = 1'
        data['slug'] = 'test_pyplot'
        data['type'] = 'composite'
        data['name'] = 'Test pyplot'

        response = self.client.post(self.url_add, data=data)
        messages = get_messages(response.wsgi_request)
        self.assertTrue(constants.WARNING in [m.level for m in messages])

    def test_http_warning(self):

        data = self.data
        data['procedure'] = 'not http'
        data['slug'] = 'test_http'
        data['name'] = 'Test http'

        response = self.client.post(self.url_add, data=data)
        messages = get_messages(response.wsgi_request)
        self.assertTrue(constants.WARNING in [m.level for m in messages])

    def test_testlistmembership_filter(self):
        qs = qa_models.Test.objects.annotate(tlcount=Count("testlistmembership"))
        fylter = qa_admin.TestListMembershipFilter(
            None, {'tlmembership': qa_admin.TestListMembershipFilter.HASMEMBERSHIPS}, qa_models.Test, qa_admin.TestAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.Test.objects.all())
        filtered_2 = qs.filter(tlcount__gt=0)
        self.assertListEqual(list(filtered_2), list(filtered_1))

        fylter = qa_admin.TestListMembershipFilter(
            None, {'tlmembership': qa_admin.TestListMembershipFilter.NOMEMBERSHIPS}, qa_models.Test, qa_admin.TestAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.Test.objects.all())
        filtered_2 = qs.filter(tlcount=0)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_change_type(self):

        data = self.data
        data['name'] = self.t_1.name
        data['slug'] = self.t_1.slug
        data['type'] = qa_models.BOOLEAN

        form = modelform_factory(qa_models.Test, form=qa_admin.TestForm, fields='__all__')(data=data, instance=self.t_1)

        self.assertFalse(form.is_valid())
        self.assertTrue('type' in form.errors)


class TestTestListAdmin(TestCase):

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        self.t_1 = qa_utils.create_test()
        self.t_2 = qa_utils.create_test()
        self.u_1 = qa_utils.create_unit()
        self.f_1 = qa_utils.create_frequency()
        self.tl_1 = qa_utils.create_test_list()
        self.utc_1 = qa_utils.create_unit_test_collection(test_collection=self.tl_1, unit=self.u_1)
        self.utc_2 = qa_utils.create_unit_test_collection(test_collection=self.tl_1, frequency=self.f_1)

        qa_utils.create_test_list_membership(test_list=self.tl_1, test=self.t_2, order=0)

        self.sublist = qa_utils.create_sublist(parent_test_list=self.tl_1)

        self.url_add = reverse(
            'admin:%s_%s_add' % (qa_models.TestList._meta.app_label, qa_models.TestList._meta.model_name)
        )
        self.url_list = reverse(
            'admin:%s_%s_changelist' % (qa_models.TestList._meta.app_label, qa_models.TestList._meta.model_name)
        )
        self.url_change = reverse(
            'admin:%s_%s_change' % (qa_models.TestList._meta.app_label, qa_models.TestList._meta.model_name),
            args=[self.tl_1.id]
        )

        self.data = {
            'name': 'testing_sublists',
            'warning_message': 'erroR',
            'javascript': 'alert("subs!")',
            'slug': 'testing_sublists',
            'description': 'description',
            'attachment_set-MAX_NUM_FORMS': 10,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-TOTAL_FORMS': 1,
            'attachment_set-0-testlist': '',
            'attachment_set-0-id': '',
            'attachment_set-0-comment': 'Testing',
            'attachment_set-0-attachment': '',
            'children-INITIAL_FORMS': 0,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 10,
            'children-TOTAL_FORMS': 1,
            'children-0-order': 1,
            'children-0-child': self.tl_1.id,
            'children-0-parent': '',
            'children-0-id': '',
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-INITIAL_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 10,
            'testlistmembership_set-TOTAL_FORMS': 1,
            'testlistmembership_set-0-test_list': '',
            'testlistmembership_set-0-id': '',
            'testlistmembership_set-0-order': 0,
            'testlistmembership_set-0-test': self.t_1.id
        }

    def test_list(self):
        self.client.get(self.url_list)

    def test_frequency_test_list_filter(self):
        fylter = qa_admin.FrequencyTestListFilter(
            None, {'assignedbyfreq': self.f_1.id}, qa_models.TestList, qa_admin.TestListAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.TestList.objects.all())
        freq_tl_ids = qa_models.get_utc_tl_ids(frequencies=[self.f_1])
        filtered_2 = qa_models.TestList.objects.filter(id__in=freq_tl_ids)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_unit_test_list_filter(self):
        fylter = qa_admin.UnitTestListFilter(
            None, {'assignedtounit': self.u_1.id}, qa_models.TestList, qa_admin.TestListAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.TestList.objects.all())
        unit_tl_ids = qa_models.get_utc_tl_ids(units=[self.u_1])
        filtered_2 = qa_models.TestList.objects.filter(id__in=unit_tl_ids)
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_active_test_list_filter(self):
        active_tl_ids = qa_models.get_utc_tl_ids(active=True)
        active_sub_tl_ids = list(
            qa_models.TestList.objects.filter(id__in=active_tl_ids,
                                              children__isnull=False).values_list('children__child__id',
                                                                                  flat=True).distinct()
        )

        fylter = qa_admin.ActiveTestListFilter(
            None, {'activeutcs': qa_admin.ActiveTestListFilter.HASACTIVEUTCS}, qa_models.TestList,
            qa_admin.TestListAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.TestList.objects.all())
        filtered_2 = qa_models.TestList.objects.filter(Q(id__in=active_tl_ids) | Q(id__in=active_sub_tl_ids))
        self.assertListEqual(list(filtered_2), list(filtered_1))

        fylter = qa_admin.ActiveTestListFilter(
            None, {'activeutcs': qa_admin.ActiveTestListFilter.NOACTIVEUTCS}, qa_models.TestList, qa_admin.TestListAdmin
        )
        filtered_1 = fylter.queryset(None, qa_models.TestList.objects.all())
        filtered_2 = qa_models.TestList.objects.exclude(Q(id__in=active_tl_ids) | Q(id__in=active_sub_tl_ids))
        self.assertListEqual(list(filtered_2), list(filtered_1))

    def test_change_page(self):
        self.client.get(self.url_change)

    def test_form_valid(self):

        data = self.data
        form = modelform_factory(qa_models.TestList, form=qa_admin.TestListAdminForm, exclude=['tests'])(data=data)
        self.assertTrue(form.is_valid())

    @override_settings(MAX_TESTS_PER_TESTLIST=0)
    def test_too_many_tests(self):
        data = self.data
        form = modelform_factory(qa_models.TestList, form=qa_admin.TestListAdminForm, exclude=['tests'])(data=data)
        assert not form.is_valid()
        assert any("A test list can have at most 0." in err for err in form.errors['__all__'])

    def test_duplicate_macros(self):
        data = self.data
        data['testlistmembership_set-TOTAL_FORMS'] = 2
        data['testlistmembership_set-1-test_list'] = ''
        data['testlistmembership_set-1-id'] = ''
        data['testlistmembership_set-1-order'] = 3
        data['testlistmembership_set-1-test'] = self.t_2.id

        form = modelform_factory(qa_models.TestList, form=qa_admin.TestListAdminForm, exclude=['tests'])(data=data)
        self.assertFalse(form.is_valid())

    def test_clean_slug(self):
        data = self.data
        data['slug'] = self.tl_1.slug
        form = modelform_factory(qa_models.TestList, form=qa_admin.TestListAdminForm, exclude=['tests'])(data=data)
        self.assertFalse(form.is_valid())

    def test_sublist_formset_valid(self):

        data = self.data
        data['children-0-child'] = self.sublist.child.id

        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.Sublist,
            formset=qa_admin.SublistInlineFormSet,
            fk_name='parent',
            fields='__all__'
        )(data=data, queryset=qa_models.Sublist.objects.all(), instance=None)
        self.assertTrue(formset.is_valid())

    def test_sublist_formset_own_child(self):
        data = self.data
        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.Sublist,
            formset=qa_admin.SublistInlineFormSet,
            fk_name='parent',
            fields='__all__'
        )(data=data, queryset=qa_models.Sublist.objects.all(), instance=self.tl_1)
        self.assertFalse(formset.is_valid())

    def test_sublist_nesting_parent(self):
        """Shouldn't be able to add a sublist that has a sublist of its own"""
        tl = qa_utils.create_test_list(name="sub")
        qa_utils.create_sublist(parent_test_list=self.sublist.child, child_test_list=tl)
        data = self.data
        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.Sublist,
            formset=qa_admin.SublistInlineFormSet,
            fk_name='parent',
            fields='__all__'
        )(data=data, queryset=qa_models.Sublist.objects.all(), instance=None)
        assert not formset.is_valid()
        assert "Test Lists can not be nested more than 1 level" in formset.non_form_errors()[0]

    def test_sublist_nesting_child(self):
        """Shouldn't be able to add a sublist when you are a sublist"""
        tl = qa_utils.create_test_list(name="sub")
        data = self.data
        data['children-0-child'] = tl.id
        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.Sublist,
            formset=qa_admin.SublistInlineFormSet,
            fk_name='parent',
            fields='__all__'
        )(data=data, queryset=qa_models.Sublist.objects.all(), instance=self.sublist.child)
        assert not formset.is_valid()
        assert "This Test List is a Sublist" in formset.non_form_errors()[0]

    def test_sublist_duplicate(self):
        data = self.data

        data['children-TOTAL_FORMS'] = 2
        data['children-1-order'] = 2
        data['children-1-child'] = self.tl_1.id
        data['children-1-parent'] = ''
        data['children-1-id'] = ''

        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.Sublist,
            formset=qa_admin.SublistInlineFormSet,
            fk_name='parent',
            fields='__all__'
        )(data=data, queryset=qa_models.Sublist.objects.all(), instance=None)
        self.assertFalse(formset.is_valid())

    def test_test_valid(self):
        data = self.data
        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.TestListMembership,
            formset=qa_admin.TestListMembershipInlineFormSet,
            fields='__all__'
        )(data=data, queryset=qa_models.TestListMembership.objects.all(), instance=None)
        self.assertTrue(formset.is_valid())

    def test_test_duplicate(self):
        data = self.data

        data['testlistmembership_set-TOTAL_FORMS'] = 2
        data['testlistmembership_set-1-test_list'] = '',
        data['testlistmembership_set-1-id'] = '',
        data['testlistmembership_set-1-order'] = 2,
        data['testlistmembership_set-1-test'] = self.t_1.id

        formset = inlineformset_factory(
            qa_models.TestList,
            qa_models.TestListMembership,
            formset=qa_admin.TestListMembershipInlineFormSet,
            fields='__all__'
        )(data=data, queryset=qa_models.TestListMembership.objects.all(), instance=None)
        self.assertFalse(formset.is_valid())


class TestUnitTestInfoAdmin(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

        get_internal_user()
        get_bool_tols()  # hack to work around tolerances being deleted somewhere (in another test?)

        self.site = AdminSite()
        self.u_1 = qa_utils.create_unit()
        self.t_1 = qa_utils.create_test(test_type=qa_models.SIMPLE)
        self.t_2 = qa_utils.create_test(test_type=qa_models.BOOLEAN)
        self.t_3 = qa_utils.create_test(test_type=qa_models.MULTIPLE_CHOICE)
        self.t_4 = qa_utils.create_test(test_type=qa_models.SIMPLE)
        self.t_5 = qa_utils.create_test(test_type=qa_models.BOOLEAN)
        self.t_6 = qa_utils.create_test(test_type=qa_models.MULTIPLE_CHOICE)
        self.t_360 = qa_utils.create_test(test_type=qa_models.WRAPAROUND, wrap_low=0, wrap_high=360)
        self.tol_1 = qa_utils.create_tolerance()
        self.tol_2 = qa_utils.create_tolerance(act_low=-10, act_high=10)

        self.tol_3 = qa_models.Tolerance.objects.filter(type=qa_models.BOOLEAN).first()
        self.tol_4 = qa_utils.create_tolerance(
            tol_type=qa_models.MULTIPLE_CHOICE, mc_pass_choices='2,4,6', mc_tol_choices='1,3,5'
        )
        self.tol_5 = qa_utils.create_tolerance(tol_type=qa_models.PERCENT)
        self.r_1 = qa_utils.create_reference()
        self.r_2 = qa_utils.create_reference(value=1.61803)
        self.r_3 = qa_utils.create_reference(ref_type=qa_models.BOOLEAN)

        self.uti_1 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_1, ref=self.r_1, tol=self.tol_1)
        self.uti_2 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_2, ref=self.r_1, tol=self.tol_1)
        self.uti_3 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_3)
        self.uti_4 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_4)
        self.uti_5 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_5, tol=self.tol_3)
        self.uti_6 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_6, tol=self.tol_4)
        self.uti_360 = qa_utils.create_unit_test_info(unit=self.u_1, test=self.t_360, ref=self.r_1, tol=self.tol_1)

        self.url_list = reverse(
            'admin:%s_%s_changelist' %
            (qa_models.UnitTestInfo._meta.app_label, qa_models.UnitTestInfo._meta.model_name)
        )
        self.url_change = reverse(
            'admin:%s_%s_change' % (qa_models.UnitTestInfo._meta.app_label, qa_models.UnitTestInfo._meta.model_name),
            args=[self.uti_1.id]
        )

        self.data = {
            'unit': self.u_1.id,
            'test': self.t_1.id,
            'test_type': self.t_1.type,
            'reference_value': self.r_2.value,
            'tolerance': self.tol_1.id,
            'id': self.uti_1.id
        }

    def test_list(self):
        self.client.get(self.url_list)

    def test_form_valid(self):
        data = self.data
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(instance=self.uti_1, data=data)
        self.assertTrue(form.is_valid())
        self.assertListEqual(
            list(form.fields['tolerance'].queryset),
            list(qa_models.Tolerance.objects.exclude(type=qa_models.MULTIPLE_CHOICE).exclude(type=qa_models.BOOLEAN))
        )

    def test_boolean(self):

        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_2
        )

        self.assertListEqual(form.fields['reference_value'].widget.choices, [("", "---"), (0, "No"), (1, "Yes")])
        self.assertListEqual(
            list(form.fields['tolerance'].queryset), list(qa_models.Tolerance.objects.filter(type=qa_models.BOOLEAN))
        )

    def test_multi(self):
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_3
        )

        self.assertIsInstance(form.fields['reference_value'].widget, HiddenInput)
        self.assertListEqual(
            list(form.fields['tolerance'].queryset),
            list(qa_models.Tolerance.objects.filter(type=qa_models.MULTIPLE_CHOICE))
        )

    def test_submit(self):

        data = self.data
        request = self.factory.get(self.url_change)
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)

        form = admin.get_form(request)(instance=self.uti_1, data=data)
        self.assertTrue(form.is_valid())
        admin.save_model(request, admin.save_form(request, form, True), form, True)
        self.assertEqual(self.uti_1.reference.value, self.r_2.value)

        data['reference_value'] = ''
        data['tolerance'] = ''
        form = admin.get_form(request)(instance=self.uti_1, data=data)
        self.assertTrue(form.is_valid())
        admin.save_model(request, admin.save_form(request, form, True), form, True)
        self.assertEqual(self.uti_1.reference, None)

        data['reference_value'] = '3.14159'
        form = admin.get_form(request)(instance=self.uti_1, data=data)
        self.assertTrue(form.is_valid())
        admin.save_model(request, admin.save_form(request, form, True), form, True)
        self.assertEqual(self.uti_1.reference.value, '3.14159')

    def test_submit_360(self):

        data = {
            'unit': self.u_1.id,
            'test': self.t_360.id,
            'test_type': self.t_360.type,
            'reference_value': -1,
            'tolerance': self.tol_1.id,
            'id': self.uti_360.id
        }
        request = self.factory.get(self.url_change)
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)

        form = admin.get_form(request)(instance=self.uti_360, data=data)
        assert not form.is_valid()

        data['reference_value'] = 0
        form = admin.get_form(request)(instance=self.uti_360, data=data)
        assert form.is_valid()

    def test_save_multiple_simple(self):
        # request = self.factory.get(self.url_change)
        request = self.client.post(self.url_change).wsgi_request
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)
        data = {
            'tolerance': self.tol_2.id,
            'reference': self.r_2.value,
            'post': 'yes',
            'contenttype': '',
            'action': 'set_multiple_references_and_tolerances',
            '_selected_action': [self.uti_1.id, self.uti_4.id],
            'apply': 'Set tolerances and references'
        }
        request.POST = QueryDict('', mutable=True)
        request.POST.update(data)
        admin.set_multiple_references_and_tolerances(
            request, qa_models.UnitTestInfo.objects.filter(id__in=[self.uti_1.id, self.uti_4.id])
        )

        self.uti_1.refresh_from_db()
        self.uti_4.refresh_from_db()
        self.assertListEqual([self.uti_1.reference.value, self.uti_4.reference.value], [self.r_2.value, self.r_2.value])

    def test_save_multiple_boolean(self):
        request = self.client.post(self.url_change).wsgi_request
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)
        data = {
            'tolerance': self.tol_3.id,
            'reference': self.r_3.value,
            'post': 'yes',
            'contenttype': '',
            'action': 'set_multiple_references_and_tolerances',
            '_selected_action': [self.uti_2.id, self.uti_5.id],
            'apply': 'Set tolerances and references'
        }
        request.POST = QueryDict('', mutable=True)
        request.POST.update(data)
        admin.set_multiple_references_and_tolerances(
            request, qa_models.UnitTestInfo.objects.filter(id__in=[self.uti_2.id, self.uti_5.id])
        )

        self.uti_2.refresh_from_db()
        self.uti_5.refresh_from_db()
        self.assertListEqual([self.uti_2.reference.value, self.uti_5.reference.value], [self.r_3.value, self.r_3.value])

    def test_save_multiple_multiple(self):
        request = self.client.post(self.url_change).wsgi_request
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)
        data = {
            'tolerance': self.tol_4.id,
            'reference': '',
            'post': 'yes',
            'contenttype': '',
            'action': 'set_multiple_references_and_tolerances',
            '_selected_action': [self.uti_3.id, self.uti_6.id],
            'apply': 'Set tolerances and references'
        }
        request.POST = QueryDict('', mutable=True)
        request.POST.update(data)
        admin.set_multiple_references_and_tolerances(
            request, qa_models.UnitTestInfo.objects.filter(id__in=[self.uti_3.id, self.uti_6.id])
        )

        self.uti_3.refresh_from_db()
        self.uti_6.refresh_from_db()
        self.assertListEqual([self.uti_3.reference, self.uti_6.reference], [None, None])

    def test_save_multiple_new_ref(self):
        request = self.client.post(self.url_change).wsgi_request
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)
        data = {
            'tolerance': self.tol_2.id,
            'reference': '2.71828',
            'post': 'yes',
            'contenttype': '',
            'action': 'set_multiple_references_and_tolerances',
            '_selected_action': [self.uti_1.id, self.uti_4.id],
            'apply': 'Set tolerances and references'
        }
        request.POST = QueryDict('', mutable=True)
        request.POST.update(data)
        admin.set_multiple_references_and_tolerances(
            request, qa_models.UnitTestInfo.objects.filter(id__in=[self.uti_1.id, self.uti_4.id])
        )

        self.uti_1.refresh_from_db()
        self.uti_4.refresh_from_db()
        self.assertListEqual([self.uti_1.reference.value, self.uti_4.reference.value], [2.71828, 2.71828])

    def test_save_multiple_defferent_types(self):
        request = self.client.post(self.url_change).wsgi_request
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)
        data = {
            'tolerance': self.tol_1.id,
            'reference': '1',
            'post': 'yes',
            'contenttype': '',
            'action': 'set_multiple_references_and_tolerances',
            '_selected_action': [self.uti_1.id, self.uti_2.id],  # Simple and Boolean test types
            'apply': 'Set tolerances and references'
        }
        request.POST = QueryDict('', mutable=True)
        request.POST.update(data)
        admin.set_multiple_references_and_tolerances(
            request, qa_models.UnitTestInfo.objects.filter(id__in=[self.uti_1.id, self.uti_2.id])
        )
        messages = get_messages(request)
        self.assertTrue(constants.ERROR in [m.level for m in messages])

    def test_bad_multiple(self):
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_3
        )
        data = form.initial
        data['tolerance'] = self.tol_1.id
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(instance=self.uti_3, data=data)
        self.assertFalse(form.is_valid())

    def test_bad_percent_tol(self):
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_4
        )
        data = form.initial
        data['tolerance'] = self.tol_5.id
        data['reference_value'] = 0
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(instance=self.uti_4, data=data)
        self.assertFalse(form.is_valid())

    def test_bad_percent_tol_blank_ref(self):
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_4
        )
        data = form.initial
        data['tolerance'] = self.tol_5.id
        data['reference_value'] = ''
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(instance=self.uti_4, data=data)
        self.assertFalse(form.is_valid())

    def test_bad_percent_tol_non_numerical_ref(self):
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(
            instance=self.uti_4
        )
        data = form.initial
        data['tolerance'] = self.tol_5.id
        data['reference_value'] = 'asdf'
        form = modelform_factory(
            qa_models.UnitTestInfo, form=qa_admin.UnitTestInfoForm, fields='__all__'
        )(instance=self.uti_4, data=data)
        self.assertFalse(form.is_valid())

    def test_history_records_old_values(self):
        """Test that UnitTestInfoChange records the correct old values when reference/tolerance are changed"""
        request = self.factory.get(self.url_change)
        request.user = self.user
        admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, self.site)

        # Initial state: uti_1 has r_1 reference and tol_1 tolerance
        initial_ref = self.uti_1.reference
        initial_tol = self.uti_1.tolerance

        # First change: update reference and tolerance
        data = {
            'unit': self.u_1.id,
            'test': self.t_1.id,
            'test_type': self.t_1.type,
            'reference_value': self.r_2.value,
            'tolerance': self.tol_2.id,
            'comment': 'First change',
            'id': self.uti_1.id
        }

        form = admin.get_form(request)(instance=self.uti_1, data=data)
        self.assertTrue(form.is_valid())
        admin.save_model(request, admin.save_form(request, form, True), form, True)

        # Check first history record
        changes = qa_models.UnitTestInfoChange.objects.filter(unit_test_info=self.uti_1)
        self.assertEqual(changes.count(), 1)
        first_change = changes.first()
        self.assertEqual(first_change.reference, initial_ref)
        self.assertEqual(first_change.tolerance, initial_tol)
        self.assertTrue(first_change.reference_changed)
        self.assertTrue(first_change.tolerance_changed)
        self.assertEqual(first_change.comment, 'First change')
        self.assertEqual(first_change.changed_by, self.user)

        # Second change: update reference again
        data2 = {
            'unit': self.u_1.id,
            'test': self.t_1.id,
            'test_type': self.t_1.type,
            'reference_value': '999',
            'tolerance': self.tol_1.id,
            'comment': 'Second change',
            'id': self.uti_1.id
        }

        form2 = admin.get_form(request)(instance=self.uti_1, data=data2)
        self.assertTrue(form2.is_valid())
        admin.save_model(request, admin.save_form(request, form2, True), form2, True)

        # Check that we now have two history records with correct old values
        changes = qa_models.UnitTestInfoChange.objects.filter(unit_test_info=self.uti_1).order_by('changed')
        self.assertEqual(changes.count(), 2)

        # First change should have initial values as old values
        self.assertEqual(changes[0].reference, initial_ref)
        self.assertEqual(changes[0].tolerance, initial_tol)

        # Second change should have the values from after the first change as old values
        self.assertEqual(changes[1].reference.value, self.r_2.value)
        self.assertEqual(changes[1].tolerance, self.tol_2)


class TestTestListAdminBuilderUI(TestCase):
    """Smoke tests for the Test List Builder pass-1 admin UI (Details card +
    restyled changelist columns)."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.changelist_url = reverse('admin:qa_testlist_changelist')

    def _admin(self):
        return qa_admin.TestListAdmin(qa_models.TestList, self.site)

    def _request(self, url=None):
        request = self.factory.get(url or self.changelist_url)
        request.user = self.user
        return request

    def test_changelist_renders(self):
        qa_utils.create_test_list()
        resp = self.client.get(self.changelist_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Configured Test Lists')

    def test_change_form_add_buttons_live_in_tests_card_header(self):
        tl = qa_utils.create_test_list()
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,)))
        self.assertContains(resp, 'id="tl-header-add-sublist-btn"')
        self.assertContains(resp, 'id="tl-header-add-test-btn"')
        self.assertNotContains(resp, 'tl-bottom-actions')
        self.assertNotContains(resp, 'tl-add-sublist-btn')
        self.assertNotContains(resp, 'id="tl-add-test-btn"')
        self.assertContains(resp, 'Use Add Test or Add Sublist above to get started.')

    def test_change_form_renders_details_card(self):
        tl = qa_utils.create_test_list()
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,)))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'tl-details-card')
        # fields are rendered server-side in the card (no JS relocation)
        self.assertContains(resp, 'id="id_name"')
        self.assertContains(resp, 'id="id_javascript"')
        # description preview is wired to the htmx endpoint
        self.assertContains(resp, reverse('admin:qa_testlist_desc_preview'))
        self.assertContains(resp, 'hx-post')

    def test_add_form_renders_details_card(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'tl-details-card')

    def test_test_count_annotation(self):
        tl = qa_utils.create_test_list()
        t1 = qa_utils.create_test(name='count_t1')
        t2 = qa_utils.create_test(name='count_t2')
        qa_utils.create_test_list_membership(test_list=tl, test=t1, order=0)
        qa_utils.create_test_list_membership(test_list=tl, test=t2, order=1)

        obj = self._admin().get_queryset(self._request()).get(pk=tl.pk)
        self.assertEqual(obj.test_count, 2)
        self.assertIn('2', self._admin().col_tests(obj))

    def test_frequency_and_units_columns(self):
        tl = qa_utils.create_test_list()
        unit = qa_utils.create_unit()
        freq = qa_utils.create_frequency(name='Monthly', slug='monthly')
        qa_utils.create_unit_test_collection(unit=unit, frequency=freq, test_collection=tl)

        ma = self._admin()
        obj = ma.get_queryset(self._request()).get(pk=tl.pk)
        self.assertIn('Monthly', ma.col_frequency(obj))
        self.assertIn('fa-cube', ma.col_units(obj))

    def test_adhoc_frequency_label(self):
        tl = qa_utils.create_test_list()
        unit = qa_utils.create_unit()
        qa_utils.create_unit_test_collection(unit=unit, test_collection=tl, null_frequency=True)

        ma = self._admin()
        obj = ma.get_queryset(self._request()).get(pk=tl.pk)
        self.assertIn('Ad Hoc', ma.col_frequency(obj))

    def test_changelist_no_per_row_queries_for_utcs(self):
        """Frequency/Units columns must not issue per-row queries."""
        for i in range(3):
            tl = qa_utils.create_test_list(name='n_query_tl_%d' % i)
            unit = qa_utils.create_unit()
            freq = qa_utils.create_frequency(name='Freq %d' % i, slug='freq_%d' % i)
            qa_utils.create_unit_test_collection(unit=unit, frequency=freq, test_collection=tl)

        ma = self._admin()
        qs = ma.get_queryset(self._request())
        with self.assertNumQueries(2):
            # 1 query for the test lists, 1 prefetch for their UnitTestCollections
            objs = list(qs)
            for obj in objs:
                ma.col_frequency(obj)
                ma.col_units(obj)

    def test_description_preview_endpoint(self):
        url = reverse('admin:qa_testlist_desc_preview')
        resp = self.client.post(url, {'description': '<b>Do not treat</b>'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode().strip(), '<b>Do not treat</b>')

    def test_description_preview_empty(self):
        url = reverse('admin:qa_testlist_desc_preview')
        resp = self.client.post(url, {'description': '   '})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Nothing to preview', resp.content.decode())

    def test_description_preview_requires_staff(self):
        self.client.logout()
        url = reverse('admin:qa_testlist_desc_preview')
        resp = self.client.post(url, {'description': 'x'})
        # admin_view redirects anonymous users to the admin login
        self.assertIn(resp.status_code, (302, 403))


class TestTestListBuilderQuickFixes(TestCase):
    """Permissions, URLs and layout of the Test List Builder edit page."""

    def setUp(self):
        self.superuser = create_user(is_superuser=True, uname='super', pwd='pwd')
        self.limited = create_user(is_superuser=False, uname='limited', pwd='pwd')
        # "test list editor": full test list permissions (including the inlines'
        # models), but no permissions on Test itself
        cts = ContentType.objects.get_for_models(
            qa_models.TestList, qa_models.TestListMembership, qa_models.Sublist,
        ).values()
        self.limited.user_permissions.add(
            *Permission.objects.filter(content_type__in=cts)
        )
        self.test = qa_utils.create_test(name='quickfix_test')
        self.test.description = 'Original description'
        self.test.save()
        self.tl = qa_utils.create_test_list(name='quickfix_tl')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.test, order=0)
        self.desc_url = reverse('admin:qa_testlist_test_desc_modal')
        self.dup_url = reverse('admin:qa_testlist_duplicate_test')
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _login(self, uname):
        self.client.login(username=uname, password='pwd')

    def _grant(self, codename):
        test_ct = ContentType.objects.get_for_model(qa_models.Test)
        self.limited.user_permissions.add(Permission.objects.get(content_type=test_ct, codename=codename))

    # --- description dialog ---

    def test_desc_modal_get_forbidden_without_change_test(self):
        self._login('limited')
        resp = self.client.get(self.desc_url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Nothing was changed', resp.content.decode())

    def test_desc_modal_post_forbidden_without_change_test(self):
        self._login('limited')
        resp = self.client.post(self.desc_url + '?test_id=%d' % self.test.pk, {'description': 'Hacked'})
        self.assertEqual(resp.status_code, 403)
        self.test.refresh_from_db()
        self.assertEqual(self.test.description, 'Original description')

    def test_desc_modal_allowed_with_change_test(self):
        self._grant('change_test')
        self._login('limited')
        resp = self.client.get(self.desc_url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(self.desc_url + '?test_id=%d' % self.test.pk, {'description': 'Updated'})
        self.assertEqual(resp.status_code, 200)
        self.test.refresh_from_db()
        self.assertEqual(self.test.description, 'Updated')

    def test_desc_modal_wording(self):
        self._login('super')
        resp = self.client.get(self.desc_url, {'test_id': self.test.pk})
        self.assertContains(resp, 'Description (HTML allowed)</label>')
        self.assertNotContains(resp, 'Test Description (HTML allowed)')
        self.assertContains(resp, 'Saving updates this test straight away')

    # --- duplicate dialog ---

    def test_duplicate_get_forbidden_without_add_test(self):
        self._login('limited')
        resp = self.client.get(self.dup_url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('No test was created', resp.content.decode())

    def test_duplicate_post_forbidden_without_add_test(self):
        self._login('limited')
        before = qa_models.Test.objects.count()
        resp = self.client.post(self.dup_url, {'source_test_id': self.test.pk, 'new_name': 'quickfix copy'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(qa_models.Test.objects.count(), before)
        self.assertFalse(qa_models.Test.objects.filter(name='quickfix copy').exists())

    def test_duplicate_allowed_with_add_test(self):
        self._grant('add_test')
        self._login('limited')
        resp = self.client.get(self.dup_url, {'test_id': self.test.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'created as soon as you click')
        resp = self.client.post(self.dup_url, {'source_test_id': self.test.pk, 'new_name': 'quickfix copy'})
        self.assertEqual(resp.status_code, 200)
        copy = qa_models.Test.objects.get(name='quickfix copy')
        self.assertEqual(copy.created_by, self.limited)

    # --- buttons hidden without permission ---

    def test_change_form_hides_test_actions_without_perms(self):
        self._login('limited')
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'class="tl-action-icon tl-duplicate-test-btn"')
        self.assertNotContains(resp, 'hx-get="%s' % self.desc_url)
        self.assertContains(resp, 'class="tl-test-desc tl-test-desc-readonly"')

    def test_change_form_shows_test_actions_with_perms(self):
        self._login('super')
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'class="tl-action-icon tl-duplicate-test-btn"')
        self.assertContains(resp, 'hx-get="%s' % self.desc_url)
        self.assertNotContains(resp, 'class="tl-test-desc tl-test-desc-readonly"')

    def test_add_test_row_respects_perms(self):
        url = reverse('admin:qa_testlist_add_test_row')
        self._login('limited')
        resp = self.client.get(url, {'test_id': self.test.pk, 'index': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'tl-duplicate-test-btn')
        self.assertNotContains(resp, self.desc_url)
        self.client.logout()
        self._login('super')
        resp = self.client.get(url, {'test_id': self.test.pk, 'index': 1})
        self.assertContains(resp, 'tl-duplicate-test-btn')
        self.assertContains(resp, self.desc_url)

    # --- URLs rendered by Django, not hard-coded in JS ---

    def test_change_form_renders_builder_urls_as_data_attributes(self):
        self._login('super')
        resp = self.client.get(self.change_url)
        for attr, name in [
            ('data-search-tests-url', 'qa_testlist_search_tests'),
            ('data-search-sublists-url', 'qa_testlist_search_sublists'),
            ('data-add-test-row-url', 'qa_testlist_add_test_row'),
            ('data-add-sublist-card-url', 'qa_testlist_add_sublist_card'),
            ('data-duplicate-test-url', 'qa_testlist_duplicate_test'),
        ]:
            self.assertContains(resp, '%s="%s"' % (attr, reverse('admin:%s' % name)))

    def test_assets_have_no_hard_coded_admin_urls(self):
        from django.template import loader
        source = loader.get_template('admin/qa/testlist/testlist_assets.html').template.source
        self.assertNotIn('/admin/qa/testlist/search', source)
        self.assertNotIn('/admin/qa/testlist/', source)

    # --- layout ---

    def test_parents_card_renders_after_tests_card(self):
        parent = qa_utils.create_test_list(name='quickfix_parent')
        qa_utils.create_sublist(parent_test_list=parent, child_test_list=self.tl)
        self._login('super')
        content = self.client.get(self.change_url).content.decode()
        tests_pos = content.index('id="tl-tests-card"')
        parents_pos = content.index('id="tl-parents-card"')
        attach_pos = content.index('id="tl-attachments-card"')
        self.assertLess(tests_pos, parents_pos)
        self.assertLess(parents_pos, attach_pos)
        self.assertIn('Changes you save here apply to each of them.', content)
        self.assertNotIn('immediately take effect across all parents', content)

    def test_standalone_parents_card_still_renders(self):
        self._login('super')
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'tl-parents-empty-card')
        self.assertContains(resp, "This test list isn't used as a sublist in any other test list.")

    def test_details_card_has_no_id_label(self):
        self._login('super')
        resp = self.client.get(self.change_url)
        self.assertNotContains(resp, 'tl-card-id')


class TestTestListBuilderTypeValue(TestCase):
    """The base list builder shows a "Type Value" column (constant value,
    choices, wraparound range or calculation) instead of per-machine
    references and tolerances."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

    def _meta(self, test_type, **kwargs):
        test = qa_utils.create_test(test_type=test_type)
        for attr, val in kwargs.items():
            setattr(test, attr, val)
        test.save()
        return qa_admin.get_test_metadata(test)

    def _assert_no_old_keys(self, meta):
        self.assertNotIn('reference_display', meta)
        self.assertNotIn('tolerance_display', meta)
        self.assertNotIn('Pass =', json.dumps(meta))

    def test_constant_without_formatting(self):
        meta = self._meta(qa_models.CONSTANT, constant_value=22.0)
        self.assertEqual(meta['type_value'], '22.0')
        self.assertEqual(meta['type_value_title'], '')
        self.assertFalse(meta['type_value_mono'])
        self._assert_no_old_keys(meta)

    def test_constant_with_formatting(self):
        meta = self._meta(qa_models.CONSTANT, constant_value=3.14159, formatting='%.2f')
        self.assertEqual(meta['type_value'], '3.14')

    def test_multiple_choice(self):
        meta = self._meta(qa_models.MULTIPLE_CHOICE, choices='Pass,Fail, Not Done')
        self.assertEqual(meta['type_value'], 'Pass, Fail, Not Done')
        self.assertFalse(meta['type_value_mono'])

    def test_wraparound(self):
        meta = self._meta(qa_models.WRAPAROUND, wrap_low=0.0, wrap_high=360.0)
        self.assertEqual(meta['type_value'], '0 to 360')
        meta = self._meta(qa_models.WRAPAROUND, wrap_low=-0.5, wrap_high=359.5)
        self.assertEqual(meta['type_value'], '-0.5 to 359.5')

    def test_composite_long_multiline_calc_is_truncated(self):
        first = 'result = ' + ' + '.join('t%d' % i for i in range(30))
        calc = '\n\n%s\nresult = result / 2\n' % first
        meta = self._meta(qa_models.COMPOSITE, calculation_procedure=calc)
        self.assertTrue(meta['type_value_mono'])
        self.assertTrue(meta['type_value'].endswith('…'))
        self.assertLessEqual(len(meta['type_value']), qa_admin.TYPE_VALUE_MAX_CHARS)
        self.assertTrue(first.startswith(meta['type_value'][:-1]))
        self.assertEqual(meta['type_value_title'], calc.strip())

    def test_composite_short_single_line_has_no_title(self):
        meta = self._meta(qa_models.COMPOSITE, calculation_procedure='result = t0')
        self.assertEqual(meta['type_value'], 'result = t0')
        self.assertEqual(meta['type_value_title'], '')
        self.assertTrue(meta['type_value_mono'])

    def test_composite_multiline_short_first_line_has_title(self):
        meta = self._meta(qa_models.STRING_COMPOSITE, calculation_procedure='x = 1\nresult = "a"')
        self.assertEqual(meta['type_value'], 'x = 1')
        self.assertEqual(meta['type_value_title'], 'x = 1\nresult = "a"')

    def test_upload_with_and_without_calc(self):
        meta = self._meta(qa_models.UPLOAD, calculation_procedure='result = len(FILE.read())')
        self.assertEqual(meta['type_value'], 'result = len(FILE.read())')
        self.assertTrue(meta['type_value_mono'])
        meta = self._meta(qa_models.UPLOAD, calculation_procedure='')
        self.assertEqual(meta['type_value'], '')
        self.assertFalse(meta['type_value_mono'])

    def test_upload_placeholder_calc_counts_as_empty(self):
        test = qa_utils.create_test(test_type=qa_models.UPLOAD)
        test.calculation_procedure = '%s = None' % test.slug
        test.save()
        self.assertEqual(qa_admin.get_test_metadata(test)['type_value'], '')

    def test_simple_types_are_empty(self):
        for test_type in (qa_models.SIMPLE, qa_models.BOOLEAN, qa_models.STRING, qa_models.DATE, qa_models.DATETIME):
            meta = self._meta(test_type)
            self.assertEqual(meta['type_value'], '', test_type)
            self.assertFalse(meta['type_value_mono'])
            self._assert_no_old_keys(meta)

    def test_boolean_flag_when_does_not_leak(self):
        for flag in (True, False, None):
            meta = self._meta(qa_models.BOOLEAN, flag_when=flag)
            self.assertEqual(meta['type_value'], '')
            self._assert_no_old_keys(meta)

    def test_change_form_shows_type_value_column(self):
        tl = qa_utils.create_test_list()
        const = qa_utils.create_test(name='tv_const', test_type=qa_models.CONSTANT, constant_value=22.0)
        num = qa_utils.create_test(name='tv_num')
        qa_utils.create_test_list_membership(test_list=tl, test=const, order=0)
        qa_utils.create_test_list_membership(test_list=tl, test=num, order=1)
        child = qa_utils.create_test_list(name='tv_child')
        mc = qa_utils.create_test(name='tv_mc', test_type=qa_models.MULTIPLE_CHOICE, choices='a,b')
        qa_utils.create_test_list_membership(test_list=child, test=mc, order=0)
        qa_utils.create_sublist(parent_test_list=tl, child_test_list=child, order=2)

        resp = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,)))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # main table header and sublist inner table header
        self.assertEqual(content.count('<th class="tl-th-type-value tl-col-type-value">Type Value</th>'), 2)
        self.assertContains(resp, 'Type Value')
        self.assertNotContains(resp, 'REFERENCE')
        self.assertNotContains(resp, 'TOLERANCE')
        # Reference / Tolerance columns exist only for machine mode, and are
        # empty and hidden (CSS) on the base list
        self.assertEqual(content.count('<th class="tl-th-ref tl-col-ref">Reference</th>'), 2)
        self.assertEqual(content.count('<th class="tl-th-tol tl-col-tol">Tolerance</th>'), 2)
        self.assertEqual(content.count('<td class="tl-cell-ref tl-col-ref"></td>'), 3)
        self.assertNotContains(resp, 'Pass = ')
        self.assertContains(resp, 'data-type-value="22.0"')
        self.assertContains(resp, '<span class="tl-type-value">22.0</span>', html=True)
        self.assertContains(resp, '<span class="tl-type-value">a, b</span>', html=True)
        self.assertContains(resp, '<span class="tl-type-value-none">None</span>', html=True)
        # the sublist row spans the whole main table (drag, test, category, type,
        # type value, machine-mode reference and tolerance, actions)
        thead = content.split('id="tl-tests-table"')[1].split('</thead>')[0]
        main_cols = len(re.findall(r'<th\b', thead))
        self.assertEqual(main_cols, 8)
        self.assertContains(resp, 'colspan="%d" class="tl-sublist-cell"' % main_cols)


class TestTestListAdminBreadcrumbs(TestCase):
    """The Test List pages show the standard admin breadcrumbs bar as their header."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.index_url = reverse('admin:index')
        self.app_url = reverse('admin:app_list', kwargs={'app_label': 'qa'})
        self.changelist_url = reverse('admin:qa_testlist_changelist')

    def _breadcrumbs(self, resp):
        """Return (plain text, list of hrefs) of the single breadcrumbs bar."""
        content = resp.content.decode()
        divs = re.findall(r'<div class="breadcrumbs">(.*?)</div>', content, re.S)
        self.assertEqual(len(divs), 1)
        html = divs[0]
        text = ' '.join(re.sub(r'<[^>]+>', ' ', html).replace('&rsaquo;', '›').split())
        hrefs = re.findall(r'href="([^"]+)"', html)
        return text, hrefs

    def _assert_common(self, resp):
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'tl-breadcrumbs')

    def test_changelist_breadcrumbs(self):
        qa_utils.create_test_list()
        resp = self.client.get(self.changelist_url)
        self._assert_common(resp)
        text, hrefs = self._breadcrumbs(resp)
        self.assertEqual(text, 'Home › QC › Test Lists')
        self.assertEqual(hrefs, [self.index_url, self.app_url])
        self.assertNotContains(resp, 'Select test list to change')
        self.assertContains(resp, '<title>Test Lists | QATrack+ Admin Site</title>', html=True)

    def test_change_form_breadcrumbs(self):
        tl = qa_utils.create_test_list()
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,)))
        self._assert_common(resp)
        text, hrefs = self._breadcrumbs(resp)
        self.assertEqual(text, 'Home › QC › Test Lists › Edit › %d' % tl.pk)
        self.assertContains(resp, '<title>%s | Edit Test List | QATrack+ Admin Site</title>' % tl.name, html=True)
        self.assertEqual(hrefs, [self.index_url, self.app_url, self.changelist_url])

    def test_add_form_breadcrumbs(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        self._assert_common(resp)
        text, hrefs = self._breadcrumbs(resp)
        self.assertEqual(text, 'Home › QC › Test Lists › Add')
        self.assertContains(resp, '<title>Add Test List | QATrack+ Admin Site</title>', html=True)
        self.assertEqual(hrefs, [self.index_url, self.app_url, self.changelist_url])


class TestAdminPinnedHeader(TestCase):
    """base_site.html wraps the admin header and breadcrumbs in one sticky .qa-admin-top box."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')

    def _top_html(self, resp):
        """Return the markup between the pinned wrapper's start and the page body (div.main)."""
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertEqual(content.count('id="qa-admin-top"'), 1)
        start = content.index('<div class="qa-admin-top" id="qa-admin-top">')
        end = content.index('<div class="main" id="main">')
        self.assertLess(start, end)
        return content, content[start:end]

    def test_index_has_wrapper_and_header(self):
        content, top = self._top_html(self.client.get(reverse('admin:index')))
        self.assertIn('id="header"', top)
        self.assertIn('QATrack+ administration', top)
        # the dashboard has no breadcrumb trail
        self.assertNotIn('class="breadcrumbs"', content)
        self.assertIn('.qa-admin-top {', content)
        self.assertIn('--qa-admin-top-h', content)

    def test_testlist_change_breadcrumbs_inside_wrapper(self):
        tl = qa_utils.create_test_list()
        content, top = self._top_html(self.client.get(reverse('admin:qa_testlist_change', args=(tl.pk,))))
        self.assertEqual(content.count('class="breadcrumbs"'), 1)
        self.assertIn('<nav aria-label="Breadcrumbs">', top)
        self.assertIn('class="breadcrumbs"', top)
        self.assertIn('Edit', top)
        # the title row is pinned below the wrapper
        self.assertIn('class="tl-header-bar"', content)
        self.assertGreater(content.index('class="tl-header-bar"'), content.index('<div class="main" id="main">'))

    def test_ordinary_changelist_breadcrumbs_inside_wrapper(self):
        content, top = self._top_html(self.client.get(reverse('admin:qa_test_changelist')))
        self.assertEqual(content.count('class="breadcrumbs"'), 1)
        self.assertIn('class="breadcrumbs"', top)

    def test_popup_has_no_wrapper(self):
        resp = self.client.get(reverse('admin:qa_frequency_add') + '?_popup=1')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="qa-admin-top"')
        self.assertNotContains(resp, 'class="breadcrumbs"')


class TestTestListBuilderSublistOutline(TestCase):
    """The builder's "Outline on Perform QC page" checkbox for Sublist.outline."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.parent = qa_utils.create_test_list(name='Parent List')
        self.child = qa_utils.create_test_list(name='Child List')
        qa_utils.create_test_list_membership(test_list=self.child, test=qa_utils.create_test(name='child test'))
        self.sublist = qa_utils.create_sublist(parent_test_list=self.parent, child_test_list=self.child)
        self.url = reverse('admin:qa_testlist_change', args=(self.parent.pk,))

    def _outline_input(self, content):
        inputs = re.findall(r'<input[^>]*name="children-0-outline"[^>]*>', content)
        self.assertEqual(len(inputs), 1)
        return inputs[0]

    def test_change_form_renders_visible_outline_checkbox(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        tag = self._outline_input(resp.content.decode())
        self.assertIn('type="checkbox"', tag)
        self.assertNotIn('display:none', tag)
        self.assertNotIn('checked', tag)
        self.assertContains(resp, 'Outline on Perform QC page')
        self.assertNotContains(resp, 'tl-sublist-card tl-sublist-outlined')

    def test_change_form_outline_checkbox_checked(self):
        self.sublist.outline = True
        self.sublist.save()
        resp = self.client.get(self.url)
        tag = self._outline_input(resp.content.decode())
        self.assertIn('checked', tag)
        self.assertContains(resp, 'tl-sublist-card tl-sublist-outlined')

    def _post_data(self, outline):
        data = {
            'name': self.parent.name,
            'slug': 'parent-list',
            'description': '',
            'warning_message': '',
            'javascript': '',
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-TOTAL_FORMS': 0,
            'testlistmembership_set-INITIAL_FORMS': 0,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'children-TOTAL_FORMS': 1,
            'children-INITIAL_FORMS': 1,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'children-0-id': self.sublist.pk,
            'children-0-parent': self.parent.pk,
            'children-0-child': self.child.pk,
            'children-0-order': 0,
        }
        if outline:
            data['children-0-outline'] = 'on'
        return data

    def test_post_outline_on_and_off(self):
        resp = self.client.post(self.url, data=self._post_data(outline=True))
        self.assertEqual(resp.status_code, 302)
        self.sublist.refresh_from_db()
        self.assertTrue(self.sublist.outline)

        resp = self.client.post(self.url, data=self._post_data(outline=False))
        self.assertEqual(resp.status_code, 302)
        self.sublist.refresh_from_db()
        self.assertFalse(self.sublist.outline)

    def test_add_sublist_card_has_unchecked_outline_checkbox(self):
        url = reverse('admin:qa_testlist_add_sublist_card')
        resp = self.client.get(url, {'child_id': self.child.pk, 'index': 0, 'parent_id': self.parent.pk})
        self.assertEqual(resp.status_code, 200)
        tag = self._outline_input(resp.content.decode())
        self.assertIn('type="checkbox"', tag)
        self.assertNotIn('display:none', tag)
        self.assertNotIn('checked', tag)
        self.assertNotContains(resp, 'tl-sublist-card tl-sublist-outlined')


def _limited_testlist_user(can_add):
    """A staff (non-superuser) user who can view/change test lists, and add them only if `can_add`."""
    user = create_user(is_superuser=False, uname='limited', pwd='pwd')
    codenames = [
        'view_testlist', 'change_testlist',
        'view_testlistmembership', 'add_testlistmembership', 'change_testlistmembership',
        'delete_testlistmembership',
        'view_sublist', 'add_sublist', 'change_sublist', 'delete_sublist',
    ]
    if can_add:
        codenames.append('add_testlist')
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='qa', codename__in=codenames))
    return user


class TestTestListSaveButtons(TestCase):
    """The change form's one save button group in the title row."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl = qa_utils.create_test_list(name='Daily QC')
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def test_edit_page_buttons(self):
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        history_url = reverse('admin:qa_testlist_history', args=(self.tl.pk,))
        delete_url = reverse('admin:qa_testlist_delete', args=(self.tl.pk,))
        self.assertContains(resp, 'href="%s"' % history_url)
        self.assertContains(resp, 'fa-history')
        self.assertContains(resp, 'href="%s"' % delete_url)
        self.assertContains(resp, 'id="tl-delete-btn"')
        self.assertContains(resp, 'href="%s"' % reverse('admin:qa_testlist_changelist'))
        self.assertContains(resp, 'id="tl-saveas-open-btn"')
        self.assertContains(resp, 'Save As…')
        self.assertContains(resp, 'id="tl-saveas-modal"')
        self.assertContains(resp, 'data-slug-available-url="%s"' % reverse('admin:qa_testlist_slug_available'))
        self.assertContains(resp, 'name="_continue"', count=1)
        self.assertContains(resp, 'name="_save"', count=1)
        self.assertNotContains(resp, 'name="_saveasnew"')
        self.assertNotContains(resp, 'class="submit-row"')

    def test_add_page_buttons(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'fa-history')
        self.assertNotContains(resp, 'id="tl-delete-btn"')
        self.assertNotContains(resp, 'id="tl-saveas-open-btn"')
        self.assertNotContains(resp, 'id="tl-saveas-modal"')
        self.assertContains(resp, 'href="%s"' % reverse('admin:qa_testlist_changelist'))
        self.assertContains(resp, 'name="_continue"', count=1)
        self.assertContains(resp, 'name="_save"', count=1)
        self.assertNotContains(resp, 'class="submit-row"')

    def test_save_as_is_off(self):
        self.assertFalse(qa_admin.TestListAdmin.save_as)

    def test_no_save_as_without_add_permission(self):
        _limited_testlist_user(can_add=False)
        self.client.login(username='limited', password='pwd')
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="tl-saveas-open-btn"')
        self.assertNotContains(resp, 'id="tl-saveas-modal"')
        self.assertNotContains(resp, 'id="tl-delete-btn"')
        self.assertContains(resp, 'name="_save"')

    def test_save_as_shown_with_add_permission(self):
        _limited_testlist_user(can_add=True)
        self.client.login(username='limited', password='pwd')
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'id="tl-saveas-open-btn"')

    def test_view_only_user_has_no_save_buttons(self):
        user = create_user(is_superuser=False, uname='viewer', pwd='pwd')
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='qa', codename='view_testlist'))
        self.client.login(username='viewer', password='pwd')
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="_save"')
        self.assertNotContains(resp, 'name="_continue"')
        self.assertNotContains(resp, 'id="tl-saveas-open-btn"')


class TestTestListSaveAs(TestCase):
    """Save As… posts the change form with _saveasnew to create a copy."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl = qa_utils.create_test_list(name='Daily Linac QC')
        self.t1 = qa_utils.create_test(name='first test')
        self.t2 = qa_utils.create_test(name='second test')
        self.m1 = qa_utils.create_test_list_membership(test_list=self.tl, test=self.t1, order=0)
        self.m2 = qa_utils.create_test_list_membership(test_list=self.tl, test=self.t2, order=1)
        self.child = qa_utils.create_test_list(name='Imaging Checks')
        qa_utils.create_test_list_membership(test_list=self.child, test=qa_utils.create_test(name='child test'))
        self.sublist = qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=self.child, order=2)
        self.sublist.outline = True
        self.sublist.save()
        self.utc = qa_utils.create_unit_test_collection(test_collection=self.tl)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))
        self.orig_slug = self.tl.slug

    def _post_data(self, name='Daily Linac QC (Copy)', slug='daily-linac-qc-copy', saveas=True, attachment=None):
        """A full change-form POST, as the builder page sends it (with the
        tests swapped round, as if reordered without saving)."""
        data = {
            'name': name,
            'slug': slug,
            'description': '',
            'warning_message': '',
            'javascript': '',
            'testlistmembership_set-TOTAL_FORMS': 2,
            'testlistmembership_set-INITIAL_FORMS': 2,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-0-id': self.m1.pk,
            'testlistmembership_set-0-test_list': self.tl.pk,
            'testlistmembership_set-0-test': self.t1.pk,
            'testlistmembership_set-0-order': 1,
            'testlistmembership_set-1-id': self.m2.pk,
            'testlistmembership_set-1-test_list': self.tl.pk,
            'testlistmembership_set-1-test': self.t2.pk,
            'testlistmembership_set-1-order': 0,
            'children-TOTAL_FORMS': 1,
            'children-INITIAL_FORMS': 1,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'children-0-id': self.sublist.pk,
            'children-0-parent': self.tl.pk,
            'children-0-child': self.child.pk,
            'children-0-order': 2,
            'children-0-outline': 'on',
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
        }
        if attachment is not None:
            data.update({
                'attachment_set-TOTAL_FORMS': 1,
                'attachment_set-INITIAL_FORMS': 1,
                'attachment_set-0-id': attachment.pk,
                'attachment_set-0-testlist': self.tl.pk,
                'attachment_set-0-comment': 'a comment',
            })
        if saveas:
            data['_saveasnew'] = '1'
            data['_saveas_source'] = self.tl.pk
        return data

    def _assert_original_unchanged(self):
        self.tl.refresh_from_db()
        self.assertEqual(self.tl.name, 'Daily Linac QC')
        self.assertEqual(self.tl.slug, self.orig_slug)
        self.assertEqual(
            list(self.tl.testlistmembership_set.order_by('order').values_list('test_id', 'order')),
            [(self.t1.pk, 0), (self.t2.pk, 1)],
        )
        self.assertEqual(list(self.tl.children.values_list('child_id', 'order', 'outline')), [(self.child.pk, 2, True)])
        self.assertEqual(self.tl.utcs.count(), 1)

    def test_save_as_creates_copy(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from qatrack.attachments.models import Attachment
        att = Attachment.objects.create(
            testlist=self.tl,
            attachment=SimpleUploadedFile('notes.txt', b'hello'),
            created_by=create_user(uname='attacher'),
        )
        try:
            resp = self.client.post(self.change_url, data=self._post_data(attachment=att))
        finally:
            att.attachment.delete(save=False)

        new = qa_models.TestList.objects.get(slug='daily-linac-qc-copy')
        self.assertNotEqual(new.pk, self.tl.pk)
        self.assertEqual(new.name, 'Daily Linac QC (Copy)')
        self.assertRedirects(resp, reverse('admin:qa_testlist_change', args=(new.pk,)), fetch_redirect_response=False)

        # tests in their posted (unsaved) order, and the sublist with its order and outline
        self.assertEqual(
            list(new.testlistmembership_set.order_by('order').values_list('test_id', 'order')),
            [(self.t2.pk, 0), (self.t1.pk, 1)],
        )
        self.assertEqual(list(new.children.values_list('child_id', 'order', 'outline')), [(self.child.pk, 2, True)])

        # attachments and machine assignments stay with the original
        self.assertFalse(Attachment.objects.filter(testlist=new).exists())
        self.assertEqual(Attachment.objects.filter(testlist=self.tl).count(), 1)
        self.assertEqual(new.utcs.count(), 0)
        self.assertEqual(qa_models.UnitTestCollection.objects.count(), 1)

        self._assert_original_unchanged()

        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertEqual(msgs, ['Created “Daily Linac QC (Copy)” as a copy of “Daily Linac QC”.'])

    def test_save_as_validation_error_rerenders_as_add_page(self):
        resp = self.client.post(self.change_url, data=self._post_data(slug=self.orig_slug))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(qa_models.TestList.objects.filter(name='Daily Linac QC (Copy)').count(), 0)
        self.assertTrue(resp.context['add'])
        self.assertContains(resp, '<title>Add Test List')
        self.assertContains(resp, '&rsaquo; Add')
        # saving again must still create a copy, never change the original
        self.assertContains(resp, '<input type="hidden" name="_saveasnew" value="1">', html=False)
        self.assertContains(resp, 'name="_saveas_source" value="%d"' % self.tl.pk)
        self.assertNotContains(resp, 'id="tl-saveas-open-btn"')
        self.assertNotContains(resp, 'id="tl-attachments-card"')
        self.assertContains(resp, 'name="_save"')
        # the rows come back from the posted data, so nothing is lost
        self.assertContains(resp, 'data-test-id="%d"' % self.t1.pk)
        self.assertContains(resp, 'data-test-id="%d"' % self.t2.pk)
        self.assertContains(resp, 'name="children-0-child"')
        self._assert_original_unchanged()

        # fixing the slug and saving again creates the copy
        resp = self.client.post(self.change_url, data=self._post_data(slug='fixed-slug'))
        new = qa_models.TestList.objects.get(slug='fixed-slug')
        self.assertRedirects(resp, reverse('admin:qa_testlist_change', args=(new.pk,)), fetch_redirect_response=False)
        self._assert_original_unchanged()

    def test_save_as_leaves_out_removed_rows(self):
        data = self._post_data(slug=self.orig_slug)
        data['testlistmembership_set-1-DELETE'] = 'on'
        resp = self.client.post(self.change_url, data=data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-test-id="%d"' % self.t1.pk)
        self.assertNotContains(resp, 'data-test-id="%d"' % self.t2.pk)

        data['slug'] = 'without-second'
        self.client.post(self.change_url, data=data)
        new = qa_models.TestList.objects.get(slug='without-second')
        self.assertEqual(list(new.testlistmembership_set.values_list('test_id', flat=True)), [self.t1.pk])
        self._assert_original_unchanged()

    def test_normal_save_still_renders_attachments(self):
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'id="tl-attachments-card"')

    def test_save_as_refused_without_add_permission(self):
        _limited_testlist_user(can_add=False)
        self.client.login(username='limited', password='pwd')
        resp = self.client.post(self.change_url, data=self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(qa_models.TestList.objects.filter(slug='daily-linac-qc-copy').exists())
        self._assert_original_unchanged()

    def test_save_as_allowed_with_add_permission(self):
        _limited_testlist_user(can_add=True)
        self.client.login(username='limited', password='pwd')
        self.client.post(self.change_url, data=self._post_data())
        self.assertTrue(qa_models.TestList.objects.filter(slug='daily-linac-qc-copy').exists())
        self._assert_original_unchanged()


class TestTestListSlugAvailable(TestCase):

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.url = reverse('admin:qa_testlist_slug_available')
        self.tl = qa_utils.create_test_list(name='Daily Linac QC')
        self.tl.slug = 'daily-linac-qc'
        self.tl.save()

    def test_available(self):
        resp = self.client.get(self.url, {'slug': 'brand-new_slug-2'})
        self.assertEqual(resp.json(), {'available': True, 'valid': True})

    def test_taken_with_suggestion(self):
        other = qa_utils.create_test_list(name='Copy 2')
        other.slug = 'daily-linac-qc-2'
        other.save()
        resp = self.client.get(self.url, {'slug': 'daily-linac-qc'})
        self.assertEqual(resp.json(), {'available': False, 'valid': True, 'suggestion': 'daily-linac-qc-3'})

    def test_invalid(self):
        for slug in ['', 'Has-Capitals', 'has spaces', 'semi;colon', 'x' * 256]:
            resp = self.client.get(self.url, {'slug': slug})
            self.assertEqual(resp.json(), {'available': False, 'valid': False}, slug)

    def test_staff_only(self):
        self.client.logout()
        create_user(is_staff=False, is_superuser=False, uname='nonstaff', pwd='pwd')
        self.client.login(username='nonstaff', password='pwd')
        resp = self.client.get(self.url, {'slug': 'anything'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('admin:login'), resp['Location'])


class TestTestListBuilderMachineMode(TestCase):
    """The builder's "Editing" dropdown: base list vs. one machine's references and tolerances."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.other_unit = qa_utils.create_unit(name='Machine B')
        self.group = create_group(name='Physicists')

        self.num_test = qa_utils.create_test(name='Output')
        self.bool_test = qa_utils.create_test(name='Door', test_type=qa_models.BOOLEAN)
        self.mc_test = qa_utils.create_test(name='Choice', test_type=qa_models.MULTIPLE_CHOICE, choices='a,b,c')
        self.unset_test = qa_utils.create_test(name='Unassigned')

        self.tl = qa_utils.create_test_list(name='Direct List')
        for i, t in enumerate([self.num_test, self.bool_test, self.mc_test]):
            qa_utils.create_test_list_membership(test_list=self.tl, test=t, order=i)
        self.freq = qa_utils.create_frequency(name='Daily', slug='daily')
        self.utc = qa_utils.create_unit_test_collection(
            unit=self.unit, frequency=self.freq, test_collection=self.tl, assigned_to=self.group,
        )

        # Assigning the list creates a UnitTestInfo per test; give them values
        self.num_uti = qa_models.UnitTestInfo.objects.get(unit=self.unit, test=self.num_test)
        self.num_uti.reference = qa_utils.create_reference(value=100)
        self.num_uti.tolerance = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.num_uti.save()
        self.bool_uti = qa_models.UnitTestInfo.objects.get(unit=self.unit, test=self.bool_test)
        # references saved from the UnitTestInfo form keep the numerical type
        self.bool_uti.reference = qa_utils.create_reference(value=1)
        self.bool_uti.save()
        self.mc_uti = qa_models.UnitTestInfo.objects.get(unit=self.unit, test=self.mc_test)
        self.mc_uti.tolerance = qa_utils.create_tolerance(
            tol_type=qa_models.MULTIPLE_CHOICE, mc_pass_choices='a,b', mc_tol_choices='c',
        )
        self.mc_uti.save()

        self.url = reverse('admin:qa_testlist_machine_values')

    def _get(self, unit_id, tests, **extra):
        params = {'unit': unit_id, 'tests': ','.join(str(t) for t in tests)}
        params.update(extra)
        return self.client.get(self.url, params)

    def test_values_for_unit(self):
        resp = self._get(
            self.unit.pk, [self.num_test.pk, self.bool_test.pk, self.mc_test.pk, 'bad', 999999],
            test_list=self.tl.pk,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        tests = data['tests']

        num = tests[str(self.num_test.pk)]
        self.assertEqual(num['reference'], '100')
        self.assertEqual(num['tolerance'], str(self.num_uti.tolerance))
        self.assertIn('Absolute', num['tolerance'])
        self.assertEqual(num['uti_url'], reverse('admin:qa_unittestinfo_change', args=[self.num_uti.pk]))

        self.assertEqual(tests[str(self.bool_test.pk)]['reference'], 'Yes')
        self.assertIsNone(tests[str(self.bool_test.pk)]['tolerance'])

        mc = tests[str(self.mc_test.pk)]
        self.assertIsNone(mc['reference'])
        self.assertIn('a:b', mc['tolerance'])

        # bad ids ignored; a valid id with no UnitTestInfo comes back as null
        self.assertNotIn('bad', tests)
        self.assertIsNone(tests['999999'])

        unit = data['unit']
        self.assertEqual(unit['name'], 'Machine A')
        self.assertEqual(unit['frequency'], 'Daily')
        self.assertEqual(unit['assigned_to'], 'Physicists')
        self.assertTrue(unit['active'])
        self.assertIsNone(unit['via'])
        self.assertEqual(unit['utc_url'], reverse('admin:qa_unittestcollection_change', args=[self.utc.pk]))

    def test_test_without_unit_test_info_is_null(self):
        resp = self._get(self.unit.pk, [self.unset_test.pk])
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['tests'][str(self.unset_test.pk)])

    def test_unknown_unit_404(self):
        self.assertEqual(self._get(999999, [self.num_test.pk]).status_code, 404)
        self.assertEqual(self._get('nope', [self.num_test.pk]).status_code, 404)

    def test_permission_required(self):
        staff = create_user(is_superuser=False, uname='staff', pwd='pwd')
        self.client.login(username='staff', password='pwd')
        self.assertEqual(self._get(self.unit.pk, [self.num_test.pk]).status_code, 403)

        uti_ct = ContentType.objects.get_for_model(qa_models.UnitTestInfo)
        staff.user_permissions.add(Permission.objects.get(content_type=uti_ct, codename='view_unittestinfo'))
        self.assertEqual(self._get(self.unit.pk, [self.num_test.pk]).status_code, 200)

    def test_change_form_dropdown_direct_and_through(self):
        # "Direct List" is a sublist of a parent assigned to Machine B, so Machine B
        # performs it too; Machine A has it directly and is only listed once.
        parent = qa_utils.create_test_list(name='Parent List')
        qa_utils.create_sublist(parent_test_list=parent, child_test_list=self.tl)
        qa_utils.create_unit_test_collection(unit=self.other_unit, test_collection=parent, null_frequency=True)
        qa_utils.create_unit_test_collection(unit=self.unit, test_collection=parent, null_frequency=True)

        resp = self.client.get(reverse('admin:qa_testlist_change', args=(self.tl.pk,)))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        select = re.search(r'<select id="tl-machine-scope-select".*?</select>', content, re.S).group(0)
        self.assertIn('Base list — all machines', select)
        self.assertIn('>Machine A (Daily)</option>', select)
        self.assertIn('<optgroup label="Through other test lists">', select)
        self.assertIn('>Machine B (via Parent List)</option>', select)
        self.assertEqual(select.count('value="%d"' % self.unit.pk), 1)
        direct, through = select.split('<optgroup')
        self.assertIn('Machine A', direct)
        self.assertIn('Machine B', through)

        # rows carry the (hidden until machine mode) Reference / Tolerance cells
        self.assertContains(resp, '<th class="tl-th-ref tl-col-ref">')
        self.assertContains(resp, '<th class="tl-th-tol tl-col-tol">')
        self.assertEqual(content.count('<td class="tl-cell-ref tl-col-ref">'), 3)
        self.assertEqual(content.count('<td class="tl-cell-tol tl-col-tol">'), 3)
        self.assertContains(resp, reverse('admin:qa_testlist_machine_values'))

    def test_through_endpoint_info_and_cycle(self):
        cycle = qa_utils.create_cycle(test_lists=[self.tl], name='My Cycle')
        qa_utils.create_unit_test_collection(unit=self.other_unit, test_collection=cycle, null_frequency=True)
        direct, through = qa_admin.get_testlist_scope_units(self.tl)
        self.assertEqual([d['unit_id'] for d in direct], [self.unit.pk])
        self.assertEqual([t['unit_id'] for t in through], [self.other_unit.pk])
        self.assertEqual(through[0]['label'], 'Machine B (via My Cycle)')

        resp = self._get(self.other_unit.pk, [self.num_test.pk], test_list=self.tl.pk)
        unit = resp.json()['unit']
        self.assertEqual(unit['via'], 'My Cycle')
        self.assertEqual(unit['frequency'], 'Ad Hoc')

    def test_sublist_rows_have_machine_cells(self):
        parent = qa_utils.create_test_list(name='Parent List')
        qa_utils.create_sublist(parent_test_list=parent, child_test_list=self.tl)
        resp = self.client.get(reverse('admin:qa_testlist_change', args=(parent.pk,)))
        content = resp.content.decode()
        self.assertIn('class="tl-sublist-test-row" data-test-id="%d"' % self.num_test.pk, content)
        self.assertEqual(content.count('<td class="tl-cell-ref tl-col-ref">'), 3)
        self.assertIn('colspan="8" class="tl-sublist-cell"', content)
        # no assignments: only the base list option
        select = re.search(r'<select id="tl-machine-scope-select".*?</select>', content, re.S).group(0)
        self.assertNotIn('<optgroup', select)

    def test_save_and_continue_keeps_unit(self):
        data = {
            'name': self.tl.name,
            'slug': 'direct-list',
            'description': '',
            'warning_message': '',
            'javascript': '',
            'tl_scope_unit': str(self.unit.pk),
            '_continue': 'Save and continue editing',
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
            'children-TOTAL_FORMS': 0,
            'children-INITIAL_FORMS': 0,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-TOTAL_FORMS': 3,
            'testlistmembership_set-INITIAL_FORMS': 3,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
        }
        for i, tlm in enumerate(qa_models.TestListMembership.objects.filter(test_list=self.tl).order_by('order')):
            data['testlistmembership_set-%d-id' % i] = tlm.pk
            data['testlistmembership_set-%d-test_list' % i] = self.tl.pk
            data['testlistmembership_set-%d-test' % i] = tlm.test_id
            data['testlistmembership_set-%d-order' % i] = i
        url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith('unit=%d' % self.unit.pk))

        data['tl_scope_unit'] = 'base'
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('unit=', resp['Location'])


class TestTestListBuilderMachineRefTol(TestCase):
    """Machine mode's Reference and Tolerance dialog (testlist_machine_ref_tol)."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        get_internal_user()
        self.bool_warn, self.bool_act = get_bool_tols()
        self.unit = qa_utils.create_unit(name='Machine A')
        self.other_unit = qa_utils.create_unit(name='Machine B')

        self.num_test = qa_utils.create_test(name='Output')
        self.bool_test = qa_utils.create_test(name='Door', test_type=qa_models.BOOLEAN)
        self.mc_test = qa_utils.create_test(name='Choice', test_type=qa_models.MULTIPLE_CHOICE, choices='a,b,c')
        self.wrap_test = qa_utils.create_test(name='Gantry', test_type=qa_models.WRAPAROUND, wrap_low=0, wrap_high=360)
        self.upload_test = qa_utils.create_test(name='Image', test_type=qa_models.UPLOAD)
        self.date_test = qa_utils.create_test(name='Calibrated', test_type=qa_models.DATE)
        self.datetime_test = qa_utils.create_test(name='Calibrated At', test_type=qa_models.DATETIME)

        self.abs_tol = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        self.pct_tol = qa_utils.create_tolerance(tol_type=qa_models.PERCENT, act_low=-5, tol_low=-4, tol_high=4, act_high=5)
        self.mc_tol = qa_utils.create_tolerance(
            tol_type=qa_models.MULTIPLE_CHOICE, mc_pass_choices='a,b', mc_tol_choices='c',
        )

        self.old_ref = qa_utils.create_reference(value=100)
        self.num_uti = qa_utils.create_unit_test_info(
            unit=self.unit, test=self.num_test, ref=self.old_ref, tol=self.abs_tol,
        )
        self.bool_uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.bool_test)
        self.mc_uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.mc_test)
        self.wrap_uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.wrap_test)
        self.upload_uti = qa_utils.create_unit_test_info(unit=self.unit, test=self.upload_test)

    def _url(self, uti):
        return reverse('admin:qa_testlist_machine_ref_tol', args=[uti.pk])

    def _grant(self, user, *codenames):
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(content_type__app_label='qa', codename=codename))

    def test_get_numerical(self):
        resp = self.client.get(self._url(self.num_uti))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Reference and Tolerance')
        self.assertContains(resp, 'Output on Machine A')
        self.assertContains(resp, 'Currently: 100 · %s' % self.abs_tol)
        # the current reference is filled in so saving without touching it keeps it
        self.assertContains(resp, 'type="text" name="reference_value" value="100"')
        tols = set(resp.context['form'].fields['tolerance'].queryset)
        self.assertEqual(tols, {self.abs_tol, self.pct_tol})
        self.assertContains(resp, 'No tolerance')
        self.assertContains(resp, 'data-newtol-url="%s?uti=%d"' % (
            reverse('admin:qa_testlist_new_tolerance'), self.num_uti.pk,
        ))
        self.assertContains(resp, reverse('admin:qa_unittestinfo_change', args=[self.num_uti.pk]))
        # posts to itself, not to the test list form
        self.assertContains(resp, 'action="%s"' % self._url(self.num_uti))
        for name in ('name="unit"', 'name="test"', 'name="active"', 'name="assigned_to"'):
            self.assertNotContains(resp, name)

    def test_get_boolean(self):
        resp = self.client.get(self._url(self.bool_uti))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Currently: not set')
        self.assertContains(resp, '<select name="reference_value"')
        self.assertContains(resp, '<option value="1">Yes</option>')
        self.assertContains(resp, '<option value="0">No</option>')
        tols = set(resp.context['form'].fields['tolerance'].queryset)
        self.assertEqual(tols, set(qa_models.Tolerance.objects.filter(type=qa_models.BOOLEAN)))
        self.assertIn(self.bool_act, tols)
        # Yes/No tolerances are fixed records: no New Tolerance button
        self.assertNotContains(resp, 'id="tl-reftol-new-tolerance"')

    def test_get_multiple_choice(self):
        resp = self.client.get(self._url(self.mc_uti))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'type="hidden" name="reference_value"')
        self.assertNotContains(resp, 'for="tl-reftol-reference_value"')
        tols = set(resp.context['form'].fields['tolerance'].queryset)
        self.assertEqual(tols, {self.mc_tol})

    def test_get_wraparound(self):
        resp = self.client.get(self._url(self.wrap_uti))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'type="text" name="reference_value"')
        self.assertContains(resp, 'Between 0.0 and 360.0.')
        tols = set(resp.context['form'].fields['tolerance'].queryset)
        self.assertEqual(tols, {self.abs_tol})

    def test_permission_and_404(self):
        self.assertEqual(self.client.get(reverse('admin:qa_testlist_machine_ref_tol', args=[999999])).status_code, 404)

        staff = create_user(is_superuser=False, uname='staff', pwd='pwd')
        self.client.login(username='staff', password='pwd')
        self._grant(staff, 'view_unittestinfo')
        self.assertEqual(self.client.get(self._url(self.num_uti)).status_code, 403)
        resp = self.client.post(self._url(self.num_uti), {'reference_value': '5', 'tolerance': self.abs_tol.pk})
        self.assertEqual(resp.status_code, 403)
        self.num_uti.refresh_from_db()
        self.assertEqual(self.num_uti.reference, self.old_ref)

        self._grant(staff, 'change_unittestinfo')
        self.assertEqual(self.client.get(self._url(self.num_uti)).status_code, 200)

    def test_post_numerical_saves_and_records_history(self):
        resp = self.client.post(self._url(self.num_uti), {
            'reference_value': '5',
            'tolerance': self.pct_tol.pk,
            'comment': 'New calibration',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['test_id'], self.num_test.pk)
        self.assertEqual(data['unit_id'], self.unit.pk)
        self.assertEqual(data['message'], 'Saved for Output on Machine A.')

        self.num_uti.refresh_from_db()
        self.assertEqual(self.num_uti.reference.value, 5)
        self.assertEqual(self.num_uti.reference.created_by, self.user)
        self.assertEqual(self.num_uti.tolerance, self.pct_tol)

        change = qa_models.UnitTestInfoChange.objects.get(unit_test_info=self.num_uti)
        self.assertEqual(change.reference, self.old_ref)
        self.assertEqual(change.tolerance, self.abs_tol)
        self.assertTrue(change.reference_changed)
        self.assertTrue(change.tolerance_changed)
        self.assertEqual(change.comment, 'New calibration')
        self.assertEqual(change.changed_by, self.user)

        # same display strings as machine mode's table
        values = self.client.get(
            reverse('admin:qa_testlist_machine_values'), {'unit': self.unit.pk, 'tests': self.num_test.pk},
        ).json()['tests'][str(self.num_test.pk)]
        self.assertEqual(data['reference'], values['reference'])
        self.assertEqual(data['tolerance'], values['tolerance'])
        self.assertEqual(data['reference'], '5')

    def test_post_unchanged_reference_keeps_it(self):
        resp = self.client.post(self._url(self.num_uti), {'reference_value': '100', 'tolerance': self.pct_tol.pk})
        self.assertEqual(resp.status_code, 200)
        self.num_uti.refresh_from_db()
        self.assertEqual(self.num_uti.reference, self.old_ref)
        change = qa_models.UnitTestInfoChange.objects.get(unit_test_info=self.num_uti)
        self.assertFalse(change.reference_changed)
        self.assertTrue(change.tolerance_changed)

    def test_post_boolean(self):
        resp = self.client.post(self._url(self.bool_uti), {'reference_value': '1', 'tolerance': self.bool_act.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['reference'], 'Yes')
        self.bool_uti.refresh_from_db()
        self.assertEqual(self.bool_uti.reference.value, 1)
        self.assertEqual(self.bool_uti.tolerance, self.bool_act)

    def test_post_percent_with_zero_reference_422(self):
        resp = self.client.post(self._url(self.num_uti), {'reference_value': '0', 'tolerance': self.pct_tol.pk})
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'Reference value cannot be zero when using a percent tolerance', status_code=422)
        self.assertContains(resp, 'id="tl-reftol-modal"', status_code=422)
        # "Currently" still shows the saved values, not the rejected ones
        self.assertContains(resp, 'Currently: 100 · %s' % self.abs_tol, status_code=422)
        self.num_uti.refresh_from_db()
        self.assertEqual(self.num_uti.reference, self.old_ref)
        self.assertEqual(self.num_uti.tolerance, self.abs_tol)
        self.assertFalse(qa_models.UnitTestInfoChange.objects.exists())

    def test_post_wraparound_out_of_range_422(self):
        resp = self.client.post(self._url(self.wrap_uti), {'reference_value': '400', 'tolerance': self.abs_tol.pk})
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'Reference value must be between 0.0 and 360.0', status_code=422)
        self.wrap_uti.refresh_from_db()
        self.assertIsNone(self.wrap_uti.reference)
        self.assertIsNone(self.wrap_uti.tolerance)
        self.assertFalse(qa_models.UnitTestInfoChange.objects.exists())

    def test_post_cannot_change_unit_test_or_active(self):
        resp = self.client.post(self._url(self.num_uti), {
            'reference_value': '100',
            'tolerance': self.abs_tol.pk,
            'unit': self.other_unit.pk,
            'test': self.bool_test.pk,
            'active': '',
            'assigned_to': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.num_uti.refresh_from_db()
        self.assertEqual(self.num_uti.unit, self.unit)
        self.assertEqual(self.num_uti.test, self.num_test)
        self.assertTrue(self.num_uti.active)
        self.assertIsNotNone(self.num_uti.assigned_to)
        # nothing changed, so no history entry
        self.assertFalse(qa_models.UnitTestInfoChange.objects.exists())

    def test_admin_save_model_uses_shared_history_helper(self):
        request = RequestFactory().get('/')
        request.user = self.user
        model_admin = qa_admin.UnitTestInfoAdmin(qa_models.UnitTestInfo, AdminSite())
        data = {'reference_value': '7', 'tolerance': self.pct_tol.pk, 'comment': 'From admin'}
        form = model_admin.get_form(request)(instance=self.num_uti, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(
            qa_admin, 'record_unit_test_info_change', wraps=qa_admin.record_unit_test_info_change,
        ) as helper:
            model_admin.save_model(request, model_admin.save_form(request, form, True), form, True)
        self.assertEqual(helper.call_count, 1)
        change = qa_models.UnitTestInfoChange.objects.get(unit_test_info=self.num_uti)
        self.assertEqual(change.reference, self.old_ref)
        self.assertEqual(change.tolerance, self.abs_tol)
        self.assertTrue(change.reference_changed)
        self.assertTrue(change.tolerance_changed)
        self.assertEqual(change.comment, 'From admin')
        self.assertEqual(change.changed_by, self.user)

    def test_machine_values_flags_types_without_limits(self):
        no_uti_test = qa_utils.create_test(name='Not Yet Saved', test_type=qa_models.UPLOAD)
        ids = [
            self.num_test, self.bool_test, self.mc_test, self.upload_test, self.date_test, self.datetime_test,
            no_uti_test,
        ]
        resp = self.client.get(reverse('admin:qa_testlist_machine_values'), {
            'unit': self.unit.pk, 'tests': ','.join(str(t.pk) for t in ids),
        })
        data = resp.json()
        limits = data['limits']
        self.assertEqual(limits[str(self.num_test.pk)], {
            'uses_limits': True, 'reference': 'required', 'tolerance': 'required',
        })
        self.assertEqual(limits[str(self.bool_test.pk)]['tolerance'], 'optional')
        self.assertEqual(limits[str(self.mc_test.pk)]['reference'], 'unused')
        for t in (self.upload_test, self.date_test, self.datetime_test, no_uti_test):
            self.assertFalse(limits[str(t.pk)]['uses_limits'])
        self.assertEqual(data['tests'][str(self.num_test.pk)]['uti_id'], self.num_uti.pk)
        self.assertIsNone(data['tests'][str(no_uti_test.pk)])

    def test_change_form_has_dialog_url_only_with_change_permission(self):
        tl = qa_utils.create_test_list(name='Direct List')
        qa_utils.create_test_list_membership(test_list=tl, test=self.num_test)
        url = reverse('admin:qa_testlist_change', args=(tl.pk,))
        base = reverse('admin:qa_testlist_machine_ref_tol', args=[0])
        resp = self.client.get(url)
        self.assertContains(resp, 'data-ref-tol-url="%s"' % base)
        self.assertContains(resp, 'id="tl-reftol-container"')

        staff = create_user(is_superuser=False, uname='staff', pwd='pwd')
        self._grant(staff, 'change_testlist', 'view_unittestinfo')
        self.client.login(username='staff', password='pwd')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'data-ref-tol-url=')


class TestTestListBuilderNewTolerance(TestCase):
    """The New Tolerance dialog opened from machine mode's Reference and Tolerance dialog."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        get_bool_tols()
        self.unit = qa_utils.create_unit(name='Machine A')
        self.num_uti = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(name='Output'))
        self.wrap_uti = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(
            name='Gantry', test_type=qa_models.WRAPAROUND, wrap_low=0, wrap_high=360,
        ))
        self.mc_uti = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(
            name='Choice', test_type=qa_models.MULTIPLE_CHOICE, choices='a,b,c',
        ))
        self.str_uti = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(
            name='Notes', test_type=qa_models.STRING,
        ))
        self.bool_uti = qa_utils.create_unit_test_info(unit=self.unit, test=qa_utils.create_test(
            name='Door', test_type=qa_models.BOOLEAN,
        ))
        self.url = reverse('admin:qa_testlist_new_tolerance')

    def _types(self, uti):
        resp = self.client.get(self.url, {'uti': uti.pk})
        self.assertEqual(resp.status_code, 200)
        return [value for value, label in resp.context['form'].fields['type'].choices], resp

    def _post(self, uti, **data):
        data['uti'] = uti.pk
        return self.client.post(self.url, data)

    def test_types_offered_per_test_type(self):
        types, resp = self._types(self.num_uti)
        self.assertEqual(types, [qa_models.ABSOLUTE, qa_models.PERCENT])
        self.assertContains(resp, '<select name="type"')
        self.assertContains(resp, 'name="tol_low"')
        self.assertNotContains(resp, 'name="mc_pass_choices"')
        self.assertContains(resp, "It isn't applied to this machine until you click Save in the previous dialog.")

        types, resp = self._types(self.wrap_uti)
        self.assertEqual(types, [qa_models.ABSOLUTE])
        self.assertContains(resp, 'type="hidden" name="type" value="absolute"')
        self.assertContains(resp, 'class="tl-newtol-type-value">Absolute<')

        for uti in (self.mc_uti, self.str_uti):
            types, resp = self._types(uti)
            self.assertEqual(types, [qa_models.MULTIPLE_CHOICE])
            self.assertContains(resp, 'name="mc_pass_choices"')
            self.assertNotContains(resp, 'name="tol_low"')

        self.assertEqual(self.client.get(self.url, {'uti': self.bool_uti.pk}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'uti': 999999}).status_code, 404)

    def test_create_absolute_percent_and_mc(self):
        resp = self._post(self.num_uti, type='absolute', act_low='-3', tol_low='-2', tol_high='2', act_high='3')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        tol = qa_models.Tolerance.objects.get(pk=data['id'])
        self.assertEqual(data['label'], str(tol))
        self.assertEqual((tol.type, tol.act_low, tol.tol_low, tol.tol_high, tol.act_high), ('absolute', -3, -2, 2, 3))
        self.assertEqual(tol.created_by, self.user)
        self.assertEqual(tol.modified_by, self.user)
        # not applied to the unit until the Reference and Tolerance dialog is saved
        self.num_uti.refresh_from_db()
        self.assertIsNone(self.num_uti.tolerance)

        resp = self._post(self.num_uti, type='percent', tol_low='-1', tol_high='1')
        self.assertEqual(resp.status_code, 200)
        tol = qa_models.Tolerance.objects.get(pk=resp.json()['id'])
        self.assertEqual((tol.type, tol.act_low, tol.tol_high), ('percent', None, 1))

        resp = self._post(self.mc_uti, type='multchoice', mc_pass_choices='a, b', mc_tol_choices='c')
        self.assertEqual(resp.status_code, 200)
        tol = qa_models.Tolerance.objects.get(pk=resp.json()['id'])
        self.assertEqual((tol.type, tol.mc_pass_choices, tol.mc_tol_choices), ('multchoice', 'a,b', 'c'))

    def test_type_not_offered_is_rejected(self):
        before = qa_models.Tolerance.objects.count()
        resp = self._post(self.wrap_uti, type='percent', tol_low='-1', tol_high='1')
        self.assertEqual(resp.status_code, 422)
        resp = self._post(self.num_uti, type='boolean')
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(qa_models.Tolerance.objects.count(), before)

    def test_invalid_limits_422(self):
        before = qa_models.Tolerance.objects.count()
        # the model's own check: at least one limit for absolute/percent
        resp = self._post(self.num_uti, type='absolute')
        self.assertContains(resp, 'You must set at least one Tolerance or Action level', status_code=422)
        # the model's own check: multiple choice needs a passing choice
        resp = self._post(self.mc_uti, type='multchoice', mc_pass_choices='')
        self.assertContains(resp, 'You must give at least 1 passing choice', status_code=422)
        # limits out of order
        resp = self._post(self.num_uti, type='absolute', tol_low='2', tol_high='1')
        self.assertContains(resp, 'Tolerance High must be at least Tolerance Low.', status_code=422)
        self.assertEqual(qa_models.Tolerance.objects.count(), before)

    def test_duplicate_names_existing(self):
        existing = qa_utils.create_tolerance(act_low=-3, tol_low=-2, tol_high=2, act_high=3)
        before = qa_models.Tolerance.objects.count()
        resp = self._post(self.num_uti, type='absolute', act_low='-3', tol_low='-2', tol_high='2', act_high='3')
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'A tolerance with these values already exists: %s.' % existing, status_code=422)
        self.assertContains(resp, 'data-tolerance-id="%d"' % existing.pk, status_code=422)
        self.assertContains(resp, 'Use This One', status_code=422)
        self.assertEqual(qa_models.Tolerance.objects.count(), before)

    def test_permission(self):
        staff = create_user(is_superuser=False, uname='staff', pwd='pwd')
        uti_ct = ContentType.objects.get_for_model(qa_models.UnitTestInfo)
        staff.user_permissions.add(Permission.objects.get(content_type=uti_ct, codename='change_unittestinfo'))
        self.client.login(username='staff', password='pwd')
        self.assertEqual(self.client.get(self.url, {'uti': self.num_uti.pk}).status_code, 403)
        resp = self._post(self.num_uti, type='absolute', tol_low='-1', tol_high='1')
        self.assertEqual(resp.status_code, 403)
        # the Reference and Tolerance dialog has no New Tolerance button for them
        resp = self.client.get(reverse('admin:qa_testlist_machine_ref_tol', args=[self.num_uti.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="tl-reftol-new-tolerance"')

        tol_ct = ContentType.objects.get_for_model(qa_models.Tolerance)
        staff.user_permissions.add(Permission.objects.get(content_type=tol_ct, codename='add_tolerance'))
        self.assertEqual(self.client.get(self.url, {'uti': self.num_uti.pk}).status_code, 200)


class TestTestListBuilderPerformPreview(TestCase):
    """Preview tab: data the builder JS uses to show the real Perform QC page (read-only)."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.unit = qa_utils.create_unit(name='Machine A')
        self.other_unit = qa_utils.create_unit(name='Machine B')
        self.cycle_unit = qa_utils.create_unit(name='Machine C')
        self.test = qa_utils.create_test(name='Output')
        self.tl = qa_utils.create_test_list(name='Direct List')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.test)
        self.utc = qa_utils.create_unit_test_collection(unit=self.unit, test_collection=self.tl)
        self.parent = qa_utils.create_test_list(name='Parent List')
        qa_utils.create_sublist(parent_test_list=self.parent, child_test_list=self.tl)
        qa_utils.create_unit_test_collection(unit=self.other_unit, test_collection=self.parent, null_frequency=True)
        self.cycle = qa_utils.create_cycle(test_lists=[self.tl], name='My Cycle')
        qa_utils.create_unit_test_collection(unit=self.cycle_unit, test_collection=self.cycle, null_frequency=True)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _preview_units(self, resp):
        match = re.search(r'<script id="tl-preview-units" type="application/json">(.*?)</script>',
                          resp.content.decode(), re.S)
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_change_form_has_preview_container_and_units(self):
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-can-preview-perform="1"')
        # one message for the layout preview's banner, with or without the pick-a-machine hint
        self.assertContains(
            resp,
            'data-msg-pick-machine="Layout preview: the order, sublists and descriptions of this test list. '
            'Pick a machine in the Editing menu to see the full Perform QC page. Nothing you enter here is saved."',
        )
        self.assertContains(
            resp,
            'data-msg-layout="Layout preview: the order, sublists and descriptions of this test list. '
            'Nothing you enter here is saved."',
        )
        self.assertNotContains(resp, 'a rough layout of this test list')
        self.assertContains(resp, 'data-msg-unsaved="You have unsaved changes.')
        units = self._preview_units(resp)
        self.assertEqual(units[str(self.unit.pk)], {
            'preview_url': reverse('perform_qa_preview', kwargs={'pk': self.utc.pk}),
        })
        self.assertEqual(units[str(self.other_unit.pk)], {
            'via': 'Parent List',
            'via_url': reverse('admin:qa_testlist_change', args=(self.parent.pk,)) + '?unit=%d' % self.other_unit.pk,
            'via_cycle': False,
        })
        self.assertEqual(units[str(self.cycle_unit.pk)], {
            'via': 'My Cycle',
            'via_url': reverse('admin:qa_testlistcycle_change', args=(self.cycle.pk,)),
            'via_cycle': True,
        })

    def test_preview_url_renders_for_admin(self):
        units = self._preview_units(self.client.get(self.change_url))
        resp = self.client.get(units[str(self.unit.pk)]['preview_url'])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['X-Frame-Options'], 'SAMEORIGIN')
        self.assertContains(resp, 'This is only a preview. Nothing you enter here is saved.')

    def test_add_form_has_no_preview_units(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        self.assertNotContains(resp, 'id="tl-preview-units"')

    def test_no_real_preview_without_change_permission(self):
        viewer = create_user(is_superuser=False, uname='viewer', pwd='pwd')
        viewer.is_staff = True
        viewer.save()
        viewer.user_permissions.add(Permission.objects.get(codename='view_testlist'))
        self.client.login(username='viewer', password='pwd')
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-can-preview-perform="0"')


class TestTestListBuilderRemovedRows(TestCase):
    """Rows removed in the builder (DELETE ticked) are left out of validation
    and stay removed when the page is re-rendered after an error."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl = qa_utils.create_test_list(name='Throwaway QC')
        self.dup = qa_utils.create_test(name='kv_mv_coincidence')
        self.other = qa_utils.create_test(name='other test')
        self.m_dup = qa_utils.create_test_list_membership(test_list=self.tl, test=self.dup, order=0)
        self.m_other = qa_utils.create_test_list_membership(test_list=self.tl, test=self.other, order=1)
        self.child = qa_utils.create_test_list(name='Imaging Checks')
        qa_utils.create_test_list_membership(test_list=self.child, test=self.dup)
        self.sublist = qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=self.child, order=2)
        self.url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _post_data(self, name='Throwaway QC', delete_dup=None, delete_sublist=None):
        data = {
            'name': name,
            'slug': 'throwaway-qc',
            'description': '',
            'warning_message': '',
            'javascript': '',
            'testlistmembership_set-TOTAL_FORMS': 2,
            'testlistmembership_set-INITIAL_FORMS': 2,
            'testlistmembership_set-MIN_NUM_FORMS': 0,
            'testlistmembership_set-MAX_NUM_FORMS': 1000,
            'testlistmembership_set-0-id': self.m_dup.pk,
            'testlistmembership_set-0-test_list': self.tl.pk,
            'testlistmembership_set-0-test': self.dup.pk,
            'testlistmembership_set-0-order': 0,
            'testlistmembership_set-1-id': self.m_other.pk,
            'testlistmembership_set-1-test_list': self.tl.pk,
            'testlistmembership_set-1-test': self.other.pk,
            'testlistmembership_set-1-order': 1,
            'children-TOTAL_FORMS': 1,
            'children-INITIAL_FORMS': 1,
            'children-MIN_NUM_FORMS': 0,
            'children-MAX_NUM_FORMS': 1000,
            'children-0-id': self.sublist.pk,
            'children-0-parent': self.tl.pk,
            'children-0-child': self.child.pk,
            'children-0-order': 2,
            'attachment_set-TOTAL_FORMS': 0,
            'attachment_set-INITIAL_FORMS': 0,
            'attachment_set-MIN_NUM_FORMS': 0,
            'attachment_set-MAX_NUM_FORMS': 1000,
        }
        if delete_dup is not None:
            data['testlistmembership_set-0-DELETE'] = delete_dup
        if delete_sublist is not None:
            data['children-0-DELETE'] = delete_sublist
        return data

    def _row(self, content, row_id):
        """Return the opening <tr ...> tag of a builder row."""
        match = re.search(r'<tr class="tl-member-item[^>]*id="%s"[^>]*>' % row_id, content)
        self.assertIsNotNone(match, row_id)
        return match.group(0)

    def _delete_box(self, content, prefix):
        match = re.search(r'<input type="checkbox" name="%s-DELETE"[^>]*>' % prefix, content)
        self.assertIsNotNone(match, prefix)
        return match.group(0)

    def test_duplicate_still_rejected(self):
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'appear more than once')
        self.assertTrue(self.tl.testlistmembership_set.filter(pk=self.m_dup.pk).exists())

    def test_duplicate_error_names_the_tests(self):
        """Plain language, with each test's name and its macro name in brackets."""
        resp = self.client.post(self.url, self._post_data())
        self.assertContains(
            resp,
            'These tests appear more than once in this test list, directly or through a sublist: '
            '%s (%s). Remove the extra copies, then save again.' % (self.dup.name, self.dup.slug),
        )
        self.assertNotContains(resp, 'sublists) ::')

    def test_unticked_delete_value_still_counts(self):
        resp = self.client.post(self.url, self._post_data(delete_dup='false'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'appear more than once')

    def test_removed_direct_test_not_counted(self):
        for value in ('on', 'true', '1'):
            with self.subTest(value=value):
                if not qa_models.TestListMembership.objects.filter(pk=self.m_dup.pk).exists():
                    # put the direct test back after the previous round removed it
                    self.m_dup = qa_utils.create_test_list_membership(test_list=self.tl, test=self.dup, order=0)
                resp = self.client.post(self.url, self._post_data(delete_dup=value))
                self.assertEqual(resp.status_code, 302)
                self.assertFalse(qa_models.TestListMembership.objects.filter(pk=self.m_dup.pk).exists())
                self.assertEqual(list(self.tl.testlistmembership_set.values_list('test_id', flat=True)), [self.other.pk])

    def test_removed_sublist_not_counted(self):
        resp = self.client.post(self.url, self._post_data(delete_sublist='on'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self.tl.children.exists())
        self.assertEqual(self.tl.testlistmembership_set.count(), 2)

    def test_removed_rows_stay_removed_after_error(self):
        resp = self.client.post(self.url, self._post_data(name='', delete_dup='on', delete_sublist='on'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('appear more than once', content)

        self.assertIn('checked', self._delete_box(content, 'testlistmembership_set-0'))
        self.assertIn('display: none', self._row(content, 'testlistmembership_set-0'))

        self.assertNotIn('checked', self._delete_box(content, 'testlistmembership_set-1'))
        self.assertNotIn('display: none', self._row(content, 'testlistmembership_set-1'))

        self.assertIn('checked', self._delete_box(content, 'children-0'))
        card = re.search(r'<div class="tl-sublist-card[^>]*>', content).group(0)
        self.assertIn('display: none', card)

        # nothing was saved
        self.assertEqual(self.tl.testlistmembership_set.count(), 2)
        self.assertTrue(self.tl.children.exists())

    def test_rows_not_removed_render_normally(self):
        resp = self.client.post(self.url, self._post_data(name='', delete_dup='false'))
        content = resp.content.decode()
        self.assertNotIn('checked', self._delete_box(content, 'testlistmembership_set-0'))
        self.assertNotIn('display: none', self._row(content, 'testlistmembership_set-0'))
        card = re.search(r'<div class="tl-sublist-card[^>]*>', content).group(0)
        self.assertNotIn('display: none', card)

    def test_add_page_no_unsaved_instance_warning(self):
        import warnings

        from django.utils.deprecation import RemovedInDjango50Warning

        with warnings.catch_warnings():
            warnings.simplefilter('error', RemovedInDjango50Warning)
            resp = self.client.get(reverse('admin:qa_testlist_add'))
            self.assertEqual(resp.status_code, 200)
            resp = self.client.post(reverse('admin:qa_testlist_add'), {
                'name': '',
                'slug': '',
                'testlistmembership_set-TOTAL_FORMS': 0,
                'testlistmembership_set-INITIAL_FORMS': 0,
                'children-TOTAL_FORMS': 0,
                'children-INITIAL_FORMS': 0,
                'attachment_set-TOTAL_FORMS': 0,
                'attachment_set-INITIAL_FORMS': 0,
            })
            self.assertEqual(resp.status_code, 200)


class TestTestListUnsavedChangesWarning(TestCase):
    """The change form carries the "Unsaved changes" dialog and the JS that opens it."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl = qa_utils.create_test_list(name='Daily QC')

    def _assert_dialog(self, resp):
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        modal = re.search(r'<div class="tl-modal-backdrop" id="tl-unsaved-modal"[^>]*>', content)
        self.assertIsNotNone(modal)
        self.assertIn('hidden', modal.group(0))
        self.assertIn('data-msg-switch="', modal.group(0))
        dialog = re.search(r'<div class="tl-modal-dialog tl-unsaved-dialog"[^>]*>', content)
        self.assertIsNotNone(dialog)
        self.assertIn('role="dialog"', dialog.group(0))
        self.assertIn('aria-modal="true"', dialog.group(0))
        self.assertIn('aria-labelledby="tl-unsaved-title"', dialog.group(0))
        self.assertContains(resp, 'id="tl-unsaved-title"')
        self.assertContains(resp, 'id="tl-unsaved-stay"')
        self.assertContains(resp, 'id="tl-unsaved-leave"')
        self.assertContains(resp, 'Stay on This Page')
        self.assertContains(resp, 'Leave Without Saving')
        # the builder JS that watches the form and opens the dialog
        self.assertContains(resp, 'function initUnsavedChanges()')
        self.assertContains(resp, 'beforeunload')

    def test_change_page_has_dialog(self):
        self._assert_dialog(self.client.get(reverse('admin:qa_testlist_change', args=(self.tl.pk,))))

    def test_add_page_has_dialog(self):
        self._assert_dialog(self.client.get(reverse('admin:qa_testlist_add')))

    def test_changelist_has_no_dialog(self):
        resp = self.client.get(reverse('admin:qa_testlist_changelist'))
        self.assertNotContains(resp, 'id="tl-unsaved-modal"')


class TestTestListAssignMachine(TestCase):
    """The builder's "Assign to Machine" dialog creates a UnitTestCollection for the test list."""

    def setUp(self):
        create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.tl = qa_utils.create_test_list(name='Throwaway List')
        self.site = qa_utils.create_site(name='Main Site')
        self.unit = qa_utils.create_unit(name='Linac 1', site=self.site)
        self.inactive_unit = qa_utils.create_unit(name='Old Linac', site=self.site, active=False)
        self.freq = qa_utils.create_frequency(name='Weekly', slug='weekly')
        self.group = create_group(name='Therapists')
        self.other_group = create_group(name='Physicists')
        self.url = reverse('admin:qa_testlist_assign_machine')
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _post(self, **overrides):
        data = {
            'test_list': self.tl.pk,
            'unit': self.unit.pk,
            'frequency': self.freq.pk,
            'assigned_to': self.group.pk,
            'visible_to': [self.group.pk, self.other_group.pk],
            'active': 'on',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def _limited_user(self, can_assign):
        user = _limited_testlist_user(can_add=False)
        if can_assign:
            user.user_permissions.add(Permission.objects.get(codename='add_unittestcollection'))
        self.client.logout()
        self.client.login(username='limited', password='pwd')
        return user

    def test_get_returns_dialog(self):
        resp = self.client.get(self.url, {'test_list': self.tl.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="tl-assign-modal"')
        self.assertContains(resp, 'role="dialog"')
        self.assertContains(resp, 'Assign to Machine')
        self.assertContains(resp, "It doesn't wait for you to save this test list.")
        for name in ('unit', 'frequency', 'assigned_to', 'visible_to', 'active'):
            self.assertContains(resp, 'name="%s"' % name)
        # active units only, grouped by site; Ad Hoc is the empty frequency
        self.assertContains(resp, '<optgroup label="Main Site">')
        self.assertContains(resp, 'Linac 1')
        self.assertNotContains(resp, 'Old Linac')
        self.assertContains(resp, '<option value="" selected>Ad Hoc</option>')
        # the test list is fixed by the view, never a dialog field
        self.assertNotContains(resp, 'name="content_type"')
        self.assertNotContains(resp, 'name="object_id"')

    def test_get_without_permission_forbidden(self):
        self._limited_user(can_assign=False)
        resp = self.client.get(self.url, {'test_list': self.tl.pk})
        self.assertEqual(resp.status_code, 403)
        resp = self._post()
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(qa_models.UnitTestCollection.objects.exists())

    def test_get_with_permission_only(self):
        self._limited_user(can_assign=True)
        resp = self.client.get(self.url, {'test_list': self.tl.pk})
        self.assertEqual(resp.status_code, 200)

    def test_unknown_test_list_404(self):
        self.assertEqual(self.client.get(self.url, {'test_list': 999999}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {'test_list': 'x'}).status_code, 404)

    def test_post_creates_assignment(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        utc = qa_models.UnitTestCollection.objects.get()
        self.assertEqual(utc.tests_object, self.tl)
        self.assertEqual(utc.unit, self.unit)
        self.assertEqual(utc.frequency, self.freq)
        self.assertEqual(utc.assigned_to, self.group)
        self.assertEqual(set(utc.visible_to.all()), {self.group, self.other_group})
        self.assertTrue(utc.active)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['unit_id'], self.unit.pk)
        self.assertEqual(data['unit_name'], 'Linac 1')
        self.assertEqual(data['label'], 'Linac 1 (Weekly)')
        self.assertEqual(data['message'], 'Assigned to Linac 1 (Weekly).')
        self.assertEqual(data['utc_url'], reverse('admin:qa_unittestcollection_change', args=[utc.pk]))
        self.assertTrue(data['show_in_scope'])
        # the builder's Preview tab can show the new assignment without a reload
        self.assertEqual(data['preview_url'], reverse('perform_qa_preview', kwargs={'pk': utc.pk}))
        # the label matches the change form's Editing dropdown option
        direct, _ = qa_admin.get_testlist_scope_units(self.tl)
        self.assertEqual(direct[0]['label'], data['label'])
        # and it's in the admin history like an assignment made on the admin page
        from django.contrib.admin.models import ADDITION, LogEntry
        self.assertTrue(LogEntry.objects.filter(object_id=str(utc.pk), action_flag=ADDITION).exists())

    def test_post_ad_hoc_inactive(self):
        resp = self._post(frequency='', active='')
        self.assertEqual(resp.status_code, 200)
        utc = qa_models.UnitTestCollection.objects.get()
        self.assertIsNone(utc.frequency)
        self.assertFalse(utc.active)
        self.assertEqual(resp.json()['label'], 'Linac 1 (Ad Hoc)')

    def test_post_ignores_posted_test_collection(self):
        other = qa_utils.create_test_list(name='Other List')
        resp = self._post(object_id=other.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(qa_models.UnitTestCollection.objects.get().object_id, self.tl.pk)

    def test_post_duplicate_returns_422(self):
        self.assertEqual(self._post().status_code, 200)
        resp = self._post()
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'id="tl-assign-modal"', status_code=422)
        self.assertContains(resp, 'already assigned to this unit at this frequency', status_code=422)
        self.assertEqual(qa_models.UnitTestCollection.objects.count(), 1)

    def test_post_missing_required_returns_422(self):
        resp = self._post(unit='', assigned_to='', visible_to=[])
        self.assertEqual(resp.status_code, 422)
        self.assertContains(resp, 'tl-assign-error', status_code=422)
        self.assertFalse(qa_models.UnitTestCollection.objects.exists())

    def test_post_inactive_unit_rejected(self):
        resp = self._post(unit=self.inactive_unit.pk)
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(qa_models.UnitTestCollection.objects.exists())

    def _assign_button(self, resp):
        return re.search(r'<button[^>]*id="tl-btn-assign-machine"[^>]*>', resp.content.decode())

    def test_change_form_button(self):
        resp = self.client.get(self.change_url)
        btn = self._assign_button(resp)
        self.assertIsNotNone(btn)
        self.assertIn('type="button"', btn.group(0))
        self.assertIn('data-assign-url="%s?test_list=%s"' % (self.url, self.tl.pk), btn.group(0))
        self.assertNotIn('disabled', btn.group(0))
        self.assertNotContains(resp, 'qa/unittestcollection/add/?test_list=')

    def test_add_form_button_disabled(self):
        resp = self.client.get(reverse('admin:qa_testlist_add'))
        btn = self._assign_button(resp)
        self.assertIsNotNone(btn)
        self.assertIn('disabled', btn.group(0))
        self.assertIn('aria-disabled="true"', btn.group(0))
        self.assertIn('title="Save the test list first, then assign it to machines."', btn.group(0))
        self.assertNotIn('data-assign-url', btn.group(0))
        self.assertNotIn('style=', btn.group(0))

    def test_change_form_button_hidden_without_permission(self):
        self._limited_user(can_assign=False)
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="tl-btn-assign-machine"')


class TestTestListBuilderWordingAndAccessibility(TestCase):
    """Builder wording (translated, Title Case buttons, "…" not "...") and
    accessible names on icon-only buttons and dialogs."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.test = qa_utils.create_test(name='Output Constancy 6X')
        self.tl = qa_utils.create_test_list(name='Daily QC')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.test)
        self.child = qa_utils.create_test_list(name='Imaging Checks')
        qa_utils.create_test_list_membership(test_list=self.child, test=qa_utils.create_test(name='kV/MV Coincidence'))
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=self.child)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _change_form(self):
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _tag(self, content, pattern):
        match = re.search(pattern, content)
        self.assertIsNotNone(match, pattern)
        return match.group(0)

    def test_row_action_buttons_have_title_and_aria_label(self):
        content = self._change_form()
        edit = self._tag(content, r'<a href="[^"]*" target="_blank" class="tl-action-icon"[^>]*>')
        self.assertIn('title="Edit Test in a New Tab"', edit)
        self.assertIn('aria-label="Edit Output Constancy 6X (opens in a new tab)"', edit)
        dup = self._tag(content, r'<button type="button" class="tl-action-icon tl-duplicate-test-btn"[^>]*>')
        self.assertIn('title="Duplicate Test"', dup)
        self.assertIn('aria-label="Duplicate Output Constancy 6X"', dup)
        remove = self._tag(content, r'<button type="button" class="tl-action-icon tl-delete-test-btn"[^>]*>')
        self.assertIn('title="Remove Test"', remove)
        self.assertIn('aria-label="Remove Output Constancy 6X from this test list"', remove)

    def test_sublist_toggle_and_remove(self):
        content = self._change_form()
        toggle = self._tag(content, r'<button type="button" class="tl-sublist-toggle-btn"[^>]*>')
        self.assertIn('aria-expanded="false"', toggle)
        self.assertIn('aria-label="Show or hide the tests in Imaging Checks"', toggle)
        self.assertIn('title="Show or Hide Tests"', toggle)
        remove = self._tag(content, r'<button type="button" class="tl-btn-sublist tl-btn-remove-sublist"[^>]*>\s*<i[^>]*>')
        self.assertIn('fa-trash-o', remove)
        self.assertNotIn('fa-times', remove)
        self.assertIn('<span class="tl-sublist-badge">Sublist</span>', content)
        self.assertIn('<span class="tl-sublist-count">1 test</span>', content)

    def test_no_capitalised_or_three_dot_strings(self):
        # base_site.html's admin-wide double-submit guard ("Submitting...") isn't part of the builder
        content = self._change_form().replace('"Submitting..."', '')
        self.assertNotIn('...', content)
        for old in ('TEST / SUBLIST', '>TEST<', '>CATEGORY<', '>TYPE<', '>SUBLIST<', '>INPUT<'):
            self.assertNotIn(old, content)
        self.assertIn('>Test / Sublist</th>', content)
        self.assertIn('>Expand All<', content)
        self.assertIn('Browse…', content)
        self.assertIn('Search name, slug, description or sublist…', content)
        self.assertNotIn('slug or tags', content)

    def test_js_strings_translated_at_render(self):
        content = self._change_form()
        # TL_STRINGS is filled in by the template engine: no template syntax is left behind
        self.assertIn('"Select Test to Add": "Select Test to Add"', content)
        self.assertIn('"Create & Add Test": "Create \\u0026 Add Test"', content)
        # placeholders keep a single % (interpolate() needs %(name)s)
        self.assertIn('"%(size)s KB": "%(size)s KB"', content)
        self.assertIn('"Preview %(name)s": "Preview %(name)s"', content)
        self.assertNotIn('%%', content)
        self.assertNotIn("{{ _(", content)

    def test_dialogs_are_labelled(self):
        content = self._change_form()
        search = self._tag(content, r'<div class="tl-modal-dialog tl-search-dialog"[^>]*>')
        for attr in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="tl-search-modal-title"'):
            self.assertIn(attr, search)
        close = self._tag(content, r'<button type="button" class="tl-modal-close-btn" data-search-close[^>]*>')
        self.assertIn('aria-label="Close"', close)
        self.assertIn('title="Close"', close)

        dup = self.client.get(reverse('admin:qa_testlist_duplicate_test'), {'test_id': self.test.pk}).content.decode()
        dialog = self._tag(dup, r'<div class="tl-modal-dialog tl-duplicate-modal"[^>]*>')
        self.assertIn('role="dialog"', dialog)
        self.assertIn('aria-labelledby="tl-duplicate-title"', dialog)
        self.assertIn('id="tl-duplicate-title"', dup)

        desc = self.client.get(
            reverse('admin:qa_testlist_test_desc_modal'), {'test_id': self.test.pk, 'index': 0},
        ).content.decode()
        dialog = self._tag(desc, r'<div class="tl-modal-dialog"[^>]*>')
        self.assertIn('role="dialog"', dialog)
        self.assertIn('aria-labelledby="tl-desc-title"', dialog)

    def test_changelist_icons_have_accessible_names(self):
        unit = qa_utils.create_unit(name='Linac 1')
        qa_utils.create_unit_test_collection(unit=unit, test_collection=self.tl)
        ma = qa_admin.TestListAdmin(qa_models.TestList, AdminSite())
        obj = ma.get_queryset(RequestFactory().get('/')).get(pk=self.tl.pk)
        edit = ma.col_edit(obj)
        self.assertIn('title="Edit Daily QC"', edit)
        self.assertIn('aria-label="Edit Daily QC"', edit)
        self.assertIn('aria-hidden="true"', edit)
        units = ma.col_units(obj)
        self.assertIn('title="Assigned to: Linac 1"', units)
        self.assertIn('<span class="tl-visually-hidden"> (Assigned to: Linac 1)</span>', units)

    def test_metadata_labels(self):
        meta = qa_admin.get_test_metadata(self.test)
        self.assertEqual((meta['type_badge'], meta['type_label']), ('Num', 'Numerical'))
        boolean = qa_utils.create_test(name='Door Interlock', test_type=qa_models.BOOLEAN)
        meta = qa_admin.get_test_metadata(boolean)
        self.assertEqual((meta['type_badge'], meta['type_label']), ('Y/N', 'Boolean'))

    def test_duplicate_name_taken_error_is_plain_text(self):
        resp = self.client.post(reverse('admin:qa_testlist_duplicate_test'), {
            'source_test_id': self.test.pk, 'new_name': 'Output Constancy 6X',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp['Content-Type'].startswith('text/plain'))
        self.assertEqual(
            resp.content.decode(),
            'A test named “Output Constancy 6X” already exists. Choose a different name. No test was created.',
        )


class TestTestListBuilderDialogsOutsideForm(TestCase):
    """The Duplicate Test and Description dialogs have forms of their own. Inside the
    change form the browser would drop them, so their buttons saved the whole test
    list; they (and the search dialog) must be rendered after the change form."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        self.test = qa_utils.create_test(name='Output Constancy 6X')
        self.test.description = 'Measure output'
        self.test.save()
        self.tl = qa_utils.create_test_list(name='Daily QC')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.test)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _change_form(self):
        resp = self.client.get(self.change_url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_dialog_containers_after_main_form(self):
        content = self._change_form()
        main = re.search(r'<form [^>]*method="post"[^>]*_form"', content)
        self.assertIsNotNone(main)
        main_close = content.index('</form>', main.end())
        # the first </form> after the change form opens is its own: nothing nested closed it early
        self.assertGreater(main_close, content.index('id="tl-tests-card"'))
        self.assertGreater(main_close, content.index('id="tl-attachments-card"'))
        inside = content[main.end():main_close]
        self.assertNotIn('<form', inside)
        self.assertNotIn('id="tl-modal-container"', inside)
        self.assertNotIn('id="tl-search-modal"', inside)
        self.assertNotIn('id="tl-search-input"', inside)
        self.assertGreater(content.index('id="tl-modal-container"'), main_close)
        self.assertGreater(content.index('id="tl-search-modal"'), main_close)
        self.assertEqual(content.count('id="tl-modal-container"'), 1)
        self.assertEqual(content.count('id="tl-search-modal"'), 1)

    def test_dialog_forms_are_standalone(self):
        dup = self.client.get(reverse('admin:qa_testlist_duplicate_test'), {'test_id': self.test.pk}).content.decode()
        self.assertIn('<form id="tl-duplicate-test-form"', dup)
        desc = self.client.get(
            reverse('admin:qa_testlist_test_desc_modal'), {'test_id': self.test.pk, 'index': 0},
        ).content.decode()
        self.assertIn('hx-target="#tl-desc-wrap-%s-0"' % self.test.pk, desc)
        self.assertIn('id="tl-desc-error-msg"', desc)

    def test_duplicate_and_description_leave_test_list_alone(self):
        before = qa_models.TestList.objects.get(pk=self.tl.pk)
        resp = self.client.post(reverse('admin:qa_testlist_duplicate_test'), {
            'source_test_id': self.test.pk, 'new_name': 'Output Constancy 6X (Copy)', 'test_list_id': self.tl.pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(qa_models.Test.objects.filter(name='Output Constancy 6X (Copy)').exists())
        url = reverse('admin:qa_testlist_test_desc_modal') + '?test_id=%s&index=0' % self.test.pk
        resp = self.client.post(url, {'description': 'New words'})
        self.assertEqual(resp.status_code, 200)
        self.test.refresh_from_db()
        self.assertEqual(self.test.description, 'New words')
        after = qa_models.TestList.objects.get(pk=self.tl.pk)
        self.assertEqual(after.modified, before.modified)
        self.assertEqual(list(after.tests.all()), [self.test])

    def test_description_cell_is_a_button(self):
        content = self._change_form()
        match = re.search(r'<button type="button" class="tl-test-desc"[^>]*>', content)
        self.assertIsNotNone(match)
        self.assertIn('hx-target="#tl-modal-container"', match.group(0))
        self.assertNotIn('<div class="tl-test-desc"', content)

    def test_browse_is_a_keyboard_button(self):
        content = self._change_form()
        match = re.search(r'<button type="button" class="[^"]*tl-browse-btn"[^>]*>', content)
        self.assertIsNotNone(match)
        self.assertIn('id="tl-browse-btn"', match.group(0))
        file_input = re.search(r'<input type="file" id="id_tl-new-attachments"[^>]*>', content)
        self.assertIsNotNone(file_input)
        self.assertIn('tabindex="-1"', file_input.group(0))
        self.assertNotIn('<label class="btn btn-default btn-sm btn-flat tl-browse-btn"', content)


class TestTestListBuilderDesignSpec(TestCase):
    """The builder follows the QATrack+ design spec: one neutral style for every
    category and test type (colour means QC status), literal values instead of
    custom --tl-* properties, whole-pixel type, no pill radii, no page-wide
    overrides of shared classes, and tlb- names where base.css has a tl- block."""

    def setUp(self):
        self.user = create_user(is_superuser=True, uname='user', pwd='pwd')
        self.client.login(username='user', password='pwd')
        safety = qa_utils.create_category(name='Safety', slug='safety', description='Safety')
        self.interlock = qa_utils.create_test(name='Door Interlock', test_type=qa_models.BOOLEAN, category=safety)
        self.output = qa_utils.create_test(name='Output Constancy 6X')
        self.tl = qa_utils.create_test_list(name='Daily QC')
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.interlock)
        qa_utils.create_test_list_membership(test_list=self.tl, test=self.output)
        child = qa_utils.create_test_list(name='Imaging Checks')
        qa_utils.create_test_list_membership(test_list=child, test=qa_utils.create_test(name='Image Upload'))
        qa_utils.create_sublist(parent_test_list=self.tl, child_test_list=child)
        self.change_url = reverse('admin:qa_testlist_change', args=(self.tl.pk,))

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _source(self):
        origin = get_template('admin/qa/testlist/testlist_assets.html').origin
        with open(origin.name, encoding='utf-8') as f:
            return f.read()

    def test_no_custom_tl_properties_rendered(self):
        for url in (self.change_url, reverse('admin:qa_testlist_changelist')):
            content = self._get(url)
            self.assertNotIn('--tl-', content, url)
            # the pinned-header height set by base_site.html is still used
            self.assertIn('--qa-admin-top-h', content, url)

    def test_categories_and_types_are_neutral(self):
        content = self._get(self.change_url)
        self.assertIn('<span class="tl-cat-pill">Safety</span>', content)
        self.assertNotRegex(content, r'tl-cat-(?!pill)[a-z]')
        self.assertNotRegex(content, r'tl-type-(num|yn|mc|comp|const|str|scomp|upload|date|default)\b')
        self.assertIn('<span class="tl-type-badge">', content)

    def test_metadata_has_no_colour_classes(self):
        meta = qa_admin.get_test_metadata(self.interlock)
        self.assertNotIn('category_class', meta)
        self.assertNotIn('type_class', meta)
        self.assertEqual(meta['category_name'], 'Safety')

    def test_builder_classes_do_not_clash_with_base_css(self):
        content = self._get(self.change_url)
        self.assertIn('<table class="tlb-table tl-tests-table" id="tl-tests-table">', content)
        self.assertIn('<table class="tlb-table tl-sublist-table">', content)
        self.assertIn('<div class="tlb-form">', content)
        self.assertIn('<div class="tlb-field tl-col-1">', content)
        for name in ('tl-table', 'tl-form', 'tl-field'):
            self.assertNotRegex(content, r'class="(?:[^"]* )?%s(?:[ "])' % name)
            self.assertNotRegex(content, r'\.%s(?![\w-])' % name)

    def test_assets_source_shapes_and_sizes(self):
        source = self._source()
        self.assertNotIn('9999px', source)
        self.assertNotIn('1.5px', source)
        self.assertNotRegex(source, r'font-size:\s*\d+\.\d+px')
        self.assertNotRegex(source, r'--tl-')

    def test_no_page_wide_overrides_of_shared_classes(self):
        source = self._source()
        style = source[source.index('<style>'):source.index('</style>')]
        self.assertNotRegex(
            style, r'(?m)^\s*\.(text-success|text-info|text-muted|btn-xs|btn-danger|btn-default|margin-right-5)\b',
        )
        content = self._get(self.change_url)
        self.assertNotIn('btn-xs', content)
        self.assertNotIn('margin-right-5', content)
