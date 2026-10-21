.. _dev_design_system:

Design System
=============

This page records how QATrack+ looks and reads today, so that new pages (and
the pages being moved onto htmx) can match it without anyone having to
reverse-engineer the stylesheets. It describes the interface as it is on the
``feature/htmx`` branch at commit ``ac800345``. It is a record of what the
code does now, not a redesign.

QATrack+ is used between patients, often in a hurry, and what it records is
clinical evidence. Clarity and calm beat decoration every time.

The same values are available in machine-readable form in
:download:`design_system_tokens.json <design_system_tokens.json>`, one entry per
token with a note on where it is used. ``docs/developer/design_system.ai.md``
holds everything on this page and more (component markup, sizes, htmx
attributes) in a compressed form meant for AI coding tools rather than people.

.. note::

    QATrack+ has no CSS custom properties yet. Every value on this page is a
    literal colour or size from the stylesheets, given a name here by the role
    it plays. The names are for talking about the values, and nothing in the
    code uses them yet.

Where the styles come from
--------------------------

The interface is `AdminLTE 2.3.3 <https://adminlte.io/themes/AdminLTE/>`__ on
Bootstrap 3.3.6, with Font Awesome 4.7 for icons. QATrack+ changes it in a few
files, loaded in this order by ``qatrack/templates/site_base.html``:

* ``qatrack_core/static/adminlte/css/skins/skin-black-dark.css``: the dark
  header and sidebar.
* ``qatrack_core/static/qatrack_core/css/custom-adminlte.css``: QATrack+'s own
  primary colour, square boxes and alerts, and the small offset shadow on
  buttons and inputs.
* ``qatrack_core/static/qatrack_core/css/base.css``: utility classes, plus the
  shared in-place editing blocks (prefixed ``tl-`` and ``tle-``).
* Page stylesheets, such as ``faults/static/faults/css/faults.css`` for the
  fault details sections (prefixed ``fl-``).

Voice and content
-----------------

* Write for clinical staff, not developers: plain words, short sentences,
  and the *why* when it helps ("When the fault happened, not when it was
  logged").
* Page titles, box titles and menu items are in Title Case: "Perform QC",
  "Fault Types", "Last Modified".
* Help text, empty states and messages are in sentence case: "No description
  available", "New fault type, created when you save".
* Buttons are a verb or verb phrase: "Save", "Cancel", "Acknowledge This
  Fault".
* Error messages say what happened and what to do, and never leave doubt
  about whether something was saved: "The server could not be reached, so
  your change was not saved. Check your connection and try again."
* No emoji, no exclamation marks.
* Every string goes through Django's translation functions and ships in
  English, French, Canadian French and Spanish. Translations are often longer
  than the English, so let labels wrap rather than cutting them off.

Colour
------

QATrack+ has one colour theme.

.. list-table:: Chrome and surfaces
   :header-rows: 1
   :widths: 22 12 66

   * - Name
     - Value
     - Used for
   * - ``chrome-bg``
     - ``#222d32``
     - The top navigation bar and the sidebar.
   * - ``chrome-bg-deep``
     - ``#1e282c``
     - The logo block, and the hovered or active sidebar item.
   * - ``chrome-text``
     - ``#ffffff``
     - Navigation links and the logo. A hovered or open menu flips to black
       text on white.
   * - ``page-bg``
     - ``#ecf0f5``
     - The content area behind the boxes.
   * - ``surface``
     - ``#ffffff``
     - Boxes, dropdowns, inputs.
   * - ``surface-subtle``
     - ``#f4f4f4``
     - Default button fill, and the faint dividers inside a box.
   * - ``surface-foot``
     - ``#fbfcfd``
     - The Cancel / Save footer of a section being edited.
   * - ``border``
     - ``#d2d6de``
     - Inputs, table header rules, the top edge of a default box.

.. list-table:: Actions and text
   :header-rows: 1
   :widths: 22 12 66

   * - Name
     - Value
     - Used for
   * - ``primary``
     - ``#424f57``
     - QATrack+'s own primary (``.btn-primary``, ``.box-primary``), in place of
       AdminLTE's blue.
   * - ``info``
     - ``#627585``
     - ``.btn-info`` and info alerts.
   * - ``slate``
     - ``#748e9f``
     - The top edge of a ``.box-info``, which fault details sections use unless
       they ask for another kind (the Details section is ``.box-primary``).
   * - ``link``
     - ``#3c8dbc``
     - Links, the focus border on buttons and inputs, the "Editing" tag.
   * - ``text``
     - ``#444444``
     - Box and page titles.
   * - ``text-body``
     - ``#333333``
     - Body copy.
   * - ``text-label``
     - ``#555555``
     - Form labels and description list terms.
   * - ``text-meta``
     - ``#8a929e``
     - Timestamps and table column headers.
   * - ``text-faint``
     - ``#9aa2ae``
     - Empty states, hints and help text.

.. list-table:: Status colours
   :header-rows: 1
   :widths: 22 12 66

   * - Name
     - Value
     - Meaning
   * - ``status-ok``
     - ``#00a65a``
     - QC "OK", success, reviewed.
   * - ``status-tolerance``
     - ``#f39c12``
     - QC "Tolerance", needs attention, unreviewed. Also the default test
       status colour.
   * - ``status-action``
     - ``#dd4b39``
     - QC "Action", failed, errors and required-field markers.
   * - ``status-no-tol``
     - ``#00c0ef``
     - QC "No Tol Set".
   * - ``status-not-done``
     - ``#b5bbc8``
     - QC "Not Done" (with black text).

The status colours carry clinical meaning, so they are never used for
decoration, and they always appear with their word ("OK", "TOL", "ACT"). A
colour alone can't be read by colour-blind users or on a black-and-white
printout.

Service event and test statuses carry colours that administrators choose,
stored in the database. These are drawn as a 2px border around a transparent
label with black text (``.service-event-status-label``), so any colour an
administrator picks stays readable.

The full list, including hover states and the in-place editing palette, is in
:download:`design_system_tokens.json <design_system_tokens.json>`.

Type
----

* Everything is set in Source Sans Pro (300, 400, 600 and 700, with italics),
  served from ``qatrack_core/static/qatrack_core/fonts/`` rather than Google
  Fonts, because many clinics run offline.
* Body text is 14px. The htmx sections run a step smaller, at 13px, with 12px
  for timestamps, help text and small buttons.
* Labels, table headers and description list terms are weight 600, not bold.
* Small column headers and captions in sections are 11px, weight 700,
  uppercase, with 0.03em letter spacing.
* Codes and identifiers (fault types, for example) are 13px bold in
  ``Menlo, Consolas, monospace``.
* Page titles are 22px and box titles 18px, both at regular weight.
* The header wordmark is Helvetica Neue at weight 300, with "QAT" and "+"
  bold. A site's ``SITE_NAME`` replaces it.

Space, shape and depth
----------------------

* Boxes have 10px of padding and 20px between them. Fault details sections sit
  in a two-column grid with a 16px gap, which becomes one column below 900px.
* Corners are square: boxes, alerts, inputs, dropdowns and ``.btn-flat``
  buttons all have no radius. Raised buttons, chips and picker items use 3px,
  and labels and inline inputs 2px.
* Depth is a small hard shadow: ``2px 2px 2px #ddd`` under buttons and
  inputs, ``0 1px 1px rgba(0, 0, 0, 0.1)`` under boxes.
* A box's kind is shown by its 3px top edge, not by a filled header.

In-place editing with htmx
--------------------------

Details pages are built from section boxes that edit and save themselves
without reloading the page (``faults/templates/faults/sections/``):

* **Reading**: a pencil button in the box header opens the section for
  editing.
* **Editing**: the box gets a thin blue ring and an "Editing" tag, its body
  becomes a form, and a footer holds any search picker on the left and
  Cancel / Save on the right.
* **Busy**: while a request runs, the body dims and a spinner shows.
* **Saved**: the box returns to reading with a green "Saved" tick that fades
  after two seconds.
* **Invalid**: the server answers with HTTP 422 and the form with its errors,
  which ``site_base.html`` lets htmx show in place. Any other failure shows an
  alert saying the change was **not** saved.
* Changes that affect other parts of the page (the review status in the page
  header, "Last Modified") are sent back out of band.
* Search pickers wait 250 ms after typing, need at least two characters, and
  open their results upward from the footer so the box doesn't jump.
* Removing a row or an attachment only marks it. Nothing is deleted until
  Save.

The building blocks are shared so other pages can use them: ``.tl-iconbtn``
(small icon button), ``.tl-table`` (compact table), ``.tl-group-foot``
(section footer), ``.tl-search`` and ``.tl-pick-item`` (picker),
``.tl-form`` and ``.tl-field`` (form grid), and ``.tle-attach`` (attachment
chips).

Icons
-----

* Use Font Awesome 4.7 only (``<i class="fa fa-...">``), with the outline
  ``-o`` variants where they exist (``fa-trash-o``, ``fa-file-o``).
* Section headers: ``fa-info-circle`` Details, ``fa-tags`` Fault Types,
  ``fa-wrench`` Related Service Events, ``fa-paperclip`` Attachments,
  ``fa-history`` Record, ``fa-commenting-o`` Comments.
* Actions: ``fa-pencil`` edit, ``fa-trash-o`` remove, ``fa-check`` save,
  ``fa-undo`` undo, ``fa-plus-circle`` add, ``fa-search`` search.
* Icon-only buttons need a ``title``, and should also have an ``aria-label``.

The only logo in the repository is the "Q+" touch icon
(``qatrack_core/static/qatrack_core/img/apple-touch-icon.png``, 114 × 114).
There is no vector logo, and the header sets the name in text.

.. _dev_design_system_contrast:

Contrast checks to address
--------------------------

These colour pairs are in the code today and fall short of the `WCAG 2
<https://www.w3.org/TR/WCAG22/#contrast-minimum>`__ minimum of 4.5:1 for
normal-size text. People read QATrack+ on shared workstations, in dim
treatment rooms and on old monitors, so this matters more than it might
elsewhere.

Each row suggests the smallest change that passes, keeping the same hue. These
are proposals to discuss, not decisions: several are AdminLTE's colours and
change the look of every page.

.. list-table:: Text on a background
   :header-rows: 1
   :widths: 30 9 31 30

   * - Pair
     - Ratio
     - Where
     - Proposed
   * - ``text-faint`` ``#9aa2ae`` on white
     - 2.58
     - ``.tl-empty``, ``.tl-pick-hint``, ``.tl-field .help``,
       ``.tle-attach-size``, ``.fl-desc em``, idle ``.tl-iconbtn``
     - ``#6d7787`` (4.53)
   * - ``text-meta`` ``#8a929e`` on white
     - 3.14
     - ``.tl-table`` headers, ``.fl-meta``, ``.tl-pick-sub``,
       ``.fl-rec-label``, ``.tle-attach-add``
     - ``#6e7785`` (4.53)
   * - ``text-crumb`` ``#97a0b3`` on ``page-bg``
     - 2.30
     - ``.fl-breadcrumb``
     - ``#616d85`` (4.55)
   * - ``link`` ``#3c8dbc`` on white
     - 3.67
     - Links everywhere, ``.fl-editing-tag``
     - ``#357da7`` on white (4.52); ``#317399`` also passes on ``page-bg``
       (4.54)
   * - ``status-ok`` ``#00a65a`` as text on white
     - 3.18
     - ``.fl-rec-ok`` ("Reviewed"), ``.fl-saved``
     - ``#008749`` (4.60)
   * - ``unreviewed`` ``#b0761a`` on white
     - 3.85
     - ``.fl-unrev`` ("Unreviewed")
     - ``#a06c18`` (4.51)
   * - ``status-action`` ``#dd4b39`` as text on white
     - 4.09
     - ``.errorlist``, ``.fl-errors``, required ``*``
     - ``#da3b28`` (4.53), or reuse ``danger-deep`` ``#c0392b`` (5.44)
   * - ``text-muted`` ``#777777`` on white
     - 4.48
     - Bootstrap ``.text-muted``, popovers
     - ``#767676`` (4.54)
   * - ``#8aa4af`` on ``#2c3b41``
     - 4.43
     - Sidebar sub-menu links
     - ``#8eaab5`` (4.74)

.. list-table:: White text on a status colour
   :header-rows: 1
   :widths: 30 9 31 30

   * - Pair
     - Ratio
     - Where
     - Proposed
   * - White on ``status-tolerance`` ``#f39c12``
     - 2.19
     - ``.label-warning``, ``.btn-warning``, ``.tolerance``
     - Black text (9.58), as ``.not_done`` already does
   * - White on ``status-no-tol`` ``#00c0ef``
     - 2.15
     - ``.label-info``, ``.no_tol``
     - Black text (9.79)
   * - White on ``status-ok`` ``#00a65a``
     - 3.18
     - ``.label-success``, ``.btn-success``, ``.ok``, ``.fl-new``
     - Darker fill ``#008749`` (4.60), or black text (6.60)
   * - White on ``status-action`` ``#dd4b39``
     - 4.09
     - ``.label-danger``, ``.btn-danger``, ``.action``
     - Darker fill ``#d73925`` (4.67), already the hover colour
   * - White on ``#e76167``
     - 3.33
     - ``.box-comment.err-comment``
     - Black text (6.30)

Two things to keep in mind when working through these:

* QC status colours are configurable per site (test statuses and service event
  statuses have a colour field), so a fix to the defaults does not fix a
  site's own choices. Drawing a status as a border with black text, as service
  event labels already do, works with any colour.
* Changing a status colour changes what clinical staff are used to seeing.
  Darkening slightly keeps the meaning recognisable; changing the hue would
  not.
