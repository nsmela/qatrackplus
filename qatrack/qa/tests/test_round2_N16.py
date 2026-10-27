"""Reference/tolerance text on Perform QC, review and backup forms (qa_tags).

The expected HTML below was captured from the tags before they were made
translatable; the only intended differences are ``</br>`` -> ``<br>`` and the
literal ``<``/``>`` in the Action line now being escaped (same visible text).
"""
from unittest import mock

from django.test import TestCase

from qatrack.qa import models
from qatrack.qa.templatetags import qa_tags


def make_tol(**kwargs):
    tol = models.Tolerance(**kwargs)
    tol.name = models.get_tolerance_name(tol)
    return tol


class Fixtures:

    def setUp(self):
        self.num = models.Test(type=models.SIMPLE)
        self.boolean = models.Test(type=models.BOOLEAN)
        self.mc = models.Test(type=models.MULTIPLE_CHOICE, choices="a,b,c")

        self.ref = models.Reference(value=1, type=models.NUMERICAL)
        self.ref_yes = models.Reference(value=1, type=models.BOOLEAN)
        self.ref_no = models.Reference(value=0, type=models.BOOLEAN)

        self.absolute = make_tol(type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        self.absolute_partial = make_tol(type=models.ABSOLUTE, act_low=None, tol_low=-1, tol_high=1.5, act_high=None)
        self.percent = make_tol(type=models.PERCENT, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        self.mult_choice = make_tol(type=models.MULTIPLE_CHOICE, mc_pass_choices="a,b", mc_tol_choices="c")


class TestReferenceToleranceSpan(Fixtures, TestCase):

    def test_absolute(self):
        assert qa_tags.reference_tolerance_span(self.num, self.ref, self.absolute) == (
            '<span> <abbr title="(ACT L, TOL L, TOL H, ACT H) = (-2.000, -1.000, 1.000, 2.000) ">1</abbr></span>'
        )

    def test_absolute_missing_limits(self):
        assert qa_tags.reference_tolerance_span(self.num, self.ref, self.absolute_partial) == (
            '<span> <abbr title="(ACT L, TOL L, TOL H, ACT H) = (--, -1.000, 1.500, --) ">1</abbr></span>'
        )

    def test_percent(self):
        assert qa_tags.reference_tolerance_span(self.num, self.ref, self.percent) == (
            '<span> <abbr title="(ACT L, TOL L, TOL H, ACT H) = (-2.00%, -1.00%, 1.00%, 2.00%) ">1</abbr></span>'
        )

    def test_limits_come_from_type_not_stored_name(self):
        """A name stored in another language (e.g. "Absolut(...)") must not leak into the text."""
        tol = make_tol(type=models.ABSOLUTE, act_low=-2, tol_low=-1, tol_high=1, act_high=2)
        tol.name = "Absolut(-2.000, -1.000, 1.000, 2.000)"
        result = qa_tags.reference_tolerance_span(self.num, self.ref, tol)
        assert "Absolut" not in result
        assert "= (-2.000, -1.000, 1.000, 2.000) " in result

    def test_multiple_choice(self):
        assert qa_tags.reference_tolerance_span(self.mc, None, self.mult_choice) == (
            '<span><abbr title="OK Values: a, b;  Tolerance Values: c; All other choices are failing">'
            '<em>Choice</em></abbr></span>'
        )

    def test_boolean(self):
        assert qa_tags.reference_tolerance_span(self.boolean, self.ref_yes, None) == (
            '<span title="Passing value = Yes">Yes</span>'
        )

    def test_no_ref(self):
        assert qa_tags.reference_tolerance_span(self.num, None, self.absolute) == '<span>No Ref</span>'

    def test_no_tol(self):
        assert qa_tags.reference_tolerance_span(self.num, self.ref, None) == (
            '<span title="No Tolerance Set">1</span>'
        )

    def test_no_tol_no_ref(self):
        assert qa_tags.reference_tolerance_span(self.mc, None, None) == (
            '<span title="No Tolerance Set">No Tol</span>'
        )

    def test_choices_are_escaped(self):
        tol = make_tol(type=models.MULTIPLE_CHOICE, mc_pass_choices='<b>x</b>,"q"', mc_tol_choices="")
        result = qa_tags.reference_tolerance_span(self.mc, None, tol)
        assert "<b>" not in result
        assert "&lt;b&gt;x&lt;/b&gt;, &quot;q&quot;" in result


class TestToleranceForReference(Fixtures, TestCase):

    def test_absolute(self):
        assert qa_tags.tolerance_for_reference(self.absolute, self.ref) == (
            '<span>OK: Between 0 &amp; 2<br> Tolerance Between -1 &amp; 3<br> Action: &lt; -1 or &gt; 3</span>'
        )

    def test_absolute_missing_limits(self):
        assert qa_tags.tolerance_for_reference(self.absolute_partial, self.ref) == (
            '<span>OK: Between 0 &amp; 2.5<br> Tolerance Between - &amp; -<br> Action: &lt; - or &gt; -</span>'
        )

    def test_percent(self):
        assert qa_tags.tolerance_for_reference(self.percent, self.ref) == (
            '<span>OK: Between 0.99 &amp; 1.01<br> Tolerance Between 0.98 &amp; 1.02<br> '
            'Action: &lt; 0.98 or &gt; 1.02</span>'
        )

    def test_multiple_choice(self):
        assert qa_tags.tolerance_for_reference(self.mult_choice, None) == (
            '<span>OK: a, b<br>  Tolerance: c<br> All others fail</span>'
        )

    def test_boolean(self):
        assert qa_tags.tolerance_for_reference(None, self.ref_yes) == '<span>OK: Yes; Action: No</span>'
        assert qa_tags.tolerance_for_reference(None, self.ref_no) == '<span>OK: No; Action: Yes</span>'

    def test_boolean_test_with_numerical_reference(self):
        assert qa_tags.tolerance_for_reference(None, self.ref, self.boolean) == '<span>OK: Yes; Action: No</span>'

    def test_no_tol(self):
        assert qa_tags.tolerance_for_reference(None, self.ref) == '<span><em>N/A</em></span>'

    def test_no_ref(self):
        assert qa_tags.tolerance_for_reference(self.absolute, None) == ''

    def test_no_invalid_br(self):
        for result in (
            qa_tags.tolerance_for_reference(self.absolute, self.ref),
            qa_tags.tolerance_for_reference(self.mult_choice, None),
        ):
            assert "</br>" not in result

    def test_choices_are_escaped(self):
        tol = make_tol(type=models.MULTIPLE_CHOICE, mc_pass_choices="<i>x</i>", mc_tol_choices="")
        result = qa_tags.tolerance_for_reference(tol, None)
        assert "<i>" not in result
        assert "OK: &lt;i&gt;x&lt;/i&gt;" in result


def fake_gettext(message):
    return "<<%s>>" % message


@mock.patch("qatrack.qa.templatetags.qa_tags._", side_effect=fake_gettext)
class TestStringsAreTranslated(Fixtures, TestCase):
    """Every user-facing sentence goes through gettext, one msgid per sentence.

    The fake translation adds ``<<``/``>>``, which also shows the translated text is escaped.
    """

    def msgids(self, gettext):
        return {c.args[0] for c in gettext.call_args_list}

    def test_span_messages(self, gettext):
        qa_tags.reference_tolerance_span(self.num, None, None)
        qa_tags.reference_tolerance_span(self.boolean, self.ref_yes, None)
        qa_tags.reference_tolerance_span(self.mc, None, None)
        qa_tags.reference_tolerance_span(self.mc, None, self.mult_choice)
        result = qa_tags.reference_tolerance_span(self.num, self.ref, self.absolute)
        assert self.msgids(gettext) == {
            "No Ref",
            "Passing value = %(value)s",
            "No Tolerance Set",
            "No Tol",
            "%(status)s Values: %(choices)s",
            "All other choices are failing",
            "Choice",
            "(%(act)s L, %(tol)s L, %(tol)s H, %(act)s H) = %(limits)s",
        }
        assert "&lt;&lt;(ACT L, TOL L, TOL H, ACT H) = (-2.000" in result

    def test_tolerance_for_reference_messages(self, gettext):
        qa_tags.tolerance_for_reference(None, self.ref_yes)
        qa_tags.tolerance_for_reference(None, self.ref)
        qa_tags.tolerance_for_reference(self.mult_choice, None)
        result = qa_tags.tolerance_for_reference(self.absolute, self.ref)
        assert self.msgids(gettext) == {
            "%(status)s: %(value)s",
            "No",
            "N/A",
            "%(status)s: %(choices)s",
            "All others fail",
            "%(status)s: Between %(low)s & %(high)s",
            "%(status)s Between %(low)s & %(high)s",
            "%(status)s: < %(low)s or > %(high)s",
        }
        assert "&lt;&lt;Action: &lt; -1 or &gt; 3&gt;&gt;" in result
