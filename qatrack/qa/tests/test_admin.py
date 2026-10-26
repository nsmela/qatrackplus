import json
import re

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import constants, get_messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.forms import HiddenInput, inlineformset_factory, modelform_factory
from django.http import QueryDict
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
        assert any("the maximum number allowed is 0" in err for err in form.errors['__all__'])

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
        self.assertContains(resp, 'is standalone')

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
        self.assertNotContains(resp, 'tl-th-ref')
        self.assertNotContains(resp, 'tl-th-tol')
        self.assertNotContains(resp, 'Pass = ')
        self.assertContains(resp, 'data-type-value="22.0"')
        self.assertContains(resp, '<span class="tl-type-value">22.0</span>', html=True)
        self.assertContains(resp, '<span class="tl-type-value">a, b</span>', html=True)
        self.assertContains(resp, '<span class="tl-type-value-none">None</span>', html=True)
        # the sublist row spans the whole main table (drag, test, category, type, type value, actions)
        thead = content.split('id="tl-tests-table"')[1].split('</thead>')[0]
        main_cols = len(re.findall(r'<th\b', thead))
        self.assertEqual(main_cols, 6)
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
