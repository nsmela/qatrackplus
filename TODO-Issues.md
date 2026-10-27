# Test List Builder: issues for review

Temporary. Written while working through `TODO-test-builder.md`, for the
maintainer to review. Remove before merging.

Every item in `TODO-test-builder.md` is done. No task needed more than three
attempts, so nothing was skipped. Each task was done by an agent with a
written plan, then checked (tests, lint, screenshots) and committed on
`feat/test-builder`. The whole project test suite passes (1652 tests).

## Decisions to review

These are choices made during the work that you may want to change.

### Editing modes and machine values
- **References and tolerances are set in a dialog in machine mode.** It
  uses the Unit Test Info admin form's rules and writes the same change
  history (one shared helper, also used by the admin page). It saves
  straight away, applies to that test on that unit in every list, and
  updates every matching row in place. There's no review step, as on the
  admin page. Needs `change_unittestinfo`; view-only users keep a link to
  the admin page.
  - The reference field starts filled with the current value; leaving it
    unchanged keeps the existing Reference, so history doesn't record a
    false change.
  - "Not set" is highlighted only where it causes "No Tol Set" on Perform
    QC: reference and tolerance for numerical types, reference for Yes/No,
    tolerance for text and multiple-choice types. Text-type references,
    Upload and Date tests show "Not used".
- **New Tolerance dialog** (stacked on the first): only the types that fit
  the test (none for Yes/No), saved through the Tolerance admin's form and
  duplicate check, which now includes the limit-order check. A duplicate
  offers "Use This One". The tolerance applies to the machine only when the
  first dialog is saved.
- **Shared settings are locked in machine mode.** Details become read-only
  and add/remove/reorder/outline controls are hidden, with a banner saying
  how to get back to the base list.
- **Which units appear:** direct assignments first, then "Through other test
  lists" for units that get the list through a parent list or a cycle. Each
  unit appears once. Needs `view_unittestinfo` or `change_unittestinfo`.
- **The chosen unit stays in the URL** (`?unit=`) and survives Save and
  Continue Editing.
- **Switching units with unsaved changes** asks first; switching reloads the
  page at that unit and drops the changes.
- **Tolerances display as the Unit Test Info admin shows them**, e.g.
  "Percent(-3.00%, -2.00%, 2.00%, 3.00%)". Yes/No references read Yes/No.
- **Type Value column (base list):** Constant shows its value; Multiple
  Choice its choices; Wraparound "low to high"; Composite, String Composite
  and Upload the first line of the calculation (cut at 60 characters, full
  text as a tooltip). Other types show "None".

### Preview
- **Full Perform QC preview only for direct assignments.** It's the real page
  in a frame, read-only: banner, no submit, no autosave, no upload, POST
  refused. Needs `change_testlist`.
  - It changes the real Perform QC template and `qa.js` behind a `preview`
    flag; the normal page is tested unchanged.
  - Composite calculations still call the server, which only calculates.
    Procedures using `UTILS.write_file` create an orphan attachment, as they
    do on Perform QC.
  - It ignores the assignment's visible-to groups and active flag.
  - It shows the last saved version, with a note when there are unsaved
    changes.
- **Base list and "through" units** get the layout preview with a note on
  how to see the full one.
- **Outlined sublists in the layout preview** copy Perform QC's look (grey
  rules above and below, name in italics), not a full box.

### Saving
- **One button group, in the title row**, which stays pinned on wide
  screens. Edit page: History · Delete · Cancel · Save As… · Save and
  Continue Editing · Save. Add page: Cancel · Save and Continue Editing ·
  Save. Django's bottom bar and "Save as new" are gone.
- **Save As…** checks the slug as you type and suggests a free one. If the
  copy fails validation, the page comes back as an add page for the copy and
  never touches the original. The copy opens in Base list mode.
- **Description and Duplicate dialogs save straight away** (they change the
  Test, not the test list), and each dialog says so.
- **Assign to Machine dialog saves straight away** and says so. It uses the
  Unit Test Collection admin form's rules, offers active units only (grouped
  by site), allows two Ad Hoc assignments to one unit as the admin page
  does, and writes an admin history entry.

### Unsaved changes
- **"Changed" means the form's posted values differ from when the page
  loaded**, covering field edits, added/removed/reordered rows, outline
  checkboxes and attachments. After a failed save the page starts as
  changed.
- **In-page dialog** for same-tab links (Cancel, breadcrumbs, History,
  Delete, header and sidebar links); the browser's own prompt covers reload,
  close and back. New-tab links and the Editor/Preview switch don't prompt.

### Layout and look
- **Sticky admin header:** the header and breadcrumbs are one pinned block
  on every admin page (`base_site.html`). A small script measures its height
  into `--qa-admin-top-h`, the only CSS custom property added (the height
  varies from 49 to 158px). Unpinned below 768px wide or 600px tall. The
  Test List title row pins under it except below 1024px wide or 700px tall.
- **List page, 1024px and narrower:** the filter card moves above the
  results, its groups side by side, each capped at 180px tall.
- **Search on the list page is a secondary button**, so "New Test List" is
  the page's one primary action.
- **Test counts:** the Tests & Sublists badge and the page header both count
  all tests, including those inside sublists ("7 tests · 1 sublist").
- **Parent Test List Memberships** sits directly below Tests & Sublists.
- **Header buttons:** Expand All, Add Sublist, Add Test.
- **Neutral colours:** category pills, type badges and sublist cards have
  one neutral style each; amber, per-category and per-type colours are gone.
  Tinted banners became grey with a `#424f57` left rule; errors keep a red
  rule.
- **Meta text on hovered rows is `#555`**, because the spec's `#6e7785`
  drops to about 4.2:1 on the hover colour.
- **Classes renamed to `tlb-`** where they clashed with `base.css`
  (`tl-table`, `tl-form`, `tl-field`).
- **Page titles:** "Test Lists", "Add Test List" and "<name> | Edit Test
  List" instead of Django's "Select test list to change" / "Change test
  list".

### Translation
- **The builder's JS strings live in a `TL_STRINGS` table** rendered by the
  template, because `makemessages -d djangojs` doesn't scan `<script>` blocks
  in `.html` files. New JS strings must be added there.
- **Type badges are translated with the context "test type badge".**

## Issue round: what each fix did

Every open item from the previous version of this file was given to its own
agent. Commits: `211c7e1`, `9f9a7ec`, `aded961`, `00feb64`, `e931c05`,
`f2cc15f`.

### Builder items (all fixed)
- **Change on a sublist** keeps its saved row (same id, order and outline)
  instead of nesting a new row; focus returns to Change. Typing in the
  search box now filters (the input had no `name`).
- **Repeated tests** are blocked in the Add Test / Add Sublist / Change
  dialogs (warning and disabled button, re-checked at click time).
- **Duplicate Test** copies references only with `change_unittestinfo`,
  makes new Reference rows (tolerances stay shared) and records history.
  Without the permission the copy starts with no unit settings.
- **Description edits** update `modified`/`modified_by` and add a History
  entry; unchanged saves do nothing.
- **Duplicate errors** (403/500/network/expired session) show a short
  message, never raw HTML.
- **Dialog backdrops** close through each dialog's own close function;
  dragging a text selection out of a dialog no longer closes it.
- **Delete permission**: saved rows show a locked remove button with a
  tooltip; validation only skips rows that will really be removed. Also
  fixed: a row added then removed was saved anyway without the permission.
- **Save As** in old browsers no longer triggers the leave prompt.
- **Contrast**: on the Test List pages links are `#357da7` (white only) or
  `#317399` (anywhere the background changes) and grey text `#6b6b6b`.
- **Narrow screens**: the builder table and list results fit down to 800px
  (sidebar collapsed) / 1024px (open) using container queries.
- **List filter card** scrolls inside itself; the page no longer scrolls at
  1440×900; results resize with the pinned header and filter toggles.
- **Stale JS**: `m2m_drag_admin_testlist.js` deleted, with a guard test.
- **Tolerance wording** in the builder is plain ("Tolerance −1 to 1 ·
  Action −2 to 2", "OK: a, b · Tolerance: c", "Action if wrong"); the
  stored name stays as a tooltip. `Tolerance.__str__`/`name` unchanged.

### Elsewhere in QATrack+ (fixed)
- **Percent tolerance with a changed reference** (bug confirmed): the form
  now validates against the new reference.
- **Unit Test Info history** reads Before → After, newest first, with
  "Not set" and "(No change)".
- **Yes/No references** are saved with the boolean type; older 1/0 ones read
  Yes/No everywhere a test is known (admin, Perform QC, reports, history).
  Display fix only, no data migration.
- **Perform QC repeated tests** (real bug): a test both direct and in a
  sublist made two rows and saved two conflicting values; composites used
  the last. `TestList.ordered_tests()` now lists each test once (first
  position), which also affects the API, history, charts and reports for
  such lists only.
- **"Do not treat…"** is one translatable string with a placeholder.
- **Deprecation warnings** (filtering by unsaved instances) are gone from
  the whole suite. Found on the way: `on_test_save` compared the test type
  with `is not`, so its Boolean-reference check rarely ran. It now runs (see
  Decisions) and the admin form reports it instead of a 500.
- **Dead `export_test_lists` action** removed.
- **Admin change forms** get `id="<model>_form"`; breadcrumbs follow view
  permission.
- **Admin list pages** show "Clear all filters", and results fill their
  column (Django 4's `changelist-form-container`).
- **"Submitting…"**, the home tooltip and calendar month names are
  translatable.
- **Admin pages on narrow windows** no longer scroll sideways (index layout,
  filter-horizontal selectors, long names, paginator, wide inlines).
- **Password pages** no longer request the removed zxcvbn library (404s and
  RequireJS errors; their focus code works again).

### Decisions from this round to review
- **Boolean reference check now enforced:** with `is not` fixed, a full save
  of a Boolean test is refused while any unit has a reference other than
  0/1. Old data in that state now blocks full saves of those tests until the
  references are fixed (description-only saves still work).
- **Repeated tests**, first occurrence wins. Sessions saved before the fix
  can still hold two TestInstances for one test; their review/edit pages
  will show duplicate rows. No data repair was done.
- **Duplicate Test without `change_unittestinfo`** creates no unit settings
  at all; the usual signals create empty ones when the list is saved.
- **Locked remove buttons** rather than hidden ones, so users see why.
- **Two link blues** on the Test List pages (could be unified on
  `#317399`).
- **Backdrop clicks** still close dialogs with typed input, as Cancel does.
- **Tolerance wording** uses the site's status names (not "Tol"/"Act") and
  shows limits as differences from the reference; numbers aren't
  locale-formatted.
- **Filter-horizontal selectors** keep their 980px desktop width.
- **No password strength meter**: zxcvbn wasn't vendored back.

## Left out on purpose

- **Pending migrations** (you chose to leave them out of this branch).
  `makemigrations --check` fails at the starting commit for attachments,
  faults, parts, qa, reports, service_log and units: about 200 `AlterField`
  operations syncing field options (verbose names, help text, related names,
  Python defaults). They produce no SQL on SQLite (not checked on
  PostgreSQL/SQL Server). They belong on `develop`.
- **"seperated" typo**: fixed (Tolerance multiple-choice help text and
  `Test.choices`), without a migration. The help-text change just joins the
  pending metadata migrations above. The fr, fr_CA and es `.po` files hold
  the old msgids; carry the French translations over when running
  `makemessages`. The Spanish one for `Test.choices` is a different
  sentence ("Debe dar al menos 1 opción…") and needs retranslating.
  `docs/developer/guide.rst:666` has the same typo. `Test.choices` also has
  `verbose_name="Description"`, which looks like a copy-paste error.

## Open issues found in this round

Builder:
- The list page is 449px wide at a 400px window because the Export /
  Import / New Test List buttons don't wrap.
- Admin dark theme: inputs inside builder dialogs render black
  (`#tl-dialogs-outside-form` isn't in the light-variable re-set list).
- `#6d7787`/`#6e7785` text is about 4.22:1 where it sits on hovered rows.
- `TestListAdminForm.clean` uses `filter(id__in=…)`, so the same test added
  twice directly is only caught by Django's generic duplicate message.
- The attachments delete control may not check the attachment inline's
  delete permission (not checked).
- A saved sublist card renders its `-id` hidden input twice (harmless).
- Machine mode: a sublist row's colspan spans hidden columns.
- On narrow screens the list page scrolls ~520px because the filter sits
  above the results; filter groups could start collapsed there.
- `#result_list thead th` padding never applies (Django's rule wins).
- "and N more" in the repeat warning isn't plural-aware.
- The description dialog's submit shares a class with Save As's.

Elsewhere:
- `/admin/qa/unittestcollection/` returns 500 when an assignment has no
  `assigned_to` (`assigned_to_name`).
- `/admin/parts/room/add/` returns 500 ("'Storage' instance needs to have a
  primary key value…").
- The admin index renders no app list (empty content block).
- Perform QC: `id="<slug>-procedure"` and `id="toggle-options"` repeat;
  one test type renders `string_value`/`json_value` inputs twice.
- Perform QC's tolerance text (`qa_tags.py`) has untranslated "Between",
  "All others fail", "No Ref", "No Tol" and uses `</br>`; it could reuse
  `Tolerance.plain_display`.
- `qatrack/static/qatrack_core/js/base.js:51`: untranslated "Submitting..."
  and `.addClass(".disabled")` (stray dot). The admin submit guard blocks
  later submits if a handler cancels the first one.
- `record_unit_test_info_change` stores `reference_changed=True` whenever a
  reference is submitted, even unchanged (the history display works around
  it).
- `templates/admin/qa/test/change_form.html:13` "Ref=… & Tolerance = …" can
  print None.
- The API returns raw reference type, so older Boolean references show
  "numerical".
- `templates/admin/change_form.html` drift from Django 4.2: hard-coded
  object tools, no `to_field_var`, `bodyclass` without app/model classes,
  "Add {{ verbose_name }}" word order, dead CSS.
- `templates/admin/change_list.html`: no `filters.js` (open/closed filter
  groups not remembered); error count not plural-aware.
- `testpack-export.js` has untranslated strings and exists twice
  (`qatrack/static/js/` and `qatrack/admin_media/js/`); `export.html` uses
  "...".
- `admin_media/js/drag_admin.js` and `jquery-1.7.1.min.js` are unused.
- "Succesfully" typo in `password_change_done.html` and
  `password_reset_complete.html` (translated string; .po files too).
- `perform.py` ~1637 translates a log message.
- Another `RemovedInDjango50Warning` (forms `default.html` templates)
  remains.
- `testlist_duplicate_test` has no per-object visibility check (any user
  with `add_test` can duplicate any test by id).

## Before merging

- Run `makemessages -l fr -l fr_CA -l es` (django and djangojs domains) and
  `compilemessages`; there are many new and changed strings.
- Run `collectstatic` on deployment: the collected RequireJS config still
  lists the removed zxcvbn entries until then.
- Remove `TODO-test-builder.md` and this file.
- Per `AGENTS.md`, a person needs to read the full diff, run the tests, and
  own the change before a PR is opened.

## Fixed along the way (for the record)

- Duplicate Test always failed with an IntegrityError (no `created_by`).
- The Duplicate and Description dialogs were inside the main form, so their
  buttons saved the whole test list.
- Validation counted rows removed in the builder, and removed rows came back
  after a validation error; unsaved rows disappeared after a failed save.
- Builder endpoints had no permission checks beyond staff.
- Search used hard-coded `/admin/` URLs (broken under a sub-path).
- The builder's dialogs and the description text weren't keyboard
  accessible.
- Tolerances accepted limits out of order (e.g. Tolerance Low 2, Tolerance
  High 1). `Tolerance.clean_tols` now requires Action Low ≤ Tolerance Low ≤
  Tolerance High ≤ Action High (blank limits skipped), for the Tolerance
  admin and the builder alike. Existing tolerances out of order aren't
  changed, but can't be saved again until fixed.
