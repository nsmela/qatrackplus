from django.urls import re_path as url

from qatrack.issue_tracker import views

urlpatterns = [
    url(r'^issue/new/$', views.IssueCreate.as_view(), name='issue_new'),
    url(r'^issue/edit/(?P<pk>\d+)?$', views.IssueUpdate.as_view(), name='issue_update'),
    url(r'^issue/details/(?P<pk>\d+)?$', views.IssueDetails.as_view(), name='issue_details'),
    url(r'^issues/(?:(?P<f>[a-zA-Z0-9_-]+)/)?$', views.IssueList.as_view(), name='issue_list'),
]
