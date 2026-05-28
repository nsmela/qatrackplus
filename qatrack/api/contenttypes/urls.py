from django.urls import include, path
from rest_framework import routers

from qatrack.api.contenttypes import views

router = routers.DefaultRouter()
router.register(r'contenttypes', views.ContentTypeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
