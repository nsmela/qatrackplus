from qatrack.issue_tracker import models
from qatrack.qatrack_core.forms import BetterModelForm


class IssueForm(BetterModelForm):

    class Meta:
        model = models.Issue
        fields = [
            'issue_type', 'issue_priority', 'issue_tags', 'description', 'error_screen',
            'test_list_instances', 'service_events', 'fault_logs',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['issue_type'].label = 'Type'
        self.fields['issue_priority'].label = 'Priority'
        self.fields['error_screen'].label = 'Error Screen Details'
        self.fields['test_list_instances'].label = 'QA Submissions'
        self.fields['service_events'].label = 'Service Events'
        self.fields['fault_logs'].label = 'Fault Logs'

        for f in self.fields:
            self.fields[f].widget.attrs['class'] = 'form-control'

        for f in ['description', 'error_screen']:
            self.fields[f].widget.attrs['class'] += ' autosize'
            self.fields[f].widget.attrs['rows'] = 8
            self.fields[f].widget.attrs['cols'] = 8

        for f in ['test_list_instances', 'service_events', 'fault_logs']:
            self.fields[f].widget.attrs['class'] += ' select2'
            self.fields[f].required = False
