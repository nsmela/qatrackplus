# Test List Builder: to do

Working list for the `feat/test-builder` branch. It combines the review of the
admin Test List pages against the design spec on `feature/design-system`
(`docs/developer/design_system.ai.md`) with features still to build.

Remove this file before the branch is merged.

## Features

- [x] **Dialog for "Assign to machine…"**
  - Replace the link that opens the Unit Test Collection add page in a new tab
    with a dialog on this page: unit, frequency, assigned to, visible to, and
    whether it is active.
  - Only available once the test list has been saved; until then, explain why
    in the button's tooltip or in the dialog.
  - When the dialog saves, add the new machine to the scope dropdown without
    reloading the page.
- [x] **Two editing modes: base list and a single machine**
  - Base list mode: the settings every machine shares (name, description,
    tests, sublists, attachments). No per-machine values are shown.
  - Machine mode: picking a machine in the scope dropdown loads that machine's
    settings (its references and tolerances for each test, frequency,
    assignment) and makes clear which edits apply to that machine only.
  - Switching machines with unsaved changes asks first, the same as leaving
    the page (see the unsaved changes item below).
  - Row columns change with the mode (tests in sublists too):
    - Base list (done): Test, Category, Type, Type Value. No Reference or Tolerance
      columns.
    - Machine: Test, Category, Type, Reference, Tolerance, taken from that
      machine's Unit Test Info. The Type Value column is replaced.
  - Type Value is the setting that belongs to the test's type, e.g. the
    value of a Constant, the choices of a Multiple Choice test, the
    calculation of a Composite. Show an empty-state word rather than "—"
    for types that have none (Numerical, Boolean, String, Upload, Date).
  - The dropdown currently only changes the hint text (`initScopeSelect`),
    which suggests a mode switch that doesn't happen. Until this is built,
    hide the dropdown or disable the machine options.
  - Settle where machine-mode edits are saved (Unit Test Infos) and how they
    relate to the change history for references and tolerances.
- [x] **Preview that matches the real Perform QC page**
  - Render the actual perform template and widgets, not a mock-up: Yes/No
    buttons, multiple-choice selects, file upload, composite tests calculated
    live, tolerance highlighting.
  - Show a clear, fixed banner: "This is only a preview. Nothing you enter
    here is saved."
  - Inputs in the preview must never submit to the server.
  - Open decision: preview with a dummy unit, or only when a machine is
    selected?
    - Recommendation: give the full preview only in machine mode, because
      references and tolerances (and so pass, tolerance and action) exist per
      machine. A dummy unit would show every test as "No Tol Set", which isn't
      what staff will see.
    - In base list mode, offer a layout-only preview (order, sublists,
      descriptions) and say there that pass/fail needs a machine selected.
- [x] **Set a machine's reference and tolerance from the builder**
  - Adding a test to a list assigned to machines creates that machine's
    settings with no reference or tolerance; Perform QC then records its
    results as "No Tol Set" with no warning (verified end to end).
  - In machine mode, a dialog on each row sets that machine's reference and
    tolerance, with the same rules and change history as the Unit Test Info
    admin page. Rows update in place.
  - "Not set" is highlighted on test types that use limits; Upload and Date
    tests show "Not used".
  - A "New Tolerance…" dialog, opened from that dialog, creates a missing
    tolerance on the page (only types that fit the test; same validation and
    duplicate check as the Tolerance admin) and selects it.
- [x] **"Outline" checkbox on each sublist row**
  - `Sublist.outline` already exists, and the perform page already draws
    each outlined sublist in its own box, headed with the sublist's name and
    description (`construct_sublist_borders`, `models.py:2922`).
  - The builder renders the checkbox hidden (`_sublist_card.html`), so today
    it can't be changed. Show it in the sublist header with a visible label,
    e.g. "Outline on Perform QC page".
  - Show the outline in the builder and in the preview, so the setting is
    visible without opening Perform QC.
- [x] **Warn about unsaved changes when leaving the page**
  - Track whether anything has changed: form fields, adding, removing or
    reordering tests and sublists, and attachments added or marked for
    removal.
  - Use `beforeunload` for closing the tab or browser navigation, and an
    in-page confirm for Cancel, the breadcrumb, the sublist "Edit" links and
    switching between Editor and Preview, if switching would lose anything.
  - Changing the selected machine in the scope dropdown (including back to
    Base list) prompts the same way as leaving the page. If the user chooses
    to stay, put the dropdown back to the previous selection and keep their
    changes.
  - Don't warn after a successful Save, or when nothing has changed.
  - Wording example: "You have changes that haven't been saved. Leave this page
    and lose them?"

## Behaviour fixes from the review

- [x] Reference column: "Pass = Yes" comes from `flag_when` and is wrong when
      `flag_when` is True, and Tolerance is always "—". Drop the
      `flag_when` "reference" from `get_test_metadata`; columns follow the
      mode rules under "Two editing modes" above.
- [x] Parent Memberships card says changes "immediately take effect"; they
      only apply on Save.
- [x] "Add description" saves the Test right away, outside the test list's
      Save. Either save it with the test list, or say in the dialog that it
      saves the test straight away for every list that uses it.
- [x] Add `change_test` / `add_test` permission checks to
      `testlist_test_desc_modal` and `testlist_duplicate_test`.
- [x] Replace the hard-coded `/admin/qa/testlist/search-*/` URLs in the JS
      with the `{% url %}` values, so search works when QATrack+ is installed
      under a sub-path.
- [x] Preview banner says "a live demonstration of how this Test List
      appears when performed", but every test gets a plain text box. Fix
      the wording now; the full fix is the preview item under Features.
- [x] "Duplicate" creates the new test immediately, before the test list is
      saved, and it stays even if the user then cancels. Say so in the
      dialog, or create it on Save.

## Design spec alignment

- [x] Category pills: use one neutral style instead of colours picked by
      matching English words in the name. Red stays reserved for QC Action.
- [x] Sublist cards: drop amber, which means Tolerance; use the neutral or
      primary palette.
- [x] Test type badges: one neutral style, or colours that pass 4.5:1 and avoid
      the status colours (Comp 3.19, Date 3.68, Const 3.74, SUBLIST 2.42 fail
      today).
- [x] Don't use link blue (`#3c8dbc`) as a button fill (Editor/Preview toggle,
      search "Add").
- [x] Raise low-contrast text and icons: `#94a3b8` 2.56, `#cbd5e1` 1.48,
      `#c4b5fd` 1.85, `#8c939d` 3.10. Don't redefine `.text-muted` globally.
- [x] Stop overriding shared classes globally in `testlist_assets.html`
      (`.text-success`, `.text-info`, `.text-muted`, `.btn-xs`, `.btn-danger`,
      `.btn-default`, `.margin-right-5`); scope them to the builder or drop
      them.
- [x] Write colour values directly instead of `:root` CSS variables
      (`--tl-*`), as the spec asks until QATrack+ adopts custom properties.
- [x] Replace the Tailwind-style greys with the spec's colours.
- [x] Radii only 0, 2px or 3px (no fully rounded pills, no 4px corners, no
      1.5px borders).
- [x] Card titles at 18px and not bold. Table headers at .03em letter spacing
      with 8/10 cell padding. No half-pixel font sizes.
- [x] Save buttons: the top right group ("Cancel", "Save Test List") and
      Django's bottom bar ("SAVE", "Save as new", "Save and continue
      editing", "Delete") don't match.
  - Either keep one group, or keep two that are identical: same buttons,
    labels, order and styles, ideally from one shared template so they can't
    drift apart.
  - Decide the button set. Candidates: Cancel, Save, Save and Continue
    Editing, Save As… (edit page only, see below), Delete (edit page only).
    Django's "Save as new" goes away.
  - Each group has one primary button (Save). Delete is ghost-style rather
    than solid red, and labels are Title Case, not uppercase.
- [x] "Save As…" in the top right group (edit page only): copies the
      current test list into a new one.
  - Opens a dialog asking for the new name and slug, prefilled like the
    Duplicate Test dialog ("Daily Linac QC (Copy)", `daily-linac-qc-copy`).
    The slug must be unique, so the copy can't reuse it.
  - Copies the details (description, warning message, JavaScript), the tests
    and sublists in order, and each sublist's outline setting. Doesn't copy
    attachments, machine assignments or parent memberships; the dialog says
    so, e.g. "Attachments and machine assignments aren't copied."
  - Copies the page as it is now, unsaved edits included; the original keeps
    its last saved state. Say so in the dialog, e.g. "The copy includes your
    unsaved changes. The original test list stays as it was last saved."
  - After saving, open the new test list, with a message naming the list it
    was copied from.
  - Needs `add_testlist` permission; hide the button without it.
  - Replaces Django's "Save as new": set `save_as = False` on
    `TestListAdmin` so it no longer appears, and remove its styles
    (`_saveasnew`) from the submit row CSS.
- [x] Rename `tl-` classes that clash with the shared blocks in `base.css`
      (`.tl-table`, `.tl-form`, `.tl-field`, `.tl-search`).
- [x] Translate the strings set in JavaScript and the type labels in
      `get_test_metadata`. Write the "EDITING", "TEST / SUBLIST" and "SUBLIST"
      `{% trans %}` strings in normal case and uppercase them with CSS.
- [x] Title Case buttons ("Add Test", "Add Sublist"); use "…" instead of "...".
- [x] Fix the search placeholder: there are no tags; the search covers name,
      description, slug and sublist names.
- [x] Icon-only buttons need an `aria-label`. Use `fa-trash-o` for removing a
      sublist.

## Layout and CSS bugs

- [x] List page: hide Django's "Select test list to change" heading.
- [x] List page: filter heading styles target `#changelist-filter > h3`, but
      Django 4.2 uses `<details><summary>`. The headings are nearly invisible
      in admin's dark mode.
- [x] List page: the Search button rule loses to Django's
      `#toolbar form input[type="submit"]`.
- [x] List page: at narrow widths the filter column runs off the page; collapse
      to one column.
- [x] List page: remove the stale `testlist_builder.css` comment in
      `change_list.html`.
- [x] Breadcrumbs: bring back the v3.1.0 Django admin breadcrumbs bar on
      both pages, as the header above the page title. v3.1.0 markup for
      reference:
      ```html
      <div class="breadcrumbs">
        <a href="/admin/">Home</a> ›
        <a href="/admin/qa/">QC</a> ›
        Test lists
      </div>
      ```
  - List page: "Home › QC › Test Lists".
  - Edit page: "Home › QC › Test Lists › Edit › 123", where 123 is the test
    list's ID (no "#"). Home, QC and Test Lists are links. On a new test
    list: "Home › QC › Test Lists › Add".
  - Label it "Test Lists" (Title Case), not v3.1.0's "Test lists". The model's
    plural name already renders as "Test Lists"; use
    `opts.verbose_name_plural|capfirst`, or a `{% trans %}` string if it
    differs.
  - `change_form.html` currently empties `{% block breadcrumbs %}` and draws
    its own `.tl-breadcrumbs` inside the form; override the block instead
    and drop `.tl-breadcrumbs`.
  - Remove the `.breadcrumbs` overrides in `testlist_assets.html` (lines
    27–57). They strip the admin bar's background and padding with
    `!important`, which is why the trail is plain grey text at the page edge
    today.
  - Build the links with `{% url 'admin:index' %}`,
    `{% url 'admin:app_list' 'qa' %}` and
    `{% url 'admin:qa_testlist_changelist' %}`, and take "QC" from
    `opts.app_config.verbose_name`, so they stay translated and work under a
    sub-path.
- [x] Sticky header across all of admin: when scrolling, keep the admin
      header (`#header`) and the breadcrumbs bar pinned to the top on every
      admin page, not only the Test List pages.
  - Put it in `qatrack/templates/admin/base_site.html` (its `extrastyle`
    block, or a static stylesheet it loads), not in `testlist_assets.html`.
  - Use `position: sticky` on one wrapper around the header and breadcrumbs,
    with a solid background and the spec's header shadow so content doesn't
    show through.
  - Check every admin page that changes the top of the page or scrolls on
    its own: the Test List pages, the other custom admin templates under
    `qatrack/templates/admin/` and `qatrack/*/templates/admin/`, the admin
    nav sidebar (`base_site.html` pins it at
    `top: 20px`; it needs the header height instead), and popup windows,
    which have no header.
  - Narrow screens: the admin header wraps onto more lines (two at 800px
    wide). Decide whether to unpin it there so it doesn't take up the
    screen.
  - Test List pages specifically: the list page's scrolling results
    (`initResultsScroll` measures from the top of the viewport), the sticky
    table headers inside the results, `scroll-padding-top` so jumps to
    errors and anchors aren't hidden under the header, and dialogs, which
    must stay above it.
  - Test List edit page: also pin the title row (title, counts and the Save
    button group) under the header and breadcrumbs, so Save is always in
    reach on a long list. This bears on the save buttons item: with the top
    group always visible, a second group at the bottom may not be needed.
  - The "Editing" scope bar (machine dropdown, Editor/Preview) is not
    pinned; it scrolls with the page.
- [x] Edit page: remove the "ID: 123" label from the Details card header
      (`#tl-details-card > div.tl-card-header > span`, i.e.
      `<span class="tl-card-id">` in `change_form.html`) and its
      `.tl-card-id` style. The ID is shown in the breadcrumbs instead.
- [x] Edit page: remove the bottom action bar of the Tests & Sublists card
      (`//*[@id="tl-tests-card"]/div[3]`, i.e. `div.tl-bottom-actions` with
      "Add sublist", "Add test" and the drag caption).
  - Move "Add Sublist" into the card header, beside the existing "Add Test"
    button (`#tl-header-add-test-btn`), styled the same.
  - Update the JS: the click handler listens for `#tl-add-sublist-btn` and
    `#tl-add-test-btn`, and `initViewTabs` hides `.tl-bottom-actions`.
  - Remove the `.tl-bottom-actions`, `.tl-add-btn` and `.tl-bottom-caption`
    styles.
  - The caption was the only place explaining drag-to-reorder; keep that as
    the drag handle's tooltip ("Drag to reorder"), which it already has.
  - Update the empty-state text, which says "Click 'Add test' or 'Add
    sublist' below".
- [x] Edit page: the "History" button is missing. `change_form.html`
      empties `{% block object-tools %}`, which removes Django's History link
      (`admin:qa_testlist_history`). Bring it back in the top right group
      (edit page only, not when adding), styled like the other secondary
      buttons.
- [x] Edit page: give the Duplicate dialog fields styles (`.tl-modal-field`,
      `.tl-modal-input` and `.tl-modal-hint` are missing).
- [x] Edit page: move Parent Memberships below Tests & Sublists.
- [x] Edit page: the Tests & Sublists badge (direct tests only) disagrees with
      the header count (includes sublist tests).

## Round 3

- [x] **Blank "New reference value" keeps the current reference**
  - Unit Test Info admin page: changing only the tolerance with the field
    blank currently clears the unit's reference
    (`UnitTestInfoForm.save()`, `elif 'reference_value' in
    self.cleaned_data: instance.reference = None`). Blank should keep the
    existing reference, as the builder's Reference and Tolerance dialog
    already does.
  - Check what still clears a reference on purpose (e.g. a test whose type no
    longer uses one) and how a user can clear it deliberately, and update
    the field's help text.
  - Check validation that reads the reference (percent tolerance, zero
    reference, wraparound) uses the kept reference when the field is blank.
- [x] **Type column: one chip with the type's full name**
  - Each row shows a short badge plus the full name
    (`tl-type-badge` + `tl-type-label` in `_test_row.html`). Replace both
    with a single chip reading the full type name (e.g. "Multiple Choice"),
    in rows, sublist rows and the search/add dialogs if they show the same
    pair.
- [x] **Machine mode: combine Reference and Tolerance into one column**
  - One "Reference & Tolerance" column whose content depends on the test
    type, instead of two columns with "Not used" filling the gaps.
    - Multiple Choice: no reference, so show only the tolerance (pass /
      tolerance choices).
    - Boolean: the expected value only.
    - Numerical, Simple Numerical, Constant, Composite, Wraparound: reference
      and tolerance together.
    - Upload, Date/Time, String types that use neither: a short neutral note,
      not "Not used" twice.
  - Keep the "Not set" warning where the type needs a value, the Set
    Reference & Tolerance dialog link, and the colspan sync for sublist rows
    (`syncColumnSpans`, column counts change).
- [x] **Test list rows align to the top of the cell**
  - Rows with a long name, description or type value currently centre their
    other cells vertically; align every cell to the top, in test rows and
    sublist rows.
- [x] **Machine mode: the Reference & Tolerance pencil in its own last column**
  - Machine mode only; the base list's actions column is already right.
  - Today the pencil that opens the Set Reference & Tolerance dialog (or the
    Unit Test Info page when the dialog isn't available) is appended inside
    the Tolerance cell (`fillMachineCells` in `testlist_assets.html`), while
    the actions column sits empty because its base-mode buttons are hidden.
    Put the pencil in that last column instead, in test rows and sublist
    test rows, with its current title/aria label.
  - Fits with the combined Reference & Tolerance column above; keep the
    column counts and `syncColumnSpans` right.
- [x] **Edit Test List header shows the test list's ID**
  - The page title reads "Edit Test List" (`h1.tl-header-title` in
    `change_form.html`). Add the ID there too (e.g. "Edit Test List · 123"),
    edit page only. The "ID: 123" label was removed from the Details card
    earlier and the ID is in the breadcrumbs; this puts it back in the
    pinned title row.
- [x] **Remove the test description dialog from the builder**
  - Editing a test belongs on the Test's own page (the pencil). Remove the
    description dialog: `_test_desc_modal.html`, the
    `testlist_test_desc_modal` endpoint and URL (`admin.py`), its JS/CSS
    (including the `tl-desc-submit` class from N11) and the tests that cover
    it.
  - The description text in each row (`_test_desc_cell.html`) becomes a link
    to the Test's edit page, opening in a new tab like the pencil, with the
    same title/aria wording ("… (opens in a new tab)"). Users without
    change_test keep the plain read-only text.
  - "Add Description" on tests without one: also link to the Test edit page
    (or drop it; decide when building).
  - Rows added in the browser (add/duplicate) render the same link.
- [x] **Attachments card above Tests & Sublists**
  - Edit page card order becomes Details, Attachments, Tests & Sublists,
    Parent Memberships (`#tl-attachments-card` currently sits last in
    `change_form.html`). Check the add page and the narrow-window layout,
    and that the unsaved-changes tracking and Browse/Remove handlers still
    find the card.
