from django.urls import path, re_path

from qatrack.parts import views

urlpatterns = [
    path('parts_searcher', views.parts_searcher, name='parts_searcher'),
    path('parts_storage_searcher', views.parts_storage_searcher, name='parts_storage_searcher'),
    path('room_location_searcher', views.room_location_searcher, name='room_location_searcher'),
    path('', views.PartsList.as_view(), name='parts_list'),
    path('low-inventory/', views.LowInventoryPartsList.as_view(), name='low_inventory_parts_list'),
    path('new/', views.PartUpdateCreate.as_view(), name='part_new'),
    re_path(r'^edit/(?P<pk>\d+)?/$', views.PartUpdateCreate.as_view(), name='part_edit'),
    re_path(r'^details/(?P<pk>\d+)?/$', views.PartDetails.as_view(), name='part_details'),
    path('suppliers/', views.SuppliersList.as_view(), name='suppliers_list'),
    re_path(r"^suppliers/(?P<pk>[/\d]+)/$", views.SupplierDetails.as_view(), name="supplier_details"),
]
