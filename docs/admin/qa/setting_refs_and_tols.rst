.. _qa_ref_tols:

Setting Reference & Tolerance Values
====================================

When you :ref:`assign a test list to a unit <qa_assign_to_unit>` each of the
tests from that list are assigned a record of the reference value and
tolerance/action levels on that unit. Reference values and tolerance/action
levels are unit specific so you must set these values for every unit a test is
assigned to. Initially the reference value and tolerance/action levels are set
to null so you will need to update them if you want to subject your tests to
pass/fail criteria when performing a test list.

To set the reference and tolerance values click on the **Set References and
Tolerances** link from the main admin page. From here you will see a list of
all the test/unit pairs for any test list which has been assigned to a unit. To
set the reference value for a given test on a unit you can either browse
through the list or use the search box at the top of the page to find the test
you are looking for. Note, you may also use the filters at the side of the page
to narrow your search. The image below shows a search for a test which has been
assigned to two units.

.. figure:: images/setting_refs_and_tols/ref_tol_search.png
   :alt: Searching for a test on a unit

   Searching for a test on a unit

Once you have located the test/unit pair you want to set the reference for,
click on its name. From here you will see information about the current
reference value and tolerance/action levels including when these values were
last changed and who changed them.

.. figure:: images/setting_refs_and_tols/ref_tol.png
   :alt: Reference and tolerance example

   Reference and tolerance example

You can also set a reference and tolerance without leaving the list. Click the
pencil at the end of a row to open the same **Reference and Tolerance**
dialogue the Test List Builder uses. Change the reference or pick a tolerance
(or click **New Tolerance** to create one), add a comment if you like, then
save. The row updates in place, and the change is recorded in the test's
history just as if you had saved it from its own page.

Where the list shows **Not set** in bold with a warning sign, the missing
reference or tolerance is what makes the test show "No Tol Set" when QC is
performed. **Not used** means that type of test never uses one, so there is
nothing to set.

Numerical References & Tolerances
---------------------------------

If the test you are setting reference values for is numerical (e.g.
:ref:`simple numerical or composite test types <qa_tests>`) you can choose a
:ref:`tolerance/action level <qa_tolerances>` from the **Tolerances:** drop
down and set the reference value in the text box below that.

The tolerance/action levels of a test act as a window around the reference
value. For example if a certain test on a unit has reference value of 50 and a
tolerance/action level of +/- 2%/3% (i.e. lower action = -3%, lower tolerance =
-2 %, upper tolerance = 2%, upper action = 3%) then values between 49 and 51
will be considered within tolerance, values between 48.5 & 49 or 51 & 51.5 will
be considered at tolerance and values less than 48.5 or greater than 51.5 will
be considered failing.

Boolean References
------------------

For boolean tests you choose whether the reference value is Yes or No and whether
a mismatch between the reference value and the users selection should result in
a warning or a failure.

.. figure:: images/setting_refs_and_tols/boolean_tolerance.png
   :alt: Reference and tolerance example for boolean test

   Reference and tolerance example for boolean test


Multiple Choice References
--------------------------

Multiple choice tests have no reference value. For information about multiple
choice tolerances, please see the :ref:`tolerances page <qa_tolerances>`.


History
-------

As of version 0.3.0 users may add a comment when updating references and
tolerances and this comment will be shown with the history of changes for the
reference and tolerance.

.. figure:: images/setting_refs_and_tols/history.png
   :alt: Reference and tolerance history

   Reference and tolerance history


Setting multiple References & Tolerances at the same time
=========================================================

To set a group of tests to the same reference/tolerance value, go to the
``Set References & Tolerances`` page and select all the tests you want
to set:

.. figure:: images/setting_refs_and_tols/set_multiple_list.png
   :alt: Setting multiple references & Tolerance

   Setting multiple references & Tolerance

then select ``Set references and tolerances for selected tests`` from the
``Action`` dropdown list at the top and click ``Go``.

The tests you select must all be of one kind, so that one tolerance suits
them all: all numerical, all Boolean (Yes/No), or all text and multiple
choice. Upload and date tests don't use references or tolerances, so leave
them out. If your selection mixes kinds, you'll be sent back to the list with
a message explaining why.

On the next page choose the tolerance and reference to give every selected
test, add a comment saying why you're making the change (it is saved in each
test's reference & tolerance history), then click
``Set References & Tolerances``.

* Leave the tolerance on ``Keep each test's current tolerance`` to change only
  the reference, or choose ``No tolerance (clear it)`` to remove it.
* Leave the reference blank to keep each test's own reference and change only
  the tolerance. Boolean tests offer ``Yes`` or ``No`` instead, and text and
  multiple choice tests have no reference at all.
* Only the tolerances that suit the selected tests are offered: wraparound
  tests, for example, can only use absolute tolerances.

Every selected test is checked against the same rules as the single-test page
before anything is saved. If even one test can't take the new values (a
percent tolerance on a test with no reference, for example), nothing is saved
and that test is marked in the table with the reason, so you can fix your
choice or your selection and try again.

.. figure:: images/setting_refs_and_tols/set_multiple_value.png
   :alt: Setting multiple references & Tolerance

   Setting multiple references & Tolerance

Copying References & Tolerances between units
=============================================

It is possible to copy references and tolerances from one unit to
another. This is quite handy when you have the same test list assigned
to multiple units with the same reference values set.

From the main admin page click on the ``Copy References & Tolerances``
link in the QC section.

.. figure:: images/setting_refs_and_tols/copy_ref_tols.png
   :alt: Copy ref tols link

   Copy ref tols link

On the next page, choose the source unit and test list (cycle) and the
destination unit and click ``Preview``.

.. figure:: images/setting_refs_and_tols/copy_ref_tols_choose.png
   :alt: Copy ref tols select

   Copy ref tols select

Finally, you will see every reference and tolerance that will change, before
anything is copied. Click ``Copy References & Tolerances`` to copy them,
``Change Selection`` to go back and pick different units or test lists, or
``Cancel`` to leave without copying anything.

.. figure:: images/setting_refs_and_tols/copy_ref_tols_confirm.png
   :alt: Copy ref tols confirm

   Copy ref tols confirm
