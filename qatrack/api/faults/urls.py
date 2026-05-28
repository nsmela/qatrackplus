from django.urls import include, path
from rest_framework import routers

from qatrack.api.faults import views

router = routers.DefaultRouter()
router.register(r'faults', views.FaultViewSet)
router.register(r'faulttypes', views.FaultTypeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
