from django.urls import path, re_path

import qatrack.qa.views.admin

from .views import admin, base, charts, perform, review

urlpatterns = [
    # CUSTOM ADMIN PAGES
    # Copy references and tolerances between testlists
    path(
        'admin/copy_refs_and_tols/',
        admin.CopyReferencesAndTolerances(admin.CopyReferencesAndTolerancesForm),
        name="qa_copy_refs_and_tols"
    ),
    re_path(
        r'^admin/copy_refs_and_tols/gettestlists/(?P<source_unit>[:|\w]+)/(?P<content_type>[:|\w]+)/$',
        qatrack.qa.views.admin.testlist_json,
        name='qa_copy_refs_and_tols_testlist_json'
    ),
    path('admin/export_testpack/', admin.ExportTestPack.as_view(), name="qa_export_testpack"),
    path('admin/import_testpack/', admin.ImportTestPack.as_view(), name="qa_import_testpack"),
    path('admin/recurrences/', admin.recurrence_examples, name="qa_recurrences"),
    path("", base.UTCList.as_view(), name="all_lists"),

    # view for composite calculations via ajax
    path("composite/", perform.CompositeCalculation.as_view(), name="composite"),
    path("autosave/", perform.autosave, name="autosave"),
    path("autosave/load/", perform.autosave_load, name="autosave_load"),

    # view for uploads via ajax
    path("upload/", perform.Upload.as_view(), name="upload"),
    path("charts/", charts.ChartView.as_view(), name="charts"),
    path("charts/export/csv/", charts.ExportCSVView.as_view(), name="charts_export_csv"),
    path("charts/data/", charts.BasicChartData.as_view(), name="chart_data"),
    re_path(r"^charts/control_chart.png$", charts.ControlChartImage.as_view(), name="control_chart"),
    path("charts/data/testlists/", charts.get_test_lists_for_unit_frequencies, name="charts_testlists"),
    path("charts/data/tests/", charts.get_tests_for_test_lists, name="charts_tests"),

    # overall program status
    path("review/", review.Overview.as_view(), name="overview"),
    path("review/overview-user/", review.Overview.as_view(), name="overview_user"),
    path("review/overview-objects/", review.OverviewObjects.as_view(), name="overview_objects"),
    path("review/due-dates/", review.DueDateOverview.as_view(), name="overview_due_dates"),
    path("review/due-dates-user/", review.DueDateOverviewUser.as_view(), name="overview_due_dates_user"),

    # review utc's
    path("review/all/", review.UTCReview.as_view(), name="review_all"),
    path("review/yourall/", review.UTCYourReview.as_view(), name="review_your_all"),
    path("review/utc/<int:pk>/", review.UTCInstances.as_view(), name="review_utc"),
    path("review/frequency/", review.ChooseFrequencyForReview.as_view(), name="choose_review_frequency"),
    re_path(
        r"^review/frequency/(?P<frequency>[/\w-]+?)/$", review.UTCFrequencyReview.as_view(), name="review_by_frequency"
    ),
    path("review/unit/", review.ChooseUnitForReview.as_view(), name="choose_review_unit"),
    re_path(r"^review/unit/(?P<unit_number>[/\d]+)/$", review.UTCUnitReview.as_view(), name="review_by_unit"),
    path("review/inactive/", review.InactiveReview.as_view(), name="review_inactive"),
    path("review/yourinactive/", review.YourInactiveReview.as_view(), name="review_your_inactive"),

    # test list instances
    path("session/details/", base.TestListInstances.as_view(), name="complete_instances"),
    re_path(
        r"^session/details(?:/(?P<pk>\d+))?/report/$",
        review.test_list_instance_report,
        name="test_list_instance_report"
    ),
    re_path(
        r"^session/details(?:/(?P<pk>\d+))?/$",
        review.TestListInstanceDetails.as_view(),
        name="view_test_list_instance"
    ),
    re_path(
        r"^session/delete(?:/(?P<pk>\d+))?/$",
        review.TestListInstanceDelete.as_view(),
        name="delete_test_list_instance"
    ),
    path("session/review/", review.Unreviewed.as_view(), name="unreviewed-alt"),
    re_path(
        r"^session/review(?:(?:/(?P<rtsqa_form>[a-zA-Z0-9-_]+))?(?:/(?P<pk>\d+)))?/$",
        review.ReviewTestListInstance.as_view(),
        name="review_test_list_instance"
    ),
    path("session/review/bulk/", review.bulk_review, name="qa-bulk-review"),
    path("session/unreviewed/", review.Unreviewed.as_view(), name="unreviewed"),
    path("session/unreviewed/visible/", review.UnreviewedVisibleTo.as_view(), name="unreviewed_visible_to"),
    path("session/group/", review.ChooseGroupVisibleTo.as_view(), name="choose_group_visible"),
    re_path(
        r"^session/unreviewedbygroup/(?P<group>[/\d]+)/$",
        review.UnreviewedByVisibleToGroup.as_view(),
        name="unreviewed_by_group"
    ),
    path("session/in-progress/", perform.InProgress.as_view(), name="in_progress"),
    path("session/continue/<int:pk>/", perform.ContinueTestListInstance.as_view(), name="continue_tli"),
    path("session/edit/<int:pk>/", perform.EditTestListInstance.as_view(), name="edit_tli"),
    path("unit/", perform.ChooseUnit.as_view(), name="choose_unit"),
    re_path(r"^utc/perform(?:/(?P<pk>\d+))?/$", perform.PerformQA.as_view(), name="perform_qa"),
    re_path(r"^site/(?P<site>[/\w-]+?)/$", perform.SiteList.as_view(), name="qa_by_site"),
    re_path(
        r"^unit/(?P<unit_number>[/\d]+)/frequency/(?P<frequency>[/\w-]+?)/$",
        perform.UnitFrequencyList.as_view(),
        name="qa_by_frequency_unit"
    ),
    re_path(r"^unit/(?P<unit_number>[/\d]+)/$", perform.UnitList.as_view(), name="qa_by_unit"),
    re_path(
        r"^frequency/(?P<frequency>[/\w-]+)/unit/(?P<unit_number>[/\d]+)/$",
        perform.UnitFrequencyList.as_view(),
        name="qa_by_unit_frequency"
    ),
    re_path(r"^frequency/(?P<frequency>[/\w-]+?)/$", perform.FrequencyList.as_view(), name="qa_by_frequency"),
    path("tree/category/", perform.CategoryTree.as_view(), name="qa_category_tree"),
    path("tree/frequency/", perform.FrequencyTree.as_view(), name="qa_frequency_tree"),
    re_path(
        r"^category/(?P<category>[/\w-]+)/unit/(?P<unit_number>[/\d]+)/$",
        perform.UnitCategoryList.as_view(),
        name="qa_by_unit_category"
    ),
    re_path(r"^category/(?P<category>[/\w-]+?)/$", perform.CategoryList.as_view(), name="qa_by_category"),
    path("due-and-overdue/", perform.DueAndOverdue.as_view(), name="qa_by_overdue"),
]
