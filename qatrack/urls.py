from django.conf import settings
from django.urls import include, path, re_path
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import path
from django.views.generic.base import RedirectView
from django.views.i18n import JavaScriptCatalog

from qatrack.qatrack_core import views

admin.autodiscover()


favicon_view = RedirectView.as_view(url=static_url("qatrack_core/img/favicon.ico"), permanent=True)
touch_view = RedirectView.as_view(url=static_url("qatrack_core/img/apple-touch-icon.png"), permanent=True)


class QAToQC(RedirectView):

    permanent = True
    query_string = True

    def get_redirect_url(self, *args, **kwargs):
        return "%s/qc/%s" % (settings.FORCE_SCRIPT_NAME or "", kwargs['terms'])


urlpatterns = [
    path('', views.homepage, name="home"),
    path('400/', views.handle_400, name="400"),
    path('403/', views.handle_403, name="403"),
    path('404/', views.handle_404, name="404"),
    path('500/', views.handle_500, name="500"),
    path('accounts/', include('qatrack.accounts.urls')),
    re_path(r'^qa/(?P<terms>.*)$', QAToQC.as_view()),
    path('qc/', include('qatrack.qa.urls')),
    path('reports/', include('qatrack.reports.urls')),
    path('units/', include('qatrack.units.urls')),
    path('core/', include('qatrack.qatrack_core.urls')),
    path('servicelog/', include('qatrack.service_log.urls')),
    path('parts/', include('qatrack.parts.urls')),
    path('faults/', include('qatrack.faults.urls')),
    path('issues/', include('qatrack.issue_tracker.urls')),

    # Uncomment the next line to enable the admin:
    path(r'admin/', admin.site.urls),
    re_path(r'^favicon\.ico$', favicon_view),
    re_path(r'^apple-touch-icon\.png$', touch_view),

    # third party
    path('', include('genericdropdown.urls')),
    path('comments/', include('django_comments.urls')),
    path('admin/dynamic_raw_id/', include('dynamic_raw_id.urls')),
    path('api/', include('qatrack.api.urls')),
]

js_info_dict = {
    'packages': ('recurrence', ),
}
urlpatterns += [path('jsi18n/', JavaScriptCatalog.as_view(), js_info_dict)]

if settings.USE_SQL_REPORTS:
    urlpatterns.append(path('sql-reports/', include('explorer.urls')),)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# error handling views
handler400 = 'qatrack.qatrack_core.views.handle_400'
handler403 = 'qatrack.qatrack_core.views.handle_403'
handler404 = 'qatrack.qatrack_core.views.handle_404'
handler500 = 'qatrack.qatrack_core.views.handle_500'

if settings.DEBUG:  # pragma: nocover
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
