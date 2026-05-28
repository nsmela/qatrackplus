from django.urls import include, path
from rest_framework import routers

from qatrack.api.attachments import views

router = routers.DefaultRouter()
router.register(r'attachments', views.AttachmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
