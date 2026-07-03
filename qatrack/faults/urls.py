from django.urls import re_path as url

from qatrack.faults import views

urlpatterns = [
    url(r'^$', views.FaultList.as_view(), name='fault_list'),
    url(r'^unreviewed/$', views.UnreviewedFaultList.as_view(), name='fault_list_unreviewed'),
    url(r'^choose-unit/$', views.ChooseUnitForViewFaults.as_view(), name="fault_choose_unit"),
    url(r'^unit/(?P<unit_number>[/\d]+)/$', views.FaultsByUnit.as_view(), name='fault_list_by_unit'),
    url(
        r'^unit/(?P<unit_number>[/\d]+)/type/(?P<slug>[\w-]+)/$',
        views.FaultsByUnitFaultType.as_view(),
        name='fault_list_by_unit_type',
    ),
    url(r'^(?P<pk>\d+)?/$', views.FaultDetails.as_view(), name='fault_details'),
    url(r'^(?P<pk>\d+)/section/(?P<section>[\w-]+)/edit/$', views.FaultSectionEdit.as_view(), name='fault_section_edit'),
    url(r'^(?P<pk>\d+)/section/(?P<section>[\w-]+)/$', views.FaultSectionDetail.as_view(), name='fault_section_detail'),
    url(r'^delete/(?P<pk>\d+)?/$', views.DeleteFault.as_view(), name='fault_delete'),
    url(r'^type/$', views.FaultTypeList.as_view(), name='fault_type_list'),
    url(r'^type/autocomplete.json$', views.fault_type_autocomplete, name="fault_type_autocomplete"),
    url(r'^type/(?P<slug>[\w-]+)/$', views.FaultTypeDetails.as_view(), name='fault_type_details'),
    url(r'^review/(?P<pk>\d+)/$', views.review_fault, name='fault_review'),
    url(r'^review/$', views.bulk_review, name='fault_bulk_review'),
    url(r'^type/(?P<slug>[\w-]+)/edit-description/$', views.edit_fault_type_description, name='fault_type_edit_description'),
    url(r'^create/$', views.CreateFault.as_view(), name='fault_create'),
    url(r'^create/ajax/$', views.fault_create_ajax, name='fault_create_ajax'),
    url(r'^edit/(?P<pk>\d+)?/$', views.EditFault.as_view(), name='fault_edit'),
]
