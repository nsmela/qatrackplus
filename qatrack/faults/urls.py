from django.urls import path, re_path

from qatrack.faults import views

urlpatterns = [
    path('', views.FaultList.as_view(), name='fault_list'),
    path('unreviewed/', views.UnreviewedFaultList.as_view(), name='fault_list_unreviewed'),
    path('choose-unit/', views.ChooseUnitForViewFaults.as_view(), name="fault_choose_unit"),
    re_path(r'^unit/(?P<unit_number>[/\d]+)/$', views.FaultsByUnit.as_view(), name='fault_list_by_unit'),
    re_path(
        r'^unit/(?P<unit_number>[/\d]+)/type/(?P<slug>[\w-]+)/$',
        views.FaultsByUnitFaultType.as_view(),
        name='fault_list_by_unit_type',
    ),
    re_path(r'^(?P<pk>\d+)?/$', views.FaultDetails.as_view(), name='fault_details'),
    re_path(r'^delete/(?P<pk>\d+)?/$', views.DeleteFault.as_view(), name='fault_delete'),
    path('type/', views.FaultTypeList.as_view(), name='fault_type_list'),
    re_path(r'^type/autocomplete.json$', views.fault_type_autocomplete, name="fault_type_autocomplete"),
    re_path(r'^type/(?P<slug>[\w-]+)/$', views.FaultTypeDetails.as_view(), name='fault_type_details'),
    path('review/<int:pk>/', views.review_fault, name='fault_review'),
    path('review/', views.bulk_review, name='fault_bulk_review'),
    path('create/', views.CreateFault.as_view(), name='fault_create'),
    path('create/ajax/', views.fault_create_ajax, name='fault_create_ajax'),
    re_path(r'^edit/(?P<pk>\d+)?/$', views.EditFault.as_view(), name='fault_edit'),
]
