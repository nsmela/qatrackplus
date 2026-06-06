from django import forms

from qatrack.faults import models as fault_models
from qatrack.issue_tracker import models
from qatrack.qa import models as qa_models
from qatrack.qatrack_core.forms import BetterModelForm
from qatrack.service_log import models as sl_models


class IssueForm(BetterModelForm):

    class Meta:
        model = models.Issue
        fields = ['issue_type', 'issue_priority', 'issue_tags', 'description', 'qa_logs', 'service_events', 'fault_logs']
        fieldsets = [
            ('hidden_fields', {
                'fields': [],
            }),
            ('required_fields', {
                'fields': ['issue_type', 'issue_priority', 'issue_tags', 'description'],
            }),
            ('optional_fields', {
                'fields': ['qa_logs', 'service_events', 'fault_logs']
            })
        ]

    qa_logs = forms.ModelMultipleChoiceField(
        queryset=qa_models.TestListInstance.objects.none(),
        required=False,
    )
    service_events = forms.ModelMultipleChoiceField(
        queryset=sl_models.ServiceEvent.objects.none(),
        required=False,
    )
    fault_logs = forms.ModelMultipleChoiceField(
        queryset=fault_models.Fault.objects.none(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields['qa_logs'].queryset = self.instance.qa_logs.all()
            self.fields['service_events'].queryset = self.instance.service_events.all()
            self.fields['fault_logs'].queryset = self.instance.fault_logs.all()
        else:
            if 'qa_logs' in self.data:
                self.fields['qa_logs'].queryset = qa_models.TestListInstance.objects.filter(
                    pk__in=self.data.getlist('qa_logs')
                )
            if 'service_events' in self.data:
                self.fields['service_events'].queryset = sl_models.ServiceEvent.objects.filter(
                    pk__in=self.data.getlist('service_events')
                )
            if 'fault_logs' in self.data:
                self.fields['fault_logs'].queryset = fault_models.Fault.objects.filter(
                    pk__in=self.data.getlist('fault_logs')
                )

        self.fields['issue_type'].label = 'Type'
        self.fields['issue_priority'].label = 'Priority'

        for f in self.fields:
            self.fields[f].widget.attrs['class'] = 'form-control'

        for f in ['description']:
            self.fields[f].widget.attrs['class'] += ' autosize'
            self.fields[f].widget.attrs['rows'] = 8
            self.fields[f].widget.attrs['cols'] = 8


class IssueUpdateForm(IssueForm):

    class Meta(IssueForm.Meta):
        fields = ['issue_type', 'issue_status', 'issue_priority', 'issue_tags', 'description', 'qa_logs', 'service_events', 'fault_logs']
        fieldsets = [
            ('hidden_fields', {
                'fields': [],
            }),
            ('required_fields', {
                'fields': ['issue_type', 'issue_status', 'issue_priority', 'issue_tags', 'description'],
            }),
            ('optional_fields', {
                'fields': ['qa_logs', 'service_events', 'fault_logs']
            })
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['issue_status'].label = 'Status'
