from django.urls import path

from qatrack.qatrack_core import views

urlpatterns = [
    path("comment/ajax_comment/", views.ajax_comment, name='ajax_comment'),
]
