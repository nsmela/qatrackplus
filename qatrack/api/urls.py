from django.urls import include, path, re_path
from rest_framework.authtoken import views as auth_views
from rest_framework.schemas import get_schema_view

from qatrack.api import views

schema_view = get_schema_view(title='QATrack+ API')


urlpatterns = [
    path('', views.all_api_roots, name="api-root"),
    re_path(r'^get-token/', auth_views.obtain_auth_token, name="get-token"),
    #    url(r'^authorize/', include('rest_framework.urls', namespace='rest_framework')),
    path('attachments/', include('qatrack.api.attachments.urls')),
    path('auth/', include('qatrack.api.auth.urls')),
    path('comments/', include('qatrack.api.comments.urls')),
    path('contenttypes/', include('qatrack.api.contenttypes.urls')),
    path('faults/', include('qatrack.api.faults.urls')),
    path('parts/', include('qatrack.api.parts.urls')),
    path('qa/', include('qatrack.api.qa.urls')),
    path('qc/', include('qatrack.api.qa.urls')),
    path('servicelog/', include('qatrack.api.service_log.urls')),
    path('units/', include('qatrack.api.units.urls')),
    path('schema/', schema_view),
]
