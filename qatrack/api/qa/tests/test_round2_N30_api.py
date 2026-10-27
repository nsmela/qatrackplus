import re

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from qatrack.api.qa import filters as api_filters
from qatrack.api.qa import serializers as api_serializers
from qatrack.qa import models
from qatrack.qa.tests import utils


class TestChoicesLabelInAPI(APITestCase):
    """The API labels Test.choices "Choices", not a second "Description".

    The model field's verbose_name is still "Description" until the metadata
    migration lands, so the serializer and the filterset label it themselves.
    """

    def setUp(self):
        self.user = utils.create_user(is_superuser=True)
        self.client.force_authenticate(user=self.user)

    def test_serializer_labels(self):
        # TestViewSet is read-only today, so no form/OPTIONS shows these yet; this keeps the
        # label right if the endpoint ever becomes writable.
        fields = api_serializers.TestSerializer().fields
        assert fields['choices'].label == 'Choices'
        assert fields['description'].label == 'Description'

    def label_for(self, html, field):
        match = re.search(r'<label[^>]*for="id_%s"[^>]*>(.*?)</label>' % field, html, re.S)
        assert match, 'no label for %s' % field
        return match.group(1).strip()

    def test_browsable_api_filter_form(self):
        resp = self.client.get(reverse('test-list'), HTTP_ACCEPT='text/html')
        assert resp.status_code == status.HTTP_200_OK
        html = resp.content.decode()
        assert self.label_for(html, 'choices__icontains') == 'Choices contains:'
        assert self.label_for(html, 'choices__in') == 'Choices is in:'
        assert self.label_for(html, 'description__icontains') == 'Description contains:'

    def test_filter_labels(self):
        fs = api_filters.TestFilter.disable_subset(depth=1)(queryset=models.Test.objects.all())
        fields = fs.form.fields
        assert fields['choices__icontains'].label == 'Choices contains'
        assert fields['choices__in'].label == 'Choices is in'
        assert fields['description__icontains'].label == 'Description contains'

    def test_choices_filter_still_filters(self):
        mc = utils.create_test(name='mc', test_type=models.MULTIPLE_CHOICE, choices='apple,pear')
        utils.create_test(name='other')
        resp = self.client.get(reverse('test-list'), {'choices__icontains': 'pear'})
        assert [t['name'] for t in resp.data['results']] == [mc.name]
