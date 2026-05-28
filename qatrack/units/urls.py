from django.urls import path, re_path

from qatrack.units import views

urlpatterns = [
    re_path(r"^unit_available_time(?:/(?P<pk>\d+))?/$", views.UnitAvailableTimeChange.as_view(), name="unit_available_time"),
    path('handle_unit_available_time/', views.handle_unit_available_time, name='handle_unit_available_time'),
    path('handle_unit_available_time_edit/', views.handle_unit_available_time_edit, name='handle_unit_available_time_edit'),
    path('delete_schedules/', views.delete_schedules, name='delete_schedules'),
    path('get_unit_available_time_data/', views.get_unit_available_time_data, name='get_unit_available_time_data'),
    path('get_unit_info/', views.get_unit_info, name='get_unit_info'),
]
