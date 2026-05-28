from django.urls import path, re_path
from qatrack.issue_tracker import views

urlpatterns = [
    path('issue/new/', views.IssueCreate.as_view(), name='issue_new'),
    re_path(r'^issue/details/(?P<pk>\d+)?$', views.IssueDetails.as_view(), name='issue_details'),
    path('issues/', views.IssueList.as_view(), name='issue_list'),
]
