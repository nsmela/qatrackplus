.. _qa_test_list_cycles:

Configuring Test List Cycles
============================

A **test list cycle** allows you to group multiple :ref:`Test Lists
<qa_test_lists>` into a single repeating cycle that can be assigned to a
unit.

For example, at our clinic, on a number of units, the therapists daily
QC is on a repeating 2 or 4 day cycle where the actual tests they
perform vary slightly by day. A test list cycle allows us to handle this
situation without the therapists having to keep track of which day was
done last.

For a 4 day cycle, you would create 4 separate test lists (e.g. Morning
Outputs Day 1, Morning Outputs Day 2, Morning Outputs Day 3, Morning
Outputs Day 4) and then create a Test List Cycle made up of those 4 Test
Lists. You would then assign that Test List Cycle to the unit with a
daily frequency, rather than assigning each of the 4 test lists
individually.

When a user performs a Test List Cycle, it checks which test list in the
cycle was performed last and automatically presents them with the tests
in the next days test list. So if Day 2 was performed yesterday, they
will be presented with the Day 3 tests today. You can also manually
override which day you want to perform.

Defining a test list cycle is described below.

Creating a new Test List Cycle
------------------------------

From the main admin page select the **Test List Cycles** page and click
the **Add Test List Cycle** button at the top right of the page.
The fields for defining a test list cycle are described below.

Name
----

A descriptive name that will be displayed in listings of test-lists.

Slug
----

A `slug is a URL friendly short
label <https://docs.djangoproject.com/en/dev/ref/models/fields/#slugfield>`__
for a test list. It should consist of only letters, numbers, underscores
and hyphens.

Description
-----------

*Optional*

A concise description of what this test list is for.

Drop Down Label
---------------

Set the text of the label of the drop down input used for choosing a one
of the test list members of this cycle. The default is "Choose Day".

Day Option Text
---------------

Choose whether to use the test list day number (i.e. Day 1, Day 2, ...)
or the test list name for display in the dropdown used for choosing one
of the test list members.

Test Lists in This Cycle
------------------------

The **Test Lists in This Cycle** card lists the days of the cycle, one test
list per day, in the order they will be performed. Each row shows the day
number, the test list's name and slug, and how many tests it has. Click a test
list's name to open it in a new tab.

To add a day, click **Add Test List** at the top of the card. A dialogue opens
where you can type part of a test list's name or slug to search for it, or pick
it from the list. A test list that is already in the cycle is marked
**Already in this cycle** and can't be added a second time. Click **Add** beside the one you want and it becomes
the last day of the cycle. Repeat this until you have added every day.

To change the order of the days, drag a row by its handle (the three lines at
the left of the row) to where you want it. The day numbers update as you drag.

To remove a day, click the bin icon at the right of its row. Nothing is
changed until you save, so if you remove the wrong day you can reload the page
without saving to get it back.

When you're done, click **Save and Continue Editing** and check that all your
test lists are there, in the right order.

Used In
-------

Once a cycle has been saved, the **Used In** card lists the units it is
assigned to, with each assignment's frequency, who it's assigned to and
whether it's active. Any change you save to the cycle applies to every one of
those units.

Attachments
-----------

You can add arbitrary attachments to a Test List Cycle (e.g. a PDF procedure
for performing the Test Lists which make up the Cycle) by uploading them using
the `Attachments` section at the bottom of the Test List Cycle configuration page.
